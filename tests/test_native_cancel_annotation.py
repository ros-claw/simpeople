import copy
import importlib.util
from pathlib import Path

import pytest


spec=importlib.util.spec_from_file_location('cancel_annotation',Path(__file__).parents[1]/'scripts/audit_native_cancel_annotation.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


@pytest.fixture
def example():
    rows=[]
    for i in range(18):
        pose=[[0,0,0,0,0,0,1] for _ in range(81)];pose[10][0]=.2*(1-i/17)
        rows.append({'actor_id':'neutral_end','trial_id':0,'actor_instance_id':'i','session_id':'s','episode_id':'e',
                     'native_actor_prim_path':'/A','traffic_body_instance_id':'b','control_epoch':0,
                     'joint_paths':[f'j{x}' for x in range(81)],'sim_time':1.5+i/30,
                     'frame_identity':{'source_tick':45+i},'world_pose':pose,'retired_native_task_id':2,
                     'retired_native_status':'running' if i==0 else 'succeeded',
                     'actual_observation':{'ready':True,'action':'neutral_end' if i==0 else 'Idle',
                         'native_task_id':2 if i==0 else 3,'position_source':'BehaviorAgent.get_world_translation',
                         'observation_sim_time':1.5+i/30,'speed_mps':0.}})
    anchor=copy.deepcopy(rows[0]);anchor['world_pose'][10][0]=0
    trial={'trial_id':0,'started_sim_time':0,'cancel_sim_time':1.5,'requested_elapsed_s':1.5,'end_sim_time':rows[-1]['sim_time'],
           'anchors':{'neutral_end':anchor},'before_cancel':{'neutral_end':copy.deepcopy(rows[0])},
           'retired_native_ids':{'neutral_end':2},'actual_idle_times':{'neutral_end':[r['sim_time'] for r in rows[1:]]}}
    return trial,'neutral_end',rows


def test_actual_stop_and_world_steps_measured(example):
    result=module.measure(*example)
    assert result['physical_stop_observed'] and result['world_continuity_passed']
    assert result['non_neutral_at_cancel'] and result['actual_samples']==18
    assert result['actual_gap_from_own_idle_anchor_m']==pytest.approx(.2)


def test_large_jump_is_valid_measurement_but_bad_quality(example):
    example[2][8]['world_pose'][10][0]=.8
    result=module.measure(*example)
    assert result['physical_stop_observed'] and not result['world_continuity_passed']


def test_sdk_keeps_running_is_preserved_failure_measurement(example):
    trial,aid,rows=example
    for r in rows[1:]:r['retired_native_status']='running'
    trial['actual_idle_times'][aid]=[]
    result=module.measure(*example)
    assert not result['physical_stop_observed']


@pytest.mark.parametrize('bad',['duplicate','gap','stale','body','epoch','layout','nonfinite','not_custom',
                                'fake_idle','deadline','elapsed','wrong_retired','anchor','bool_tick','speed'])
def test_invalid_sdk_cancel_evidence_rejected(example,bad):
    trial,aid,rows=example
    if bad=='duplicate':rows.insert(8,copy.deepcopy(rows[8]))
    elif bad=='gap':rows.pop(8)
    elif bad=='stale':rows[8]['actual_observation']['observation_sim_time']-=1/30
    elif bad=='body':rows[8]['traffic_body_instance_id']='other'
    elif bad=='epoch':rows[8]['control_epoch']=1
    elif bad=='layout':rows[8]['joint_paths']=rows[8]['joint_paths'][:-1]
    elif bad=='nonfinite':rows[8]['world_pose'][10][0]=float('nan')
    elif bad=='not_custom':trial['before_cancel'][aid]['actual_observation']['action']='Idle'
    elif bad=='fake_idle':trial['actual_idle_times'][aid]=[1,2]
    elif bad=='deadline':trial['end_sim_time']=17
    elif bad=='elapsed':trial['started_sim_time']=.1
    elif bad=='wrong_retired':rows[8]['retired_native_task_id']=99
    elif bad=='anchor':trial['anchors'][aid]['actor_instance_id']='other'
    elif bad=='bool_tick':rows[8]['frame_identity']['source_tick']=True
    else:rows[8]['actual_observation']['speed_mps']=float('nan')
    with pytest.raises(ValueError):module.measure(*example)


def test_missing_native_run_never_qualifies(tmp_path):
    result=module.audit(tmp_path)
    assert not result['measurement_verified'] and not result['all_raw_sdk_cases_quality_passed']
    assert result['expected_comparisons']==6 and result['qualified_generated_native_rigs']==[]
