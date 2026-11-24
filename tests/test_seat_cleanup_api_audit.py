import copy
import importlib.util
from pathlib import Path

import pytest


spec=importlib.util.spec_from_file_location('seat_api_audit',Path(__file__).parents[1]/'scripts/audit_seat_cleanup_api.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


@pytest.fixture
def example():
    stamp={'frame':0,'sim_time':1.,'frame_identity':{'source_tick':0,'video_frame':0}}
    before={'sim_time':1.,'session_id':'s','episode_id':'e','actors':{},'tasks':{},'resources':{'owners':{'chair_01':'operator'}}}
    actors=[]
    for aid in ['operator','witness']:
        task={'task_id':'t_'+aid,'actor_id':aid,'actor_instance_id':'i_'+aid,'control_epoch':1,'status':'running'}
        obs={'ready':True,'position_m':[0,0,0],'observation_sim_time':1.,'position_source':'BehaviorAgent.get_world_translation',
             'speed_mps':0.,'native_task_id':5,'action':'Idle'}
        actor={'actor_id':aid,'actor_instance_id':'i_'+aid,'task_id':'t_'+aid,'seat':'chair_01' if aid=='operator' else None,
               'observation':obs,'task':copy.deepcopy(task),'status':'running'}
        before['actors'][aid]={k:actor[k] for k in ['actor_instance_id','task_id','seat']};before['actors'][aid].update(control_epoch=1,native_task_id=5)
        before['tasks'][task['task_id']]=task;actors.append(actor)
    snapshot={'pending':True,'actor_instance_id':'i_operator','control_epoch':1,'seat_id':'chair_01','actual_observation_ready':True,
              'since_sim_time':0.,'budget_s':15,'deadline_sim_time':15.,'remaining_sim_s':14.,'exit_backend_task_id':'r',
              'exit_target':'exit','exit_position_m':[2,0,0],'exit_distance_m':2.,'route_status':'blocked','movement_native_task_id':None,
              'route_goal_m':[2,0,0],'phase':'exit_wait'}
    actors[0]['seat_cleanup']=snapshot
    record={'sim_time':1.,'frame_identity':stamp['frame_identity'],'before':before,'after':copy.deepcopy(before),
            'read_only_internal_unchanged':True,'crowd_state':{'session_id':'s','episode_id':'e','sim_time':1.,'actors':actors},
            'operator_cleanup_raw':{'release_seat_when_standing':True,'actor_instance_id':'i_operator','control_epoch':1,
                'seat':'chair_01','cleanup_started':0.,'cleanup_task':'r','cleanup_target':'exit','handle':'/A'},
            'exit_route_raw':{'handle':'/A','status':'blocked','native_task_id':None,'goals':[[2,0,0]]},
            'operator_observation':copy.deepcopy(actors[0]['observation'])}
    return record,stamp


def test_actual_read_only_state_matches_raw_route_and_budget(example):
    assert set(module.frame(*example))=={'operator','witness'}


@pytest.fixture
def independent_example(example):
    record,stamp=example;record['body_bindings']={};reads={}
    for a in record['crowd_state']['actors']:
        aid=a['actor_id'];a['observation']['joints_m']={'Hips':[0,0,1],'LeftFoot':[0,.1,.05]}
        record['body_bindings'][aid]={'native_actor_prim_path':'/'+aid,'traffic_body_instance_id':'b'+aid}
        reads[aid]={**record['body_bindings'][aid],'actor_instance_id':a['actor_instance_id'],
            'position_m':[0,0,0],'joints_m':copy.deepcopy(a['observation']['joints_m']),
            'sim_time':1.,'current_native_task_id':5,'current_native_task_elapsed_s':1.,'current_native_task_name':'Idle'}
    # Engine submitted command 9 after the current pose was read under command 5.
    reads['operator'].update(current_native_task_id=9,current_native_task_elapsed_s=0.,current_native_task_name='MoveAlong')
    record['before']['actors']['operator']['native_task_id']=9;record['after']=copy.deepcopy(record['before'])
    record['operator_observation']=copy.deepcopy(record['crowd_state']['actors'][0]['observation'])
    record['sdk_reads_before']=reads;record['sdk_reads_after']=copy.deepcopy(reads)
    return record,stamp


def test_same_frame_pose_is_not_relabelled_as_new_command_output(independent_example):
    record,stamp=independent_example
    actors=module.frame(record,stamp)
    assert actors['operator']['observation']['native_task_id']==5
    assert record['sdk_reads_before']['operator']['current_native_task_id']==9


@pytest.mark.parametrize('bad',['missing','changed','old_clock','other_body','other_instance','wrong_sdk',
    'root','joints','missing_joint','elapsed','nan_elapsed','missing_name'])
def test_independent_readback_never_excuses_stale_pose_or_old_sdk(independent_example,bad):
    record,stamp=independent_example;raw=record['sdk_reads_before']['operator']
    if bad=='missing':record.pop('sdk_reads_before')
    elif bad=='changed':record['sdk_reads_after']['operator']['position_m']=[1,0,0]
    elif bad=='old_clock':raw['sim_time']=0
    elif bad=='other_body':raw['traffic_body_instance_id']='other'
    elif bad=='other_instance':raw['actor_instance_id']='other'
    elif bad=='wrong_sdk':raw['current_native_task_id']=99
    elif bad=='root':raw['position_m']=[.1,0,0]
    elif bad=='joints':raw['joints_m']['Hips'][0]=.1
    elif bad=='missing_joint':raw['joints_m'].pop('LeftFoot')
    elif bad=='elapsed':raw['current_native_task_elapsed_s']=1/30
    elif bad=='nan_elapsed':raw['current_native_task_elapsed_s']=float('nan')
    else:raw['current_native_task_name']=''
    if bad not in {'missing','changed'}:record['sdk_reads_after']=copy.deepcopy(record['sdk_reads_before'])
    with pytest.raises(ValueError):module.frame(record,stamp)


@pytest.mark.parametrize('bad',['sdk_changed','lease_changed','clock_changed','epoch_changed','stale','static_xform',
                                'deadline_reset','remaining','route_owner','route_status','phase','goal','distance','false_task','missing_actor'])
def test_changed_or_fabricated_native_query_evidence_rejected(example,bad):
    record,stamp=example;actor=record['crowd_state']['actors'][0];snapshot=actor['seat_cleanup']
    if bad=='sdk_changed':record['after']['actors']['operator']['native_task_id']=99
    elif bad=='lease_changed':record['after']['resources']['owners'].clear()
    elif bad=='clock_changed':record['before']['sim_time']=2
    elif bad=='epoch_changed':actor['task']['control_epoch']=2
    elif bad=='stale':actor['observation']['observation_sim_time']=0
    elif bad=='static_xform':actor['observation']['position_source']='UsdGeom.Xform'
    elif bad=='deadline_reset':snapshot['deadline_sim_time']=16
    elif bad=='remaining':snapshot['remaining_sim_s']=15
    elif bad=='route_owner':record['exit_route_raw']['handle']='/other'
    elif bad=='route_status':snapshot['route_status']='running'
    elif bad=='phase':snapshot['phase']='exit_route_running'
    elif bad=='goal':snapshot['route_goal_m']=[3,0,0]
    elif bad=='distance':snapshot['exit_distance_m']=0
    elif bad=='false_task':actor['task']['status']='succeeded'
    else:record['crowd_state']['actors'].pop()
    with pytest.raises(ValueError):module.frame(*example)


def test_missing_native_run_is_not_verified(tmp_path):
    result=module.audit(tmp_path)
    assert not result['measurement_verified'] and not result['native_api_functional_verified']
    assert result['qualified_generated_native_rigs']==[]


def test_real_engine_crowd_state_contract_matches_independent_frame_reader():
    from test_engine import Backend, Journal
    from simpeople.core.engine import Engine
    backend=Backend();engine=Engine(backend,Journal())
    for aid in ['operator','witness']:
        engine.call('spawn',{'request_id':'spawn_'+aid,'actor_id':aid})
        engine.call('run_activity',{'request_id':'activity_'+aid,'actor_id':aid,'steps':[{'action':'wait','duration_s':5}]})
    original_observe=backend.observe
    backend.observe=lambda handle:{**original_observe(handle),'position_source':'BehaviorAgent.get_world_translation',
                                  'observation_sim_time':engine.sim_time,'native_task_id':5}
    state=engine.call('crowd_state',{'details':True})
    before={'sim_time':engine.sim_time,'session_id':engine.session_id,'episode_id':engine.episode_id,
            'tasks':{tid:engine.public(t) for tid,t in engine.tasks.items()},'actors':{
                aid:{**{k:a[k] for k in ['actor_instance_id','control_epoch','task_id','seat']},'native_task_id':5}
                for aid,a in engine.actors.items()}}
    identity={'source_tick':0,'video_frame':0};stamp={'sim_time':engine.sim_time,'frame_identity':identity}
    record={'sim_time':engine.sim_time,'frame_identity':identity,'before':before,'after':copy.deepcopy(before),
            'read_only_internal_unchanged':True,'crowd_state':state,'operator_cleanup_raw':{'release_seat_when_standing':False},
            'operator_observation':next(a['observation'] for a in state['actors'] if a['actor_id']=='operator')}
    assert all('control_epoch' not in a for a in state['actors'])
    assert set(module.frame(record,stamp))=={'operator','witness'}
