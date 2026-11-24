import pytest
from simpeople.core.engine import Engine
from simpeople.core.errors import SimPeopleError
from simpeople.core.protocol import activity
from test_engine import Backend,Journal


class GestureBackend(Backend):
    def __init__(self):
        super().__init__();self.aligned=True;self.returned=False;self.releases=[]
    def gesture_status(self,*args):return {'aligned':self.aligned,'hand_error_m':0 if self.aligned else .2}
    def end_gesture(self,h,tid):self.releases.append(tid)
    def gesture_stop_settled(self,*args):return self.returned


def setup():
    e=Engine(GestureBackend(),Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    return e


def submit(e):return e.call('run_activity',{'request_id':'reach','actor_id':'a','steps':[{'action':'reach_hand','hand':'right','target':[0,-.3,1.1],'duration_s':.6,'timeout_s':3}]})['task_id']


def test_native_success_does_not_replace_actual_alignment_and_hold():
    e=setup();e.backend.state='succeeded';e.backend.aligned=False;tid=submit(e)
    e.tick(0);e.tick(.5);e.tick(2)
    assert e.tasks[tid]['status']=='running' and not e.backend.releases
    e.tick(3.1)
    assert e.tasks[tid]['status']=='failed' and e.tasks[tid]['error']['code']=='TIMEOUT'


def test_real_hold_must_be_followed_by_native_release_and_return_settlement():
    e=setup();tid=submit(e);e.tick(0);e.tick(.3);e.tick(.9)
    assert e.backend.releases==[1] and e.tasks[tid]['status']=='running'
    e.backend.state='failed'  # Native cancellation is expected while releasing.
    e.tick(1);assert e.tasks[tid]['status']=='running'
    e.backend.returned=True;e.tick(1.1);e.tick(1.6)
    assert e.tasks[tid]['status']=='succeeded'
    assert e.tasks[tid]['gesture_verified_hold_sim_s']==pytest.approx(.6)


def test_loss_of_alignment_restarts_the_continuous_hold_without_extending_deadline():
    e=setup();tid=submit(e);e.tick(0);e.tick(.3);e.tick(.5)
    e.backend.aligned=False;e.tick(.6)
    e.backend.aligned=True;e.tick(.7);e.tick(1);e.tick(1.3)
    assert not e.backend.releases
    e.tick(1.6);assert e.backend.releases
    assert e.tasks[tid]['step_deadline_sim_time']==3


def test_cancel_cannot_claim_physical_stop_while_hand_is_still_extended():
    e=setup();tid=submit(e);e.tick(0)
    e.call('cancel',{'request_id':'cancel','task_id':tid});e.tick(.2);e.tick(.8)
    assert e.tasks[tid]['status']!='cancelled'
    e.backend.returned=True;e.tick(1);e.tick(1.5)
    assert e.tasks[tid]['status']=='cancelled' and e.tasks[tid]['physical_stop_verified']


@pytest.mark.parametrize('bad',[{'hand':'both'},{'hand':True},{'duration_s':6}])
def test_gesture_protocol_bounds(bad):
    spec={'action':'reach_hand','target':[0,-.3,1.1],'hand':'left','duration_s':1,**bad}
    with pytest.raises(SimPeopleError):activity({'actor_id':'a','steps':[spec]})


def test_hand_field_cannot_be_ignored_on_a_different_action():
    with pytest.raises(SimPeopleError):activity({'actor_id':'a','steps':[{'action':'wait','hand':'left','duration_s':1}]})


def test_native_return_task_keeps_original_actor_and_request_lineage():
    e=setup();tid=submit(e);e.tick(0)
    e.event('native_gesture_return_started',agent='/actor',original_native_task_id=1,native_task_id=8)
    e.event('native_task_ended',agent='/actor',task_id=8,task_status='failed')
    event=e.journal.events[-1]
    assert event['logical_task_id']==tid and event['request_id']=='reach' and event['correlation_status']=='unique'
