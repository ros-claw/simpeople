"""Compare frozen request outcomes without claiming a single-run speedup."""
import argparse
import hashlib
import json
import math
from pathlib import Path

def read(folder,name):return json.loads((folder/name).read_text())

def compare(baseline,candidate):
    folders=[Path(baseline),Path(candidate)];runs=[]
    for folder in folders:
        case=read(folder,'workload.json');outcomes=read(folder,'outcomes.json')
        digest=hashlib.sha256(json.dumps(case,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        assert digest==outcomes['case_sha256'],'case/result hash mismatch'
        assert outcomes['denominator']==len(case['requests'])==len(outcomes['requests']),'request denominator changed'
        assert {r['request_case_id'] for r in case['requests']}=={r['request_case_id'] for r in outcomes['requests']},'lost request IDs'
        expected={r['request_case_id']:r for r in case['requests']}
        tasks={t['task_id']:t for t in read(folder,'tasks.json')}
        matched=sum(r['state']==expected[r['request_case_id']].get('expected_outcome','succeeded') and
                    ('expected_error_code' not in expected[r['request_case_id']] or (r.get('error') or {}).get('code')==expected[r['request_case_id']]['expected_error_code']) and
                    ('expected_physical_stop' not in expected[r['request_case_id']] or tasks.get(r.get('task_id'),{}).get('physical_stop_verified')==expected[r['request_case_id']]['expected_physical_stop']) for r in outcomes['requests'])
        contract=read(folder,'runtime_contract.json');manifest=read(folder,'source_manifest.json')
        end=read(folder,'measurement_end_state.json');actors={a['actor_id']:a for a in end['actors']}
        final_requests={r['actor_id']:r for r in case['requests']}
        final_steps={aid:r['steps'][-1] for aid,r in final_requests.items() if r.get('expected_outcome','succeeded')=='succeeded'}
        cutoff_errors={aid:math.dist(actors[aid]['observation']['position_m'][:2],step['target'][:2]) for aid,step in final_steps.items() if step['action']=='move_to' and isinstance(step.get('target'),list)}
        receipts={r['request_case_id']:r for r in outcomes['requests']}
        goals={receipts[r['request_case_id']]['task_id']:(aid,final_steps[aid]) for aid,r in final_requests.items() if aid in cutoff_errors and receipts[r['request_case_id']].get('task_id')}
        goal_errors={}
        for line in (folder/'trajectories.jsonl').open():
            row=json.loads(line);tid=row.get('task_id')
            if tid not in goals or tasks[tid].get('finished_sim_time') is None:continue
            if abs(row['sim_time']-tasks[tid]['finished_sim_time'])<=1e-7:
                aid,step=goals[tid];goal_errors[aid]=math.dist(row['position_m'][:2],step['target'][:2])
        recording=read(folder,'recording_metrics.json');expected_frames=round((read(folder,'completed.json')['duration_s'] if case.get('stop_when_complete') else case['duration_s'])*30)
        runs.append({'run_id':folder.name,'case_sha256':digest,'compatibility_sha256':contract['compatibility_sha256'],
            'harness_hashes':{k:manifest[k] for k in sorted(manifest) if k=='bench_native_runtime.py' or k.startswith('harness/')},
            'metrics':read(folder,'metrics.json'),'outcomes':{k:outcomes[k] for k in ['scheduled','submitted','admitted','counts','denominator','conservation_passed']},
            'expected_outcomes_matched':matched,'all_expected_outcomes_matched':matched==len(expected),
            'position_error_at_cutoff_m':cutoff_errors,'position_error_at_completion_m':goal_errors,'end_position_tolerance_met':set(goal_errors)==set(cutoff_errors) and all(error<=final_steps[aid].get('tolerance_m',.3) for aid,error in goal_errors.items()),'recording':recording,
            'complete_capture':recording['frames_written']==expected_frames and recording['empty_rgb_frames']==0 and recording['dropped_frames']==0,
            'actual_submission_times_s':{r['request_case_id']:r['submitted_at_s'] for r in outcomes['requests']}})
    same_case=runs[0]['case_sha256']==runs[1]['case_sha256'];same_harness=runs[0]['harness_hashes']==runs[1]['harness_hashes'];same_runtime=runs[0]['compatibility_sha256']==runs[1]['compatibility_sha256']
    return {'same_frozen_case':same_case,'same_replay_harness':same_harness,'same_runtime_contract':same_runtime,
        'paired_functional_check_passed':same_case and same_harness and same_runtime and all(r['all_expected_outcomes_matched'] and r['complete_capture'] and r['end_position_tolerance_met'] for r in runs),
        'runs':runs,'limits':['one run per version; no performance improvement or statistical reliability claim',
            'closed-loop submission times may differ; frozen steps/dependencies and policies must match',
            'completion position error uses actual runtime samples at task completion; it is not a foot-slip or mesh-contact certification']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('baseline');p.add_argument('candidate');p.add_argument('--output',required=True);args=p.parse_args()
    result=compare(args.baseline,args.candidate);Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='runs'},indent=2))
    if not result['paired_functional_check_passed']:raise SystemExit(1)
