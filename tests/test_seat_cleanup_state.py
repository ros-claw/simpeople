import copy
import json

import pytest

from simpeople.core.cleanup_state import seat_cleanup_state
from simpeople.core.engine import Engine
from test_engine import Backend,Journal


class ReadBackend(Backend):
    def __init__(self):
        super().__init__();self.reads=[]
        self.routes={'route1':{'handle':'/actor','status':'blocked','native_task_id':None}}
        self.traffic={'reason':'traffic_reservation','blocker_ids':['b'],'since_sim_time':190.067,'extra':{'rank':2}}
    def task_state(self,handle,tid):self.reads.append(('state',handle,tid));return 'running'
    def blocked_reason(self,handle,tid):self.reads.append(('blocked',handle,tid));return self.traffic
    def is_standing(self,handle,obs):return obs['action']=='Idle' and obs['joints_m']['Hips'][2]-obs['position_m'][2]>.75
    def resolve_target(self,target):return [8.8,-15.05,0]
    def stop(self,*args):raise AssertionError('read-only state must not stop an actor')
    def start(self,*args):raise AssertionError('read-only state must not start a task')
    def request_recovery(self,*args):raise AssertionError('read-only state must not retry')


@pytest.fixture
def example():
    backend=ReadBackend()
    actor={'handle':'/actor','actor_instance_id':'i','control_epoch':1,'seat':'seat03','release_seat_when_standing':True,
           'cleanup_started':187.9,'cleanup_task':'route1','cleanup_target':'exit03'}
    obs={'ready':True,'position_m':[7.48,-14.25,0],'joints_m':{'Hips':[7.48,-14.25,.928]},'speed_mps':.02,
         'action':'Idle','position_source':'BehaviorAgent.get_world_translation','observation_sim_time':200.}
    return backend,actor,obs,200.


def test_standing_actor_can_be_waiting_for_exit_not_standup(example):
    result=seat_cleanup_state(*example)
    assert result['phase']=='exit_wait' and result['actual_observation_ready']
    assert result['deadline_sim_time']==pytest.approx(202.9) and result['remaining_sim_s']==pytest.approx(2.9)
    assert result['route_status']=='blocked' and result['exit_task_status']=='running'
    assert result['traffic']['blocker_ids']==['b'] and result['movement_native_task_id'] is None
    assert result['exit_distance_m']>1


def test_reads_do_not_modify_actor_route_or_return_shared_metadata(example):
    backend,actor,obs,now=example;before=copy.deepcopy((actor,obs,backend.routes,backend.traffic))
    result=seat_cleanup_state(*example);result['traffic']['extra']['rank']=99
    assert (actor,obs,backend.routes,backend.traffic)==before
    assert backend.started==[]


def test_inactive_cleanup_reads_no_sdk_and_returns_no_pending_state(example):
    backend,actor,obs,now=example;actor['release_seat_when_standing']=False
    assert seat_cleanup_state(*example)=={'pending':False} and backend.reads==[]


def test_failed_activity_cleanup_continues_with_zero_budget_without_new_deadline(example):
    backend,actor,obs,_=example;obs['observation_sim_time']=205
    result=seat_cleanup_state(backend,actor,obs,205)
    assert result['pending'] and result['phase']=='exit_wait' and result['remaining_sim_s']==0
    assert result['deadline_sim_time']==pytest.approx(202.9) and actor['cleanup_started']==187.9


def test_pause_and_repeat_queries_keep_original_simulation_budget(example):
    before=seat_cleanup_state(*example);after=seat_cleanup_state(*example)
    assert before==after


@pytest.mark.parametrize('bad',['stale','unready','nonfinite_position','nonfinite_speed','static_xform'])
def test_stale_or_nonactual_pose_remains_unavailable(example,bad):
    backend,actor,obs,now=example
    if bad=='stale':obs['observation_sim_time']-=1/30
    elif bad=='unready':obs['ready']=False
    elif bad=='nonfinite_position':obs['position_m'][0]=float('nan')
    elif bad=='nonfinite_speed':obs['speed_mps']=float('nan')
    else:obs['position_source']='UsdGeom.Xform'
    result=seat_cleanup_state(*example)
    assert result['phase']=='observation_unavailable' and not result['actual_observation_ready']
    assert result['remaining_sim_s']==pytest.approx(2.9) and backend.reads==[]


@pytest.mark.parametrize('clock',['missing','future','nan'])
def test_missing_clock_does_not_invent_budget_or_modify_owner(example,clock):
    backend,actor,obs,now=example
    if clock=='missing':actor.pop('cleanup_started')
    elif clock=='future':actor['cleanup_started']=201
    else:actor['cleanup_started']=float('nan')
    result=seat_cleanup_state(*example)
    assert result['phase']=='unavailable' and result['deadline_sim_time'] is None and result['read_errors']
    json.dumps(result,allow_nan=False)


def test_other_body_route_is_not_queried_or_borrowed(example):
    backend,actor,obs,now=example;backend.routes['route1']['handle']='/another'
    result=seat_cleanup_state(*example)
    assert result['phase']=='unavailable' and result['read_errors'][0]['operation']=='exit_route_owner'
    assert backend.reads==[]


@pytest.mark.parametrize('state,phase',[('running','exit_route_running'),('succeeded','settling_exit'),('failed','exit_route_failed'),('cancelled','exit_route_failed')])
def test_exit_status_is_separate_from_standing_transition(example,state,phase):
    backend,actor,obs,now=example;backend.routes['route1']['status']=state;backend.traffic=None
    backend.routes['route1']['native_task_id']=17
    backend.task_state=lambda *_:state
    assert seat_cleanup_state(*example)['phase']==phase


def test_running_route_without_movement_submission_is_pending(example):
    backend,actor,obs,now=example;backend.routes['route1']['status']='running';backend.traffic=None
    result=seat_cleanup_state(*example)
    assert result['phase']=='exit_route_pending' and result['movement_native_task_id'] is None


def test_live_exit_marker_and_original_route_goal_are_not_conflated(example):
    backend,actor,obs,now=example;backend.routes['route1']['goals']=[[6,-12,0]]
    result=seat_cleanup_state(*example)
    assert result['route_goal_m']==[6,-12,0] and result['exit_position_m']==[8.8,-15.05,0]
    assert result['route_goal_distance_m']!=result['exit_distance_m']
    result['route_goal_m'][0]=999
    assert backend.routes['route1']['goals']==[[6,-12,0]]


@pytest.mark.parametrize('change,phase',[('sit','standing_transition'),('moving','settling_stand'),('no_target','selecting_exit'),
                                       ('target','starting_exit'),('clear','releasing_seat'),('retry','exit_retry_wait'),('error','exit_selection_blocked')])
def test_no_route_preserves_cleanup_phase_and_same_deadline(example,change,phase):
    backend,actor,obs,now=example;actor.pop('cleanup_task');actor.pop('cleanup_target')
    if change=='sit':obs['action']='Sit'
    elif change=='moving':obs['speed_mps']=.2
    elif change=='target':actor['cleanup_target']='exit'
    elif change=='clear':actor['cleanup_target']=None
    elif change=='retry':actor['cleanup_retry_at']=201
    elif change=='error':actor['cleanup_error']={'code':'RESOURCE_BUSY','message':'all exits occupied'}
    result=seat_cleanup_state(*example)
    assert result['phase']==phase and result['deadline_sim_time']==pytest.approx(202.9)


def test_unavailable_backend_read_preserves_crowd_query_and_error(example):
    backend,actor,obs,now=example
    def unavailable(*_):raise RuntimeError('SDK read unavailable')
    backend.task_state=unavailable;result=seat_cleanup_state(*example)
    assert result['phase']=='unavailable' and result['read_errors'][0]['operation']=='exit_task_status'
    assert result['remaining_sim_s']==pytest.approx(2.9)


def test_crowd_query_exposes_cleanup_without_rewriting_original_error_or_tasks(example):
    backend,actor,obs,now=example;engine=Engine(backend,Journal())
    engine.call('spawn',{'actor_id':'a','request_id':'s'})
    task=engine.call('run_activity',{'actor_id':'a','request_id':'t','steps':[{'action':'wait','duration_s':10}]})
    engine.sim_time=now;current=engine.actors['a'];current.update({k:v for k,v in actor.items() if k not in ['actor_instance_id','control_epoch']})
    engine.tasks[task['task_id']].update(status='failed',error={'code':'STOP_FAILED','message':'original preserved'})
    backend.observe=lambda _:copy.deepcopy(obs);before=copy.deepcopy((engine.actors,engine.tasks));result=engine.cmd_crowd_state({})
    row=result['actors'][0]
    assert row['status']=='failed' and row['error']['message']=='original preserved'
    assert row['seat_cleanup']['phase']=='exit_wait' and row['seat_cleanup']['actor_instance_id']==current['actor_instance_id']
    assert (engine.actors,engine.tasks)==before and backend.started==[]
