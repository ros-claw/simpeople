"""Synthetic trigger contracts only; no native coverage inferred here."""
import copy
from pathlib import Path
import sys
import subprocess
import json

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from native_fault_triggers import NativeReleaseTriggers, validate_triggers
from simpeople.core.workloads import validate_case


@pytest.fixture
def setup():
    event={'event_id':'enter','at_s':0,'method':'move_prop','params':{'prop_id':'movable_box'},
           'trigger':{'kind':'native_diagonal_release','actor_id':'lead','witness_actor_id':'witness',
                      'placement':{'forward_m':3,'end_margin_m':.05,'z_m':.65}}}
    clear={'event_id':'clear','at_s':0,'method':'move_prop','params':{'prop_id':'movable_box','position_m':[-4,10,.65]},
           'trigger':{'kind':'event_applied','event_id':'enter','delay_s':8}}
    ctx={'session_id':'s','episode_id':'e','actor_id':'lead','actor_instance_id':'i','control_epoch':1,
         'task_id':'task','agent':'/lead/i','body_instance_id':'body','current_route_id':'r',
         'task_status':'running','cancel_requested':False,
         'route_native_task_id':7,'sdk_task_id':7,'position_m':[2,2,0],'sim_time':5,
         'witness':{'actor_id':'witness','status':'running','task_id':'w'}}
    tracking={'route_id':'r','native_task_id':7,'agent':'/lead/i','eligible':True,
              'diagonal_straight_enabled':True,'points_m':[[0,0,0],[10,10,0]]}
    release={'route_id':'r','native_task_id':7,'agent':'/lead/i','body_instance_id':'body',
             'original_points_m':tracking['points_m'],'position_m':[2,2,0],'removed_cells':[[0,0]]}
    return [event,clear],ctx,tracking,release


def observe(setup):
    events,ctx,track,release=setup;obj=NativeReleaseTriggers(events,{'lead','witness'})
    obj.observe('traffic_tail_tracking',track,ctx,1.25)
    obj.observe('traffic_tail_released',release,ctx,1.25)
    return obj


def test_only_actual_diagonal_release_resolves_one_current_path_point_and_relative_clear(setup):
    events,ctx,track,release=setup;obj=NativeReleaseTriggers(events,{'lead','witness'})
    assert obj.ready('enter',5,ctx) is None
    obj.observe('traffic_tail_tracking',track,ctx,1.25)
    assert obj.ready('enter',5,ctx) is None
    obj.observe('traffic_tail_released',release,ctx,1.25)
    params,proof=obj.ready('enter',5,ctx)
    assert params['position_m']==pytest.approx([2+3/2**.5,2+3/2**.5,.65])
    assert proof['release']['native_task_id']==7
    assert obj.ready('clear',99) is None
    obj.applied('enter',5)
    assert obj.ready('clear',12.999) is None and obj.ready('clear',13)[0]['position_m']==[-4,10,.65]
    with pytest.raises(ValueError,match='already applied'):obj.applied('enter',6)


def test_axis_release_never_counts_as_diagonal(setup):
    events,ctx,track,release=setup;track['points_m']=[[0,0,0],[10,0,0]];release['original_points_m']=track['points_m']
    obj=NativeReleaseTriggers(events,{'lead','witness'});obj.observe('traffic_tail_tracking',track,ctx,1.25);obj.observe('traffic_tail_released',release,ctx,1.25)
    assert obj.ready('enter',100,ctx) is None


@pytest.mark.parametrize('key,value',[('actor_instance_id','recreated'),('control_epoch',2),('session_id','new'),
                                    ('episode_id','new'),('task_id','new'),('current_route_id','new'),
                                    ('route_native_task_id',8),('sdk_task_id',8),('body_instance_id','new')])
def test_old_release_cannot_be_rebound_at_injection(setup,key,value):
    obj=observe(setup);ctx=copy.deepcopy(setup[1]);ctx[key]=value
    with pytest.raises(ValueError,match='stale'):obj.ready('enter',10,ctx)


def test_native_release_callback_itself_requires_actual_sdk_owner(setup):
    events,ctx,track,release=setup;obj=NativeReleaseTriggers(events,{'lead','witness'});obj.observe('traffic_tail_tracking',track,ctx,1.25);ctx['sdk_task_id']=0
    with pytest.raises(ValueError,match='actual native'):obj.observe('traffic_tail_released',release,ctx,1.25)


def test_completed_witness_cannot_establish_fault_interference_coverage(setup):
    obj=observe(setup);ctx=setup[1];ctx['witness']['status']='succeeded'
    with pytest.raises(ValueError,match='still-active'):obj.ready('enter',10,ctx)


@pytest.mark.parametrize('field,value',[('task_status','succeeded'),('task_status','failed'),('cancel_requested',True)])
def test_cleanup_motion_after_terminal_or_cancelled_lead_is_not_a_live_fault(setup,field,value):
    obj=observe(setup);ctx=setup[1];ctx[field]=value
    with pytest.raises(ValueError,match='uncancelled lead'):obj.ready('enter',10,ctx)


@pytest.mark.parametrize('field,value',[('forward_m',True),('forward_m',float('inf')),('end_margin_m',0),('z_m',-1)])
def test_invalid_or_hidden_placement_does_not_reach_native_driver(setup,field,value):
    events=copy.deepcopy(setup[0]);events[0]['trigger']['placement'][field]=value
    with pytest.raises(ValueError):validate_triggers(events,{'lead','witness'})


def test_forward_dependency_cycle_unknown_type_and_unknown_actor_are_rejected(setup):
    events=copy.deepcopy(setup[0]);events[1]['trigger']['event_id']='clear'
    with pytest.raises(ValueError,match='earlier event'):validate_triggers(events,{'lead','witness'})
    events=copy.deepcopy(setup[0]);events[0]['trigger']['kind']='eval'
    with pytest.raises(ValueError,match='unknown'):validate_triggers(events,{'lead','witness'})
    with pytest.raises(ValueError,match='known lead'):validate_triggers(setup[0],{'lead'})


def test_default_workload_reader_rejects_trigger_instead_of_silently_firing_by_time(setup):
    events=setup[0]
    case={'schema_version':'simpeople.benchmark.v1','case_id':'fixture','duration_s':60,
          'submission_mode':'open_arrival','busy_policy':'reject','scene':{'id':'scene','revision':'r'},
          'actors':[{'actor_id':'lead'},{'actor_id':'witness'}],'requests':[],'capture_profile':'full','events':events}
    with pytest.raises(ValueError,match='explicitly enabled'):validate_case(case)
    assert validate_case(case,allow_diagnostic_triggers=True)==case


def test_driver_rejects_trigger_without_flag_before_sdk_or_run_directory(setup,tmp_path):
    root=Path(__file__).parents[1];case=tmp_path/'case.json'
    case.write_text(json.dumps({'actors':[{'actor_id':'lead'},{'actor_id':'witness'}],'events':setup[0]}))
    rid='offline-trigger-rejection-'+tmp_path.name
    target=root/'runs'/rid;assert not target.exists()
    result=subprocess.run([sys.executable,str(root/'scripts/bench_native_runtime.py'),
                           '--case',str(case),'--run-id',rid],capture_output=True,text=True,timeout=20)
    assert result.returncode==2 and '--diagnostic-native-release-triggers' in result.stderr
    assert not target.exists()


def test_first_release_is_not_replaced_by_a_later_more_convenient_sample(setup):
    obj=observe(setup);_,ctx,_,release=setup
    later=copy.deepcopy(release);later['position_m']=[9,9,0];ctx['sim_time']=20
    obj.observe('traffic_tail_released',later,ctx,1.25)
    assert obj.first['lead']['observed_sim_time']==5
    assert obj.first['lead']['position_m']==[2,2,0]


@pytest.mark.parametrize('value',[None,False,'native_diagonal_release'])
def test_present_but_untyped_trigger_cannot_silently_become_timed_fault(setup,value):
    events=copy.deepcopy(setup[0]);events[0]['trigger']=value
    with pytest.raises(ValueError,match='typed object'):validate_triggers(events,{'lead','witness'})


@pytest.fixture
def local_setup(setup):
    events, ctx, _, _ = copy.deepcopy(setup)
    events[0]['trigger'].update(kind='native_local_yield_motion', placement={'forward_m':1.2,'end_margin_m':.05,'z_m':.65})
    ctx.update(position_m=[.2,0,0],sim_time=6,local_yield={'native_task_id':7,'body_generation':'body',
        'path_m':[[0,0,0],[1,0,0],[1,1,0]],'deadline_sim_time':13})
    payload={'route_id':'r','native_task_id':7,'agent':'/lead/i','actual_position_m':[.2,0,0]}
    obj=NativeReleaseTriggers(events,{'lead','witness'})
    return obj, ctx, payload


def test_local_fault_requires_actual_motion_not_submission_or_diagonal_release(local_setup):
    obj,ctx,payload=local_setup
    obj.observe('traffic_native_started',payload,ctx,1.25)
    assert obj.ready('enter',6,ctx) is None
    obj.observe('traffic_local_yield_motion_observed',payload,ctx,1.25)
    params,proof=obj.ready('enter',6,ctx)
    assert params['position_m']==pytest.approx([1,.4,.65])
    assert proof['placement']['target_progress_m']==pytest.approx(1.4)
    assert proof['kind']=='native_local_yield_motion'


@pytest.mark.parametrize('field,value', [('native_task_id',8),('body_generation','new'),
    ('path_m',[[0,0,0],[0,2,0]]),('deadline_sim_time',5),('deadline_sim_time',float('nan'))])
def test_local_yield_must_still_own_exact_path_and_live_deadline(local_setup,field,value):
    obj,ctx,payload=local_setup
    obj.observe('traffic_local_yield_motion_observed',payload,ctx,1.25)
    ctx['local_yield'][field]=value
    with pytest.raises(ValueError,match='stale'):obj.ready('enter',6,ctx)


@pytest.mark.parametrize('field,value',[('sdk_task_id',8),('body_instance_id','new'),('position_m',[.3,0,0])])
def test_local_callback_cannot_borrow_other_sdk_body_or_actual_root(local_setup,field,value):
    obj,ctx,payload=local_setup;ctx[field]=value
    with pytest.raises(ValueError,match='current owned'):obj.observe('traffic_local_yield_motion_observed',payload,ctx,1.25)


def test_local_motion_first_proof_is_not_rebound(local_setup):
    obj,ctx,payload=local_setup
    obj.observe('traffic_local_yield_motion_observed',payload,ctx,1.25)
    ctx.update(sim_time=7,position_m=[.8,0,0]);payload['actual_position_m']=[.8,0,0]
    obj.observe('traffic_local_yield_motion_observed',payload,ctx,1.25)
    _,proof=obj.ready('enter',7,ctx)
    assert proof['release']['position_m']==[.2,0,0]
    assert proof['release']['observed_sim_time']==6


def test_local_cancel_has_no_placement_and_retains_current_ownership(local_setup):
    obj,ctx,payload=local_setup
    event=copy.deepcopy(obj.events['enter']);event.update(method='cancel',params={'actor_id':'lead'})
    del event['trigger']['placement'];obj=NativeReleaseTriggers([event],{'lead','witness'})
    obj.observe('traffic_local_yield_motion_observed',payload,ctx,1.25)
    assert obj.ready('enter',6,ctx)[0]=={'actor_id':'lead'}
    ctx.pop('local_yield')
    with pytest.raises(ValueError,match='stale'):obj.ready('enter',6,ctx)


@pytest.mark.parametrize('position',[[2,2,0],[1,1,0]])
def test_local_box_cannot_be_moved_off_path_or_behind_current_root(local_setup,position):
    obj,ctx,payload=local_setup
    obj.observe('traffic_local_yield_motion_observed',payload,ctx,1.25);ctx['position_m']=position
    with pytest.raises(ValueError):obj.ready('enter',6,ctx)


def replacement_event(local_setup):
 obj,ctx,payload=local_setup
 event=copy.deepcopy(obj.events['enter']);event.update(method='run_activity',params={'actor_id':'lead','steps':[{'action':'move_to','target':[8.75,16.25,0],'timeout_s':15}]})
 del event['trigger']['placement']
 return event,ctx,payload


def test_only_local_motion_can_trigger_one_same_actor_standard_move_replacement(local_setup):
 event,ctx,payload=replacement_event(local_setup);obj=NativeReleaseTriggers([event],{'lead','witness'})
 obj.observe('traffic_local_yield_motion_observed',payload,ctx,1.25)
 assert obj.ready('enter',6,ctx)[0]==event['params']
 event['trigger']['kind']='native_diagonal_release'
 with pytest.raises(ValueError,match='unsupported'):validate_triggers([event],{'lead','witness'})


@pytest.mark.parametrize('fault',['other_actor','extra_method','many_steps','custom_action','missing_timeout','nonfinite','boolean','placement'])
def test_replacement_diagnostic_does_not_become_a_general_remote_command(local_setup,fault):
 e,_,_=replacement_event(local_setup)
 if fault=='other_actor':e['params']['actor_id']='witness'
 elif fault=='extra_method':e['params']['eval']='code'
 elif fault=='many_steps':e['params']['steps']*=2
 elif fault=='custom_action':e['params']['steps'][0]['action']='custom_action'
 elif fault=='missing_timeout':del e['params']['steps'][0]['timeout_s']
 elif fault=='nonfinite':e['params']['steps'][0]['target'][0]=float('inf')
 elif fault=='boolean':e['params']['steps'][0]['timeout_s']=True
 else:e['trigger']['placement']={'forward_m':1}
 with pytest.raises(ValueError):validate_triggers([e],{'lead','witness'})


def test_default_workload_and_timed_events_never_admit_replacement(local_setup):
 event,_,_=replacement_event(local_setup)
 c={'schema_version':'simpeople.benchmark.v1','case_id':'replacement_fixture','duration_s':90,
    'submission_mode':'open_arrival','busy_policy':'reject','scene':{'id':'industrial','revision':'frozen'},
    'actors':[{'actor_id':'lead'},{'actor_id':'witness'}],'requests':[],'capture_profile':'full','events':[event]}
 with pytest.raises(ValueError,match='explicitly enabled'):validate_case(c)
 assert validate_case(c,allow_diagnostic_triggers=True)==c
 del c['events'][0]['trigger']
 with pytest.raises(ValueError,match='invalid frozen fault'):validate_case(c,allow_diagnostic_triggers=True)


def wait_replacement(local_setup):
 event,ctx,payload=replacement_event(local_setup)
 event['params']['steps']=[{'action':'wait','duration_s':2,'timeout_s':15}]
 return event,ctx,payload


def test_wait_supersession_is_explicitly_typed_and_bound_to_actual_yield_motion(local_setup):
 event,ctx,payload=wait_replacement(local_setup)
 obj=NativeReleaseTriggers([event],{'lead','witness'})
 assert obj.ready('enter',6,ctx) is None
 obj.observe('traffic_local_yield_motion_observed',payload,ctx,1.25)
 assert obj.ready('enter',6,ctx)[0]==event['params']
 event['trigger']['kind']='native_diagonal_release'
 with pytest.raises(ValueError,match='unsupported'):validate_triggers([event],{'lead','witness'})


@pytest.mark.parametrize('changes',[{'duration_s':True},{'duration_s':float('nan')},
 {'duration_s':0},{'duration_s':31},{'timeout_s':True},{'timeout_s':float('inf')},
 {'duration_s':15},{'target':[0,0,0]},{'eval':'code'}])
def test_wait_diagnostic_cannot_omit_bounds_or_add_other_action_fields(local_setup,changes):
 event,_,_=wait_replacement(local_setup);event['params']['steps'][0].update(changes)
 with pytest.raises(ValueError):validate_triggers([event],{'lead','witness'})
