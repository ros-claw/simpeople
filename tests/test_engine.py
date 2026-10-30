"""Protocol/state invariants; no test here claims animation acceptance."""
import copy
import pytest
from simpeople.core.engine import Engine
from simpeople.core.errors import SimPeopleError
from simpeople.core.resources import Resources

class Journal:
    def __init__(self):self.events=[]
    def event(self,e):self.events.append(copy.deepcopy(e))

class Backend:
    def __init__(self):self.started=[];self.state='running';self.stops=0
    def spawn(self,*args):return '/actor'
    def despawn(self,*args):pass
    def validate(self,h,s):
        if s.get('target')=='bad':raise SimPeopleError('TARGET_INVALID','bad')
    def observe(self,h):return {'ready':True,'position_m':[0,0,0],'speed_mps':0,'facing_direction':[1,0,0]}
    def start(self,h,s):self.started.append(s['action']);return len(self.started)
    def stop(self,h):self.stops+=1
    def task_state(self,h,t):return self.state
    def resolve_target(self,t):return t if isinstance(t,list) else [0,0,0]
    def is_seated(self,*args):return True
    def is_standing(self,*args):return True

@pytest.fixture
def engine():
    e=Engine(Backend(),Journal())
    e.call('people.spawn',{'request_id':'spawn','actor_id':'a'})
    return e

def submit(e,rid='task',steps=None):
    return e.call('people.run_activity',{'request_id':rid,'actor_id':'a','steps':steps or [{'action':'wait','duration_s':1}]})['task_id']

def test_duplicate_request_does_not_repeat_spawn(engine):
    r=engine.call('spawn',{'request_id':'spawn','actor_id':'a'})
    assert r['idempotent_replay'] and len(engine.actors)==1

def test_request_id_collision_rejected(engine):
    with pytest.raises(SimPeopleError,match='different parameters'):
        engine.call('spawn',{'request_id':'spawn','actor_id':'b'})

def test_pause_does_not_consume_sim_time(engine):
    tid=submit(engine);engine.tick(0);engine.tick(.5)
    for _ in range(100):engine.tick(.5,paused=True)
    assert engine.tasks[tid]['status']=='paused'
    engine.tick(.9);assert engine.tasks[tid]['status']=='running'
    engine.tick(1.0);assert engine.tasks[tid]['status']=='succeeded'

def test_cancel_stops_successor_steps(engine):
    tid=submit(engine,steps=[{'action':'wait','duration_s':1},{'action':'move_to','target':[2,0,0]}])
    engine.tick(0);engine.call('cancel',{'request_id':'cancel','task_id':tid})
    engine.tick(.1);engine.tick(.7);engine.tick(10)
    assert engine.tasks[tid]['status']=='cancelled'
    assert engine.backend.started==['wait']

def test_invalid_replacement_keeps_old_task(engine):
    tid=submit(engine)
    with pytest.raises(SimPeopleError):submit(engine,'bad',steps=[{'action':'move_to','target':'bad'}])
    assert engine.actors['a']['task_id']==tid and engine.tasks[tid]['status']=='accepted'

def test_new_control_invalidates_old_activity(engine):
    old=submit(engine);engine.tick(0);new=submit(engine,'replacement')
    engine.tick(.1);engine.tick(2)
    assert engine.tasks[old]['status']=='cancelled' and engine.tasks[new]['status']=='succeeded'
    assert engine.tasks[new]['control_epoch']>engine.tasks[old]['control_epoch']

def test_backend_success_alone_is_not_arrival(engine):
    engine.backend.resolve_target=lambda _: [2,0,0]
    engine.backend.state='succeeded'
    tid=submit(engine,steps=[{'action':'move_to','target':[2,0,0]}])
    engine.tick(0);engine.tick(1)
    assert engine.tasks[tid]['status']=='running'

def test_failure_prevents_next_step(engine):
    tid=submit(engine,steps=[{'action':'move_to','target':[2,0,0]},{'action':'wait','duration_s':1}])
    engine.backend.state='failed';engine.tick(0);engine.tick(1)
    assert engine.tasks[tid]['status']=='failed' and engine.backend.started==['move_to']

def test_reset_new_episode_and_cleanup(engine):
    tid=submit(engine);episode=engine.episode_id
    engine.resources.acquire('seat','a')
    engine.call('reset',{'request_id':'reset','episode_id':episode})
    assert engine.tasks[tid]['status']=='cancelled'
    assert not engine.actors and not engine.resources.owners and engine.episode_id!=episode

def test_stale_episode_request_cannot_gain_control_after_reset(engine):
    old=engine.episode_id
    engine.call('reset',{'request_id':'new-episode'})
    engine.call('spawn',{'request_id':'new-actor','actor_id':'a'})
    with pytest.raises(SimPeopleError) as err:
        engine.call('move_to',{'request_id':'stale-move','actor_id':'a','episode_id':old,'target':[2,0,0]})
    assert err.value.code=='EPISODE_MISMATCH' and engine.actors['a']['task_id'] is None

def test_terminal_result_never_overwritten_by_cancel(engine):
    tid=submit(engine);engine.tick(0);engine.tick(1)
    engine.call('cancel',{'request_id':'late-cancel','task_id':tid})
    assert engine.tasks[tid]['status']=='succeeded'

@pytest.mark.parametrize('duration',[float('nan'),float('inf'),-1,True])
def test_invalid_numbers_never_gain_control(engine,duration):
    with pytest.raises((SimPeopleError,ValueError)):
        submit(engine,steps=[{'action':'wait','duration_s':duration}])
    assert engine.actors['a']['task_id'] is None

def test_fifo_resource_cancellation_and_fairness():
    r=Resources();assert r.acquire('seat','a')
    assert not r.acquire('seat','b');assert not r.acquire('seat','c')
    r.release('b');r.release('a');assert r.acquire('seat','c')

def test_seat_lease_persists_until_leave(engine):
    tid=submit(engine,steps=[{'action':'sit','target':'chair','duration_s':1},{'action':'wait','duration_s':1},{'action':'leave_seat'}])
    engine.tick(0);engine.tick(.5);engine.tick(1.5)
    assert engine.resources.owners=={'chair':'a'}
    engine.tick(1.6);engine.tick(2.7);engine.tick(2.8);engine.tick(3.4);engine.tick(4)
    assert engine.tasks[tid]['status']=='succeeded' and not engine.resources.owners

def test_paused_task_remains_queryable_when_native_handle_is_absent(engine):
    tid=submit(engine)
    engine.backend.observe=lambda _: {'ready':False,'position_m':None,'speed_mps':0}
    engine.tick(0,paused=True)
    assert engine.cmd_get_state({'task_id':tid})['status']=='paused'
    engine.tick(0,paused=True)
    assert engine.tasks[tid]['step_started'] is None

def test_seated_cancellation_holds_lease_until_physical_standup(engine):
    tid=submit(engine,steps=[{'action':'sit','target':'chair','duration_s':20}])
    engine.tick(0);engine.tick(.6)
    engine.backend.is_standing=lambda *_:False
    engine.call('cancel',{'request_id':'seat-cancel','task_id':tid})
    engine.tick(1);engine.tick(2)
    assert engine.tasks[tid]['status']!='cancelled' and engine.resources.owners=={'chair':'a'}
    engine.backend.is_standing=lambda *_:True
    engine.tick(2.1);engine.tick(2.7)
    assert engine.tasks[tid]['status']=='cancelled' and not engine.resources.owners

def test_queue_service_waits_for_front_actor_to_clear():
    class MultiBackend(Backend):
        def __init__(self):super().__init__();self.positions={};self.state='succeeded'
        def spawn(self,aid,asset,anchor):self.positions[aid]=[0,0,0];return aid
        def observe(self,h):return {'ready':True,'position_m':self.positions[h],'speed_mps':0,'facing_direction':[1,0,0]}
        def resolve_target(self,t):return t if isinstance(t,list) else [0,0,0]
        def queue_slots(self,q):return [[0,0,0],[-1.2,0,0]]
        def queue_egress(self,q,h):return [2,0,0]
    e=Engine(MultiBackend(),Journal())
    for aid in ['a','b']:e.call('spawn',{'request_id':'spawn-'+aid,'actor_id':aid})
    one=submit(e,steps=[{'action':'queue','target':'counter','duration_s':1}])
    two=e.call('run_activity',{'request_id':'queue-b','actor_id':'b','steps':[{'action':'queue','target':'counter','duration_s':1}]})['task_id']
    e.backend.positions['b']=[-1.2,0,0]
    e.tick(0);e.tick(.6);e.tick(1.7)
    assert e.tasks[one]['step_phase']=='queue_egress' and e.tasks[two]['step_phase']=='queue_waiting'
    e.tick(2.5)
    assert e.tasks[two]['queue_slot']==1  # service is still reserved while actor A leaves
    e.backend.positions['a']=[2,0,0];e.tick(2.6);e.tick(3.2)
    assert e.tasks[one]['status']=='succeeded' and e.tasks[two]['queue_slot']==0

def test_manual_cancellation_does_not_restart_population_program(engine):
    from simpeople.core.population import Population
    engine.population=Population(engine,42)
    engine.population.assignments['a']={'suspended':False}
    tid=engine.cmd_run_activity({'actor_id':'a','steps':[{'action':'wait','duration_s':10}]},source='scheduler')['task_id']
    engine.tick(0);engine.call('cancel',{'request_id':'stop-routine','task_id':tid})
    engine.tick(.1);engine.tick(.7);engine.tick(20)
    assert engine.tasks[tid]['status']=='cancelled' and engine.backend.started==['wait']

def test_long_wait_uses_its_declared_duration(engine):
    tid=submit(engine,steps=[{'action':'wait','duration_s':300}])
    engine.tick(0);engine.tick(299)
    assert engine.tasks[tid]['status']=='running'
    engine.tick(300)
    assert engine.tasks[tid]['status']=='succeeded'

def test_finite_follow_waits_for_stop_settlement(engine):
    tid=submit(engine,steps=[{'action':'follow','target':'leader','duration_s':2}])
    engine.tick(0);engine.tick(2)
    assert engine.tasks[tid]['status']=='running' and engine.backend.stops==1
    engine.tick(2.1);engine.tick(2.7)
    assert engine.tasks[tid]['status']=='succeeded'

def test_move_already_at_goal_uses_native_idle_and_stable_observation(engine):
    tid=submit(engine,steps=[{'action':'move_to','target':[0,0,0]}])
    engine.tick(0);engine.tick(.4)
    assert engine.backend.started==['settle'] and engine.tasks[tid]['status']=='running'
    engine.tick(.5)
    assert engine.tasks[tid]['status']=='succeeded'

def test_queue_temporary_native_failure_retries_but_has_a_deadline(engine):
    engine.backend.queue_slots=lambda _: [[2,0,0]]
    engine.backend.queue_egress=lambda *_: [4,0,0]
    engine.backend.state='failed'
    tid=submit(engine,steps=[{'action':'queue','target':'counter','duration_s':1,'timeout_s':10}])
    engine.tick(0)
    assert engine.tasks[tid]['status']=='blocked' and engine.backend.stops==1
    engine.tick(1)
    assert len(engine.backend.started)==1
    engine.tick(2)
    assert len(engine.backend.started)==2 and engine.tasks[tid]['status']=='blocked'
    engine.tick(11)
    assert engine.tasks[tid]['status']=='failed' and engine.tasks[tid]['error']['code']=='TIMEOUT'

def test_seat_cleanup_observes_egress_while_native_move_is_running(engine):
    actor=engine.actors['a'];actor.update(seat='chair',release_seat_when_standing=True)
    engine.backend.seat_egress=lambda *_: [2,0,0]
    engine.tick(0)
    assert actor.get('cleanup_task')
    # Native MoveTo is no longer an Idle action. It still needs monitoring.
    engine.backend.is_standing=lambda *_:False
    engine.backend.state='succeeded'
    engine.backend.observe=lambda _: {'ready':True,'position_m':[2,0,0],'speed_mps':0}
    engine.tick(1)
    assert actor['seat'] is None and not actor['release_seat_when_standing']

def test_event_priority_and_debounce_preserve_manual_override(engine):
    original=submit(engine,steps=[{'action':'wait','duration_s':20}]);engine.tick(0)
    low=engine.call('signal_event',{'request_id':'low','kind':'robot_nearby','actor_ids':['a']})
    high=engine.call('signal_event',{'request_id':'high','kind':'region_closed','actor_ids':['a'],'target':[0,0,0]})
    duplicate=engine.call('signal_event',{'request_id':'low-again','kind':'robot_nearby','actor_ids':['a']})
    assert duplicate['results'][0]['status']=='debounced'
    engine.tick(.1)
    assert engine.tasks[original]['status']=='cancelled'
    assert engine.events.active['a']['record']['event_id']==high['event_id']
    replacement=submit(engine,'manual',steps=[{'action':'wait','duration_s':1}])
    engine.tick(.2);engine.tick(2)
    assert engine.tasks[replacement]['status']=='succeeded' and not engine.events.active and not engine.events.pending
    assert engine.events.records[low['event_id']]['results'][0]['status']=='superseded'

def test_ordinary_event_waits_for_seat_boundary(engine):
    original=submit(engine,steps=[{'action':'sit','target':'chair','duration_s':1},{'action':'leave_seat'},{'action':'wait','duration_s':20}])
    engine.tick(0);engine.tick(.6)
    response=engine.call('signal_event',{'request_id':'seat-event','kind':'call_person','actor_ids':['a'],'target':[0,0,0]})
    engine.tick(.7)
    assert engine.events.records[response['event_id']]['results'][0]['status']=='deferred'
    assert engine.actors['a']['task_id']==original
    for t in [1.7,1.8,2,2.6,3.2]:engine.tick(t)
    assert engine.events.records[response['event_id']]['results'][0]['status']=='running'

def test_event_success_restores_interrupted_activity(engine):
    original=submit(engine,steps=[{'action':'wait','duration_s':20}]);engine.tick(0)
    event=engine.call('signal_event',{'request_id':'wait-event','kind':'robot_nearby','actor_ids':['a'],'duration_s':1})
    engine.tick(.1);engine.tick(.2);engine.tick(1.2)
    restored=engine.tasks[engine.actors['a']['task_id']]
    assert restored['source']=='event_restore' and restored['steps'][0]['duration_s']==pytest.approx(19.9)
    assert engine.events.records[event['event_id']]['results'][0]['status']=='succeeded'

def test_event_reports_a_missing_safe_boundary_in_finite_sim_time(engine):
    original=submit(engine,steps=[{'action':'wait','duration_s':300}]);engine.actors['a']['seat']='chair';engine.tick(0)
    event=engine.call('signal_event',{'request_id':'defer-expiry','kind':'call_person','actor_ids':['a'],'target':[0,0,0]})
    engine.tick(1);engine.tick(121)
    result=engine.events.records[event['event_id']]['results'][0]
    assert result['status']=='failed' and result['error']['code']=='SAFE_BOUNDARY_TIMEOUT'
    assert engine.actors['a']['task_id']==original

def test_replacement_discards_cancelled_seat_egress_handle(engine):
    actor=engine.actors['a'];actor.update(seat='chair',cleanup_task=99,cleanup_target=[2,0,0],cleanup_started=-20,release_seat_when_standing=True)
    submit(engine)
    assert 'cleanup_task' not in actor and 'cleanup_target' not in actor
    assert actor['cleanup_started']==engine.sim_time and actor['release_seat_when_standing']

def test_seat_hold_waits_for_completed_effector_entry(engine):
    engine.backend.seat_entry_ready=lambda *_:False
    tid=submit(engine,steps=[{'action':'sit','target':'chair','duration_s':1}])
    engine.tick(0);engine.tick(.6);engine.tick(1)
    assert engine.tasks[tid]['step_phase']!='holding' and 'hold_started' not in engine.tasks[tid]
    engine.backend.seat_entry_ready=lambda *_:True
    engine.tick(1.1);engine.tick(1.7)
    assert engine.tasks[tid]['step_phase']=='holding'
    assert engine.tasks[tid]['hold_started']>=1.7
    engine.tick(2.8);assert engine.tasks[tid]['status']=='succeeded'

def test_cancelled_distant_seat_approach_releases_without_returning_to_chair(engine):
    tid=submit(engine,steps=[{'action':'sit','target':'chair','duration_s':20}])
    engine.backend.is_seated=lambda *_:False
    engine.tick(0)
    engine.backend.can_release_seat_here=lambda *_:True
    engine.backend.seat_egress=lambda *_:pytest.fail('already outside the entire egress envelope')
    engine.call('cancel',{'request_id':'cancel-distant-approach','task_id':tid})
    engine.tick(.1);engine.tick(.7)
    assert engine.tasks[tid]['status']=='cancelled'
    assert engine.actors['a']['seat'] is None and not engine.resources.owners
    assert engine.backend.started==['sit']

def test_near_chair_cleanup_still_requires_native_egress(engine):
    actor=engine.actors['a'];actor.update(seat='chair',release_seat_when_standing=True)
    engine.backend.can_release_seat_here=lambda *_:False
    engine.backend.seat_egress=lambda *_:[2,0,0]
    engine.resources.acquire('chair','a')
    engine.tick(0);engine.tick(.7)
    assert actor['seat']=='chair' and engine.resources.owners=={'chair':'a'}
    assert engine.backend.started==['move_to']
