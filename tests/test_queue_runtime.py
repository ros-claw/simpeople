import copy
import pytest
from test_engine import Backend,Journal
from simpeople.core.engine import Engine
from simpeople.core.errors import SimPeopleError

class QueueBackend(Backend):
    def __init__(self):super().__init__();self.positions={};self.state='succeeded';self.egress_blocked=False
    def spawn(self,aid,asset,anchor):self.positions[aid]=anchor;return aid
    def observe(self,h):return {'ready':True,'position_m':self.positions[h],'speed_mps':0,'facing_direction':[1,0,0]}
    def queue_slots(self,q):return [[0,0,0],[-1.25,0,0]]
    def queue_egress(self,q,h):
        if self.egress_blocked:raise SimPeopleError('RESOURCE_BUSY','exit occupied')
        return [2,0,0]

def setup():
    e=Engine(QueueBackend(),Journal());tasks={}
    for i,aid in enumerate(['a','b','c']):
        e.call('spawn',{'request_id':'spawn_'+aid,'actor_id':aid,'spawn_anchor':[-1.25*i,0,0]})
        tasks[aid]=e.call('run_activity',{'request_id':'queue_'+aid,'actor_id':aid,'steps':[{'action':'queue','target':'q','duration_s':10,'timeout_s':30}]})['task_id']
    e.tick(0);e.tick(.6);return e,tasks

def test_front_cancel_keeps_slot_until_body_exits_and_settles():
    e,tasks=setup();e.call('cancel',{'request_id':'cancel','task_id':tasks['a']});e.tick(.7);e.tick(1.3)
    assert e.queues.members['q']==['a','b'] and e.tasks[tasks['a']]['status']!='cancelled'
    assert e.tasks[tasks['b']]['step_phase']!='serving'
    e.backend.positions['a']=[2,0,0];e.tick(1.4);e.tick(2);e.tick(2.6)
    assert e.tasks[tasks['a']]['status']=='cancelled' and e.tasks[tasks['a']]['physical_stop_verified']
    assert e.queues.members['q']==['b','c'] and not e.actors['a'].get('queue_cleanup')

def test_outside_cancel_is_removed_without_moving_or_ghost_ticket():
    e,tasks=setup();e.call('cancel',{'request_id':'cancel','task_id':tasks['c']});e.tick(.7);e.tick(1.3)
    t=e.tasks[tasks['c']];ticket=e.queues.ticket('q','c',t['queue_token'])
    assert t['status']=='cancelled' and ticket['cancelled']
    assert not e.actors['c'].get('queue_cleanup') and e.queues.members['q']==['a','b']

def test_superseded_queue_member_cannot_free_slot_or_start_new_step_early():
    e,tasks=setup();old=copy.deepcopy(e.tasks[tasks['a']])
    new=e.call('run_activity',{'request_id':'replace','actor_id':'a','steps':[{'action':'wait','duration_s':1}]})['task_id']
    e.tick(.7);assert e.tasks[new]['step_started'] is None and e.queues.members['q'][0]=='a'
    e.finish(old,'failed',{'code':'LATE'})
    assert e.queues.members['q'][0]=='a'
    e.backend.positions['a']=[2,0,0];e.tick(1);e.tick(1.6);e.tick(2.7)
    assert e.tasks[new]['status']=='succeeded' and e.queues.members['q'][0]=='b'

def test_exit_blockage_retains_occupancy_after_timeout_instead_of_ttl_release():
    e,tasks=setup();e.backend.egress_blocked=True;t=e.tasks[tasks['a']];t['steps'][0]['duration_s']=.1
    e.tick(1);assert t['blocked_details']['reason']=='no_free_egress'
    e.tick(31);e.tick(47)
    assert t['status']=='failed' and e.queues.members['q'][0]=='a'
    assert e.actors['a']['queue_cleanup']['error']['physical_occupancy_retained']

def test_resource_admission_consumes_original_step_budget():
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    e.resources.acquire('bench','owner')
    tid=e.call('run_activity',{'request_id':'wait','actor_id':'a','steps':[{'action':'wait','duration_s':8,'timeout_s':10,'resource_id':'bench'}]})['task_id']
    e.tick(0);e.tick(5);assert e.tasks[tid]['blocked_details']['blocker_ids']==['owner']
    e.resources.release('owner');e.tick(6);e.tick(11)
    assert e.tasks[tid]['status']=='failed' and e.tasks[tid]['error']['details']['deadline_sim_time']==10

def test_explicit_new_command_can_retry_failed_exit_without_reviving_old_task():
    e,tasks=setup();e.backend.egress_blocked=True;e.tick(31);e.tick(32);e.tick(48)
    assert e.actors['a']['queue_cleanup'].get('error')
    e.backend.egress_blocked=False
    newer=e.call('run_activity',{'request_id':'explicit_retry','actor_id':'a','steps':[{'action':'wait','duration_s':1}]})['task_id']
    e.tick(49);assert not e.actors['a']['queue_cleanup'].get('error')
    e.backend.positions['a']=[2,0,0];e.tick(49.1);e.tick(49.7);e.tick(50.8)
    assert e.tasks[newer]['status']=='succeeded' and e.tasks[tasks['a']]['status']=='failed'

def test_admission_full_remains_an_admission_error_in_task_results():
    from simpeople.core.population import Queues
    e=Engine(QueueBackend(),Journal());e.queues=Queues(max_outside=0,clock=lambda:e.sim_time,on_event=e.event)
    for aid in ['a','b']:
        e.call('spawn',{'request_id':'spawn_'+aid,'actor_id':aid,'spawn_anchor':[0,0,0]})
        e.call('run_activity',{'request_id':'queue_'+aid,'actor_id':aid,'steps':[{'action':'queue','target':'q','duration_s':20}]})
    e.queues.admission.configure('q',2)
    e.call('spawn',{'request_id':'spawn_c','actor_id':'c','spawn_anchor':[-4,0,0]})
    task=e.call('run_activity',{'request_id':'queue_c','actor_id':'c','steps':[{'action':'queue','target':'q','duration_s':20}]})['task_id']
    e.tick(0)
    assert e.tasks[task]['error']['code']=='ADMISSION_FULL' and e.tasks[task]['error']['stage']=='admission'

def test_same_activity_can_reacquire_one_resource_in_distinct_steps():
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    task=e.call('run_activity',{'request_id':'twice','actor_id':'a','steps':[{'action':'wait','duration_s':1,'resource_id':'bench'},{'action':'wait','duration_s':1,'resource_id':'bench'}]})['task_id']
    for now in [0,1,1.1,2.2]:e.tick(now)
    assert e.tasks[task]['status']=='succeeded'
    tickets=[t for t in e.resources.admission.tickets.values() if t['resource_id']=='bench']
    assert len(tickets)==2 and all(t['status']=='completed' for t in tickets)

def test_failed_queue_native_requests_share_the_two_attempt_recovery_budget():
    e=Engine(QueueBackend(),Journal());e.backend.state='failed'
    e.call('spawn',{'request_id':'spawn','actor_id':'a','spawn_anchor':[0,0,0]})
    task=e.call('run_activity',{'request_id':'queue','actor_id':'a','steps':[{'action':'queue','target':'q','duration_s':1,'timeout_s':30}]})['task_id']
    for now in [0,2,4]:e.tick(now)
    assert len(e.tasks[task]['recovery_attempts'])==2 and e.tasks[task]['status']=='failed'
    assert e.tasks[task]['error']['code']=='BACKEND_TASK_FAILED' and e.tasks[task]['step_deadline_sim_time']==30

def test_native_success_does_not_leave_a_displaced_queue_member_stuck_forever():
    e,tasks=setup();t=e.tasks[tasks['a']];e.backend.positions['a']=[0,.6,0]
    e.tick(1);assert t['blocked_details']['reason']=='slot_pose_lost'
    e.tick(1.6)
    assert len(t['recovery_attempts'])==1 and t['native_task_id'] is None
    assert t['recovery_attempts'][0]['reason']=='slot_pose_lost' and t['step_deadline_sim_time']==30

def test_completed_service_is_not_repeated_after_exit_wait_and_pose_reacquisition():
    e,tasks=setup();t=e.tasks[tasks['a']];t['steps'][0]['duration_s']=.1;e.backend.egress_blocked=True
    e.tick(1);ended=t['service_ended'];started=t['service_started']
    e.backend.positions['a']=[0,.6,0];e.tick(3);e.tick(3.6)
    assert len(t['recovery_attempts'])==1
    e.backend.positions['a']=[0,0,0];e.tick(5.7);e.backend.egress_blocked=False;e.tick(6.3)
    assert t['step_phase']=='queue_egress' and t['service_ended']==ended and t['service_started']==started
    events=[x for x in e.journal.events if x['kind']=='queue_service_started' and x.get('task_id')==t['task_id']]
    assert len(events)==1
