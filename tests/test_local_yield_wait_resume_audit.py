"""Synthetic counterexamples for the independent two-stage Native reviewer."""
import copy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_local_yield_wait_resume import review_resume


@pytest.fixture
def evidence():
    identity={'session_id':'s','episode_id':'e','actor_id':'a','actor_instance_id':'body'}
    wait={**identity,'control_epoch':2,'task_id':'wait','status':'succeeded','finished_sim_time':1.}
    steps=[{'action':'move_to','target':[1.,0.,0.],'timeout_s':15}]
    new={**identity,'control_epoch':3,'task_id':'resume','status':'succeeded','accepted_sim_time':1.,'finished_sim_time':61/30,
         'steps':[{**steps[0],'gait':'walk'}]}
    start={'agent':'/World/a','body_instance_id':'nativebody','route_id':'retired'}
    at={'ready':True,**wait,'sim_time':1.,'observation_sim_time':1.,'position_m':[0.,0.,0.],'speed_mps':0.,'native_task_id':20,
        'action':'Idle','native_actor_prim_path':'/World/a','traffic_body_instance_id':'nativebody','traffic_claim_cells':[]}
    current={**wait,'agent':'/World/a','body_instance_id':'nativebody','task_status':'succeeded','cancel_requested':False,'sdk_task_id':20,
             'position_m':[0.,0.,0.],'actual_observation':{'native_task_id':20,'observation_sim_time':1.}}
    wf={'result':{'task_id':'wait'},'event_id':'wait_fault'}
    rf={'method':'run_activity','resolved_params':{'actor_id':'a','steps':steps},'sim_time':1.,'cursor':100,'result':{'task_id':'resume'},
        'trigger_evidence':{'kind':'activity_succeeded','predecessor_event_id':'wait_fault','predecessor_receipt':wait,'current':current}}
    events=[{'kind':'task_ended','cursor':99,'task':wait},
            {'kind':'step_started','cursor':101,'task_id':'resume','sim_time':31/30,'step':new['steps'][0],'backend_task_id':'route-new'},
            {'kind':'traffic_native_started','cursor':102,'sim_time':32/30,'route_id':'route-new','native_task_id':21,**new}]
    rows=[at]
    for tick in range(31,62):
        x=max(0.,min(1.,(tick-31)/14));moving=32<=tick<=45
        rows.append({**at,**new,'sim_time':tick/30,'observation_sim_time':tick/30,'position_m':[x,0.,0.],
                     'speed_mps':30/14 if moving else 0.,'native_task_id':21 if moving else 20 if tick==31 else 22,
                     'traffic_claim_cells':[[0,0]] if moving else [],'action':'MoveAlong' if moving else 'Idle'})
    expected={'params':{'actor_id':'a','steps':steps}}
    return copy.deepcopy((start,wf,rf,events,rows,{'wait':wait,'resume':new},expected))


def test_actual_resumed_movement_and_stopped_goal_are_both_required(evidence):
    result=review_resume(*evidence)
    assert result['verified'],result['errors']
    assert result['max_actual_resume_displacement_m']==1.
    assert result['resume_native_task_ids']==[21] and result['actual_goal_hold_samples']==16
    assert result['new_owner_identity_verified'] and result['goal_hold_verified']


def test_failed_resume_is_not_misreported_as_wrong_identity(evidence):
    evidence[5]['resume']['status']='failed'
    result=review_resume(*evidence)
    assert not result['verified'] and result['new_owner_identity_verified']
    assert result['errors']==['resume task did not succeed: failed']
    assert result['goal_hold_verified']


def test_sixteen_recorded_samples_do_not_mean_they_satisfy_hold(evidence):
    for row in evidence[4][-16:]:row['speed_mps']=1.
    result=review_resume(*evidence)
    assert result['actual_goal_hold_samples']==16
    assert not result['goal_hold_verified'] and not result['verified']


@pytest.mark.parametrize('fault',['old_failed','wrong_wait_receipt','new_body','new_epoch','no_terminal_event','terminal_after_dispatch',
                                  'wrong_prim','wrong_native_body','no_sdk_lineage','other_sdk_owner','no_step',
                                  'deadline_extended','changed_goal','accepted_without_moving','moving_without_claims','lost_owner_midway',
                                  'gap_in_actual_stream','moving_at_goal','only_one_stopped_frame','nan_root','nan_speed','old_observation','duplicate_hold_frame'])
def test_metadata_success_cannot_hide_actual_route_failure(evidence,fault):
    start,wf,rf,events,rows,tasks,expected=evidence
    if fault=='old_failed':tasks['wait']['status']='failed'
    elif fault=='wrong_wait_receipt':rf['trigger_evidence']['predecessor_receipt']={**tasks['wait'],'task_id':'anotherwait'}
    elif fault=='new_body':tasks['resume']['actor_instance_id']='otherbody'
    elif fault=='new_epoch':tasks['resume']['control_epoch']=4
    elif fault=='no_terminal_event':events.pop(0)
    elif fault=='terminal_after_dispatch':events[0]['cursor']=105
    elif fault=='wrong_prim':rows[0]['native_actor_prim_path']='/World/other'
    elif fault=='wrong_native_body':rows[5]['traffic_body_instance_id']='otherbody'
    elif fault=='no_sdk_lineage':events.pop()
    elif fault=='other_sdk_owner':events[-1]['actor_id']='otheractor'
    elif fault=='no_step':events.pop(1)
    elif fault=='deadline_extended':events[1]['step']={**events[1]['step'],'timeout_s':30}
    elif fault=='changed_goal':tasks['resume']['steps']=[{**tasks['resume']['steps'][0],'target':[3.,0.,0.]}]
    elif fault=='accepted_without_moving':
        for r in rows:r['position_m']=[0.,0.,0.]
    elif fault=='moving_without_claims':
        for r in rows:r['traffic_claim_cells']=[]
    elif fault=='lost_owner_midway':rows[7]['control_epoch']=9
    elif fault=='gap_in_actual_stream':rows.pop(7)
    elif fault=='moving_at_goal':rows[-1]['speed_mps']=1.
    elif fault=='only_one_stopped_frame':
        for r in rows[-16:-1]:r['speed_mps']=1.
    elif fault=='nan_root':rows[-1]['position_m'][0]=float('nan')
    elif fault=='nan_speed':rows[-1]['speed_mps']=float('nan')
    elif fault=='old_observation':rows[-1]['observation_sim_time']=0.
    elif fault=='duplicate_hold_frame':rows[-2]=copy.deepcopy(rows[-3])
    result=review_resume(start,wf,rf,events,rows,tasks,expected)
    assert not result['verified'] and result['errors'],fault



def observed_exit_evidence(evidence):
    start,wf,rf,events,rows,tasks,expected=evidence
    endpoint=[.5,0.,0.]
    start.update(points_m=[[0.,0.,0.],endpoint],native_task_id=17)
    expected['trigger']={'resume_via':'observed_yield_exit'}
    rf['resolved_params']=copy.deepcopy(expected['params']);rf['resolved_params']['steps'][0]['via']=[endpoint]
    tasks['resume']['steps'][0]['via']=[endpoint]
    rf['trigger_evidence']['continuation']={'kind':'observed_yield_exit','source_yield_path_m':start['points_m'],
        'source_yield_native_task_id':17,'source_body_instance_id':'nativebody','via':[endpoint]}
    return evidence


def test_review_requires_actual_body_visit_to_observed_exit(evidence):
    result=review_resume(*observed_exit_evidence(evidence))
    assert result['verified'],result['errors']
    assert result['observed_exit_visit_error_m']<=.3


@pytest.mark.parametrize('fault',['changed_source_path','changed_sdk','changed_body','changed_via','missing_recipe','not_visited'])
def test_declared_via_and_observed_actual_route_are_both_required(evidence,fault):
    args=observed_exit_evidence(evidence);start,wf,rf,events,rows,tasks,expected=args;c=rf['trigger_evidence']['continuation']
    if fault=='changed_source_path':c['source_yield_path_m']=[[0.,0.,0.],[9.,9.,0.]]
    elif fault=='changed_sdk':c['source_yield_native_task_id']=99
    elif fault=='changed_body':c['source_body_instance_id']='otherbody'
    elif fault=='changed_via':c['via']=[[9.,9.,0.]]
    elif fault=='missing_recipe':rf['trigger_evidence'].pop('continuation')
    elif fault=='not_visited':
        for row in rows[1:-16]:row['position_m'][1]=2.
    result=review_resume(*args)
    assert not result['verified'] and result['errors'],fault
