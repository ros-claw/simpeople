"""A followup is tied to a completed replacement wait, never a timed guess."""
import copy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from native_fault_triggers import NativeReleaseTriggers,validate_triggers
from simpeople.core.workloads import validate_case


@pytest.fixture
def setup():
    events=[{'event_id':'wait','at_s':0,'method':'run_activity','params':{'actor_id':'a','steps':[{'action':'wait','duration_s':2,'timeout_s':15}]},
             'trigger':{'kind':'native_local_yield_motion','actor_id':'a','witness_actor_id':'w'}},
            {'event_id':'resume','at_s':0,'method':'run_activity','params':{'actor_id':'a','steps':[{'action':'move_to','target':[10.8,16.5,0],'timeout_s':15}]},
             'trigger':{'kind':'activity_succeeded','event_id':'wait','actor_id':'a','witness_actor_id':'w'}}]
    witness={'actor_id':'w','actor_instance_id':'wi','task_id':'wt','control_epoch':1,'status':'running'}
    old={'session_id':'s','episode_id':'e','actor_id':'a','actor_instance_id':'i','control_epoch':1,'task_id':'old',
         'agent':'/World/a/Instance1','body_instance_id':'nativebody','witness':witness}
    receipt={k:old[k] for k in ['session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id']}
    receipt.update(control_epoch=2,task_id='waittask',status='accepted')
    current={**old,**receipt,'task_status':'running','cancel_requested':False,'sdk_task_id':20,'sim_time':6.,
             'actual_observation':{'ready':True,'action':'Idle','native_task_id':20,'speed_mps':0.,'observation_sim_time':6.}}
    obj=NativeReleaseTriggers(events,{'a','w'})
    return events,obj,old,receipt,current


def applied(setup):
    e,obj,old,receipt,current=setup
    obj.applied('wait',4.,receipt=receipt,context=old)
    return obj,current


def test_no_elapsed_delay_substitutes_for_wait_success(setup):
    e,obj,old,receipt,current=setup
    assert obj.ready('resume',100,current) is None
    obj.applied('wait',4.,receipt=receipt,context=old)
    assert obj.ready('resume',100,current) is None
    current['task_status']='succeeded'
    params,proof=obj.ready('resume',100,current)
    assert params==e[1]['params']
    assert proof['predecessor_receipt']['task_id']=='waittask'
    assert proof['current']['body_instance_id']=='nativebody'


@pytest.mark.parametrize('field',['session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id','agent','body_instance_id'])
def test_old_success_cannot_rebind_to_replaced_owner(setup,field):
    obj,current=applied(setup);current['task_status']='succeeded';current[field]='changed'
    with pytest.raises(ValueError,match='stale'):obj.ready('resume',8,current)


@pytest.mark.parametrize('status',['failed','cancelled'])
def test_failed_prerequisite_never_dispatches_followup(setup,status):
    obj,current=applied(setup);current['task_status']=status
    with pytest.raises(ValueError,match='did not succeed'):obj.ready('resume',8,current)


@pytest.mark.parametrize('fault',['moving','stale_observation','other_sdk','not_idle','nan_speed','boolean_speed','invalid_context_clock','boolean_sdk'])
def test_success_still_requires_current_actual_stationary_idle(setup,fault):
    obj,current=applied(setup);current['task_status']='succeeded';o=current['actual_observation']
    if fault=='moving':o['speed_mps']=.2
    elif fault=='stale_observation':o['observation_sim_time']=5.
    elif fault=='other_sdk':o['native_task_id']=19
    elif fault=='not_idle':o['action']='MoveTo'
    elif fault=='nan_speed':o['speed_mps']=float('nan')
    elif fault=='boolean_speed':o['speed_mps']=False
    elif fault=='invalid_context_clock':current['sim_time']=float('nan')
    elif fault=='boolean_sdk':o['native_task_id']=True;current['sdk_task_id']=1
    assert obj.ready('resume',8,current) is None


@pytest.mark.parametrize('fault',['other_witness','new_witness_body','new_witness_task','new_witness_epoch','witness_done'])
def test_followup_keeps_same_live_witness(setup,fault):
    obj,current=applied(setup);current['task_status']='succeeded'
    field={'other_witness':'actor_id','new_witness_body':'actor_instance_id','new_witness_task':'task_id','new_witness_epoch':'control_epoch','witness_done':'status'}[fault]
    current['witness'][field]='succeeded' if fault=='witness_done' else 'changed'
    with pytest.raises(ValueError,match='witness'):obj.ready('resume',8,current)


@pytest.mark.parametrize('fault',['missing','wrong_body','same_task','old_epoch','failed','missing_native_context'])
def test_actual_receipt_required_before_recording_applied_time(setup,fault):
    e,obj,old,receipt,current=setup
    if fault=='missing':receipt={}
    elif fault=='wrong_body':receipt['actor_instance_id']='new'
    elif fault=='same_task':receipt['task_id']='old'
    elif fault=='old_epoch':receipt['control_epoch']=1
    elif fault=='failed':receipt['status']='failed'
    elif fault=='missing_native_context':old=None
    with pytest.raises(ValueError,match='actual newly accepted'):obj.applied('wait',4,receipt=receipt,context=old)
    assert 'wait' not in obj.applied_times


@pytest.mark.parametrize('fault',['no_parent','future_parent','non_wait_parent','other_actor','different_witness','extra_key','many_steps','not_move','missing_timeout','nonfinite'])
def test_followup_contract_is_bounded_and_not_general_remote_execution(setup,fault):
    e=setup[0];t=e[1]['trigger'];p=e[1]['params']
    if fault=='no_parent':t['event_id']='unknown'
    elif fault=='future_parent':e.reverse()
    elif fault=='non_wait_parent':e[0]['params']['steps'][0]={'action':'move_to','target':[0,0,0],'timeout_s':15}
    elif fault=='other_actor':p['actor_id']='w'
    elif fault=='different_witness':t['witness_actor_id']='a'
    elif fault=='extra_key':t['eval']='code'
    elif fault=='many_steps':p['steps']*=2
    elif fault=='not_move':p['steps'][0]={'action':'custom_action','target':'unknown','timeout_s':15}
    elif fault=='missing_timeout':p['steps'][0].pop('timeout_s')
    elif fault=='nonfinite':p['steps'][0]['target'][0]=float('nan')
    with pytest.raises(ValueError):validate_triggers(e,{'a','w'})


def test_followup_is_diagnostic_only_in_core_workload_reader(setup):
    c={'schema_version':'simpeople.benchmark.v1','case_id':'diagnostic_wait_resume','duration_s':90,
       'submission_mode':'open_arrival','busy_policy':'reject','scene':{'id':'industrial','revision':'frozen'},
       'actors':[{'actor_id':'a'},{'actor_id':'w'}],'requests':[],'capture_profile':'full','events':setup[0]}
    with pytest.raises(ValueError,match='explicitly enabled'):validate_case(c)
    assert validate_case(c,allow_diagnostic_triggers=True)==c


def with_observed_exit(setup):
    events,_,old,receipt,current=setup
    events[1]['trigger']['resume_via']='observed_yield_exit'
    old['sdk_task_id']=17
    old['local_yield']={'path_m':[[0.,1.,0.],[-1.,0.,0.]],'body_generation':'nativebody','native_task_id':17}
    current['task_status']='succeeded'
    obj=NativeReleaseTriggers(events,{'a','w'})
    return events,obj,old,receipt,current


def test_resume_via_uses_exact_original_observed_exit_and_keeps_goal(setup):
    events,obj,old,receipt,current=with_observed_exit(setup)
    obj.applied('wait',4,receipt=receipt,context=old)
    old['local_yield']['path_m'][-1]=[99.,99.,0.]
    params,proof=obj.ready('resume',8,current)
    assert params['steps'][0]['via']==[[-1.,0.,0.]]
    assert params['steps'][0]['target']==[10.8,16.5,0]
    assert 'via' not in events[1]['params']['steps'][0]
    assert proof['continuation']['source_yield_native_task_id']==17
    assert proof['continuation']['source_body_instance_id']=='nativebody'


@pytest.mark.parametrize('fault',['missing','other_body','other_sdk','missing_sdk','nonfinite','boolean_point','short_path'])
def test_resume_waypoint_cannot_borrow_another_or_malformed_source_path(setup,fault):
    events,obj,old,receipt,current=with_observed_exit(setup)
    local=old['local_yield']
    if fault=='missing':old.pop('local_yield')
    elif fault=='other_body':local['body_generation']='other'
    elif fault=='other_sdk':local['native_task_id']=18
    elif fault=='missing_sdk':local['native_task_id']=None;old['sdk_task_id']=None
    elif fault=='nonfinite':local['path_m'][-1][0]=float('nan')
    elif fault=='boolean_point':local['path_m'][-1][0]=True
    elif fault=='short_path':local['path_m']=local['path_m'][-1:]
    obj.applied('wait',4,receipt=receipt,context=old)
    with pytest.raises(ValueError,match='original observed owned yield exit'):obj.ready('resume',8,current)


@pytest.mark.parametrize('value',[None,True,'eval','free_space'])
def test_unknown_continuation_recipe_is_rejected(setup,value):
    events=setup[0];events[1]['trigger']['resume_via']=value
    with pytest.raises(ValueError):validate_triggers(events,{'a','w'})
