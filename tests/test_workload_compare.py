"""Offline evidence predicates; fabricated rows here are not native acceptance."""
import hashlib
import importlib.util
import json
from pathlib import Path


def test_cancelled_label_without_verified_stop_cannot_pass_paired_comparison(tmp_path):
    script=Path(__file__).resolve().parents[1]/'scripts/compare_workload_runs.py'
    spec=importlib.util.spec_from_file_location('workload_compare',script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    case={'duration_s':1/30,'requests':[{'request_case_id':'cancel','actor_id':'a','expected_outcome':'cancelled',
        'expected_physical_stop':True,'steps':[{'action':'wait','duration_s':1}]}]}
    digest=hashlib.sha256(json.dumps(case,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    folders=[tmp_path/name for name in ['before','after']]
    for folder in folders:
        folder.mkdir()
        files={'workload.json':case,'outcomes.json':{'case_sha256':digest,'scheduled':1,'submitted':1,'admitted':1,'counts':{'cancelled':1},
            'denominator':1,'conservation_passed':True,'requests':[{'request_case_id':'cancel','state':'cancelled','task_id':'t','submitted_at_s':0}]},
            'tasks.json':[{'task_id':'t','physical_stop_verified':True}],
            'runtime_contract.json':{'compatibility_sha256':'offline-fixture'},'source_manifest.json':{'bench_native_runtime.py':'same'},
            'measurement_end_state.json':{'actors':[{'actor_id':'a','observation':{'position_m':[0,0,0]}}]},
            'recording_metrics.json':{'frames_written':1,'empty_rgb_frames':0,'dropped_frames':0},'metrics.json':{}}
        for name,value in files.items():(folder/name).write_text(json.dumps(value))
        (folder/'trajectories.jsonl').write_text('')
    assert module.compare(*folders)['paired_functional_check_passed']
    (folders[1]/'tasks.json').write_text(json.dumps([{'task_id':'t','physical_stop_verified':False}]))
    result=module.compare(*folders)
    assert not result['paired_functional_check_passed'] and result['runs'][1]['expected_outcomes_matched']==0
