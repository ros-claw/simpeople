"""A stationary animation must not inflate the measured moving population."""
import importlib.util
import json
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('population_summary',Path(__file__).resolve().parents[1]/'scripts/summarize_run.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

@pytest.mark.parametrize('motion,expected',[('idle_sway',0),('walk',1),('episode_relocation',0)])
def test_participation_requires_real_excursion_not_cumulative_sway_or_reset(tmp_path,motion,expected):
    files={'config.json':{'scenario':'industrial_life','people':1,'duration':4},
           'metrics.json':{'sim_elapsed_s':4,'rtf':1},'tasks.json':[],
           'population.json':{'actor':{'cycle':1,'suspended':False,'role':'commuter'}},
           'asset_manifest.json':[{'asset_id':'default','runtime_radius_m':.3}]}
    for name,value in files.items():(tmp_path/name).write_text(json.dumps(value))
    (tmp_path/'events.jsonl').write_text('')
    rows=[]
    for n in range(41):
        episode='second' if motion=='episode_relocation' and n>=20 else 'first'
        x=n*.04 if motion=='walk' else .05*(n%2)
        if episode=='second':x+=100
        rows.append({'actor_id':'actor','episode_id':episode,'sim_time':n*.1,'ready':True,
                     'asset_id':'default','base_identity_id':'human','appearance_id':'original',
                     'position_m':[x,0,0],'action':'MoveTo' if motion=='walk' else 'Idle'})
    (tmp_path/'trajectories.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    result=module.summarize(tmp_path)
    assert result['actor_measurements']['actor']['distance_travelled_m']>1
    assert result['richness']['moving_participants']==expected
    assert result['functional_population_gate_passed']==bool(expected)
    assert result['trajectory_proxies']['root_discontinuities']==[]
