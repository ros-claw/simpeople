"""Observed SDK reuse needs both prior provenance and actual new-owner frames."""
import copy
import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('idle_adoption_audit',Path(__file__).resolve().parents[1]/'scripts/audit_owned_idle_adoption.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


@pytest.fixture
def evidence():
    old={'actor_id':'a','actor_instance_id':'body1','session_id':'s','episode_id':'e','control_epoch':1,'task_id':'old','status':'succeeded'}
    new={**old,'task_id':'new','control_epoch':2,'status':'succeeded','started_sim_time':1.,'finished_sim_time':2.,'steps':[{'action':'look_at','target':[0,100,1],'max_angle_deg':.15,'timeout_s':8}]}
    events=[{'kind':'native_task_bound','cursor':1,'sim_time':.5,'native_task_id':5,**old},
            {'kind':'task_ended','cursor':2,'sim_time':29/30,'task':old},
            {'kind':'native_idle_adopted_for_precision','cursor':3,'sim_time':1.,'native_task_id':5,'agent':'/World/a','issued_new_sdk_command':False,'observation_sim_time':1.},
            {'kind':'native_task_bound','cursor':4,'sim_time':1.,'native_task_id':5,**new}]
    def row(task,tick):
        return {'actor_id':'a','actor_instance_id':'body1','activity_task_id':task['task_id'],'task':task,'source_tick':tick,'sim_time':tick/30,
                'actual_observation':{'ready':True,'native_task_id':5,'action':'Idle','speed_mps':0.,'observation_sim_time':tick/30}}
    rows=[row(old,29),row(new,30),row(new,31)]
    prep={'task':new,'second_before':{'task_id':'untouched','control_epoch':1,'native_task_id':77},'second_after':{'task_id':'untouched','control_epoch':1,'native_task_id':77}}
    trajectory=[{'actor_id':'a','actor_instance_id':'body1','session_id':'s','episode_id':'e','native_actor_prim_path':'/World/a','sim_time':1.}]
    return copy.deepcopy((events,rows,prep,trajectory))


def test_equal_sdk_id_is_read_back_under_new_owner(evidence):
    result=audit.review(*evidence)
    assert result['verified'] and result['observed_reuse_samples']==2
    assert result['previous_task_id']=='old' and result['new_task_id']=='new'
    assert not result['generated_motion_verified'] and result['qualified_generated_native_rigs']==[]


@pytest.mark.parametrize('fault',['no_trigger','external_sdk','different_body','old_running','wrong_old_epoch',
                                 'new_running_without_bind','one_frame','duplicate_frame','wrong_row_owner','stale_read',
                                 'new_sdk_id','moving','wrong_agent_prim','unrelated_actor_changed','late_completion'])
def test_corrupted_or_unexercised_handoff_is_not_verified(evidence,fault):
    events,rows,prep,trajectory=evidence
    if fault=='no_trigger':events[:]=[e for e in events if e['kind']!='native_idle_adopted_for_precision']
    elif fault=='external_sdk':events[0]['native_task_id']=4
    elif fault=='different_body':events[0]['actor_instance_id']='otherbody'
    elif fault=='old_running':events[1]['task']['status']='running'
    elif fault=='wrong_old_epoch':events[0]['control_epoch']=0
    elif fault=='new_running_without_bind':events.pop()
    elif fault=='one_frame':rows.pop()
    elif fault=='duplicate_frame':rows[-1]=copy.deepcopy(rows[-2])
    elif fault=='wrong_row_owner':rows[-1]['task']={**rows[-1]['task'],'actor_instance_id':'otherbody'}
    elif fault=='stale_read':rows[-1]['actual_observation']['observation_sim_time']=0.
    elif fault=='new_sdk_id':rows[-1]['actual_observation']['native_task_id']=6
    elif fault=='moving':rows[-1]['actual_observation']['speed_mps']=.3
    elif fault=='wrong_agent_prim':events[2]['agent']='/World/other'
    elif fault=='unrelated_actor_changed':prep['second_after']['control_epoch']=2
    elif fault=='late_completion':prep['task']['finished_sim_time']=10.
    result=audit.review(events,rows,prep,trajectory)
    assert not result['verified'] and result['errors']
    assert not result['generated_motion_verified']
