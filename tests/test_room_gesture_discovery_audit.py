import copy
import importlib.util
from pathlib import Path

import pytest


spec=importlib.util.spec_from_file_location('room_discovery',Path(__file__).parents[1]/'scripts/audit_room_gesture_discovery.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


@pytest.fixture
def example():
    owner={'session_id':'s','episode_id':'e','actor_id':'a','actor_instance_id':'i','control_epoch':3,'task_id':'t'}
    task={**owner,'status':'succeeded','steps':[{'action':'head_look','duration_s':.6,'timeout_s':8}]}
    event={'task_id':'t','hold_sim_s':.6,'sim_time':1.6}
    start={'native_task_id':7,'agent':'/A','action':'head_look','target_m':[0,1,1.5],'baseline':{}}
    binding={**owner,'native_task_id':7};rows=[];overlays=[]
    for i in range(19):
        row={**owner,'sim_time':1+i/30,'observation_sim_time':1+i/30,'frame_identity':{'source_tick':i},
             'native_actor_prim_path':'/A','traffic_body_instance_id':'b','ready':True,
             'position_source':'BehaviorAgent.get_world_translation'}
        rows.append(row);overlays.append({**copy.deepcopy(row),'owned':{'native_task_id':{'native_task_id':7,'actual_status':'running'}}})
    return task,event,start,binding,rows,overlays,lambda *args:{'aligned':True}


def test_running_overlay_and_joint_interval_both_required(example):
    proof=module.hold(*example)
    assert proof['actual_samples']==19 and proof['hold_sim_s']==pytest.approx(.6)
    assert proof['actual_running_gesture_native_id']==7


@pytest.fixture
def completed_boundary(example):
    task,event,start,binding,rows,overlays,measure=example
    event['cursor']=12
    overlays[-1]['owned']={'native_task_id':{'native_task_id':7,'actual_status':'failed'},
                          'return_task_id':{'native_task_id':8,'actual_status':'running'}}
    fields={k:task[k] for k in module.OWNER if k!='task_id'}
    end={**fields,'kind':'native_task_ended','task_id':'7','logical_task_id':'t','native_task_id':'7',
         'agent':'/A','sim_time':1.6,'cursor':10,'task_error_name':'BehaviorTaskError.CANCELED','correlation_status':'unique'}
    returned={**fields,'kind':'native_gesture_return_started','task_id':'t','original_native_task_id':7,
              'native_task_id':8,'agent':'/A','sim_time':1.6,'cursor':11}
    return (*example,[end,returned])


def test_exact_post_tick_cancellation_at_last_measured_pose(completed_boundary):
    assert module.hold(*completed_boundary)['actual_samples']==19


@pytest.mark.parametrize('bad',['earlier_sample','earlier_cancel','other_task','other_body','epoch','noncancel_error',
    'missing_end','missing_return','wrong_return','return_order','cursor_nan','ambiguous_end','last_geometry'])
def test_boundary_exception_never_hides_an_early_or_unowned_failure(completed_boundary,bad):
    task,event,start,binding,rows,overlays,measure,events=completed_boundary
    if bad=='earlier_sample':overlays[-2]['owned']=copy.deepcopy(overlays[-1]['owned'])
    elif bad=='earlier_cancel':events[0]['sim_time']-=1/30
    elif bad=='other_task':events[0]['logical_task_id']='other'
    elif bad=='other_body':events[0]['agent']='/B'
    elif bad=='epoch':events[0]['control_epoch']=4
    elif bad=='noncancel_error':events[0]['task_error_name']='BLOCKED'
    elif bad=='missing_end':events.pop(0)
    elif bad=='missing_return':events.pop()
    elif bad=='wrong_return':events[-1]['native_task_id']=99
    elif bad=='return_order':events[-1]['cursor']=13
    elif bad=='cursor_nan':events[0]['cursor']=float('nan')
    elif bad=='ambiguous_end':events.append(copy.deepcopy(events[0]))
    else:completed_boundary=(*completed_boundary[:6],lambda *args:{'aligned':args[-1]['sim_time']<1.6},events)
    with pytest.raises(ValueError):module.hold(*completed_boundary)


@pytest.mark.parametrize('bad',['overlay_missing','overlay_ended','overlay_other_task','overlay_duplicate','overlay_epoch',
                                'stale','body','logical_epoch','gap','duplicate','geometry','budget','duration','wrong_binding','static_xform'])
def test_false_hold_evidence_rejected(example,bad):
    task,event,start,binding,rows,overlays,measure_fn=example
    if bad=='overlay_missing':overlays.pop(8)
    elif bad=='overlay_ended':overlays[8]['owned']['native_task_id']['actual_status']='succeeded'
    elif bad=='overlay_other_task':overlays[8]['owned']['native_task_id']['native_task_id']=99
    elif bad=='overlay_duplicate':overlays.append(copy.deepcopy(overlays[8]))
    elif bad=='overlay_epoch':overlays[8]['control_epoch']=4
    elif bad=='stale':rows[8]['observation_sim_time']-=1/30
    elif bad=='body':rows[8]['traffic_body_instance_id']='other'
    elif bad=='logical_epoch':rows[8]['control_epoch']=4
    elif bad=='gap':rows.pop(8)
    elif bad=='duplicate':rows.insert(8,copy.deepcopy(rows[8]))
    elif bad=='geometry':example=(*example[:-1],lambda *args:{'aligned':False})
    elif bad=='budget':task['steps'][0]['timeout_s']=16
    elif bad=='duration':event['hold_sim_s']=1
    elif bad=='wrong_binding':binding['control_epoch']=9
    else:rows[8]['position_source']='UsdGeom.Xform'
    with pytest.raises(ValueError):module.hold(*example)


@pytest.fixture
def fences():
    before={'controller_id':'c','controller_epoch':1,'task_count':3,'actor_instance_id':'i','control_epoch':2,
            'task_id':'t','actual_native_action_task_id':5,'owned_gesture_ids':{'native_task_id':None}}
    return {'before':before,'after':copy.deepcopy(before)}


def test_stale_geometry_rejection_preserves_native_and_logical_owner(fences):
    module.reject_fences(fences)


@pytest.mark.parametrize('key',['controller_epoch','task_count','control_epoch','actor_instance_id','task_id','actual_native_action_task_id'])
def test_hidden_mutation_during_stale_rejection_is_not_accepted(fences,key):
    fences['after'][key]='changed'
    with pytest.raises(ValueError):module.reject_fences(fences)


def test_missing_run_remains_unverified(tmp_path):
    result=module.audit(tmp_path)
    assert not result['discovery_measurement_verified'] and result['strict_catalog_verified'] is False
