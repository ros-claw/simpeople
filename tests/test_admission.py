"""FIFO applies to callers outside the physical queue as well as inside."""
import pytest
from simpeople.core.admission import Admission
from simpeople.core.errors import SimPeopleError
from simpeople.core.population import Queues

def token(actor,generation=0):return (actor,actor+'-instance',generation,'task-'+actor+'-'+str(generation))

def request(pool,actor,now=0):return pool.request_admission('desk',token(actor),now,actor_id=actor,capacity=1)

def test_bounded_tickets_and_first_request_time_survive_polling():
    p=Admission(max_outside=2);a=request(p,'a');b=request(p,'b',1);c=request(p,'c',2);d=request(p,'d',3)
    assert [a['status'],b['status'],c['status'],d['status']]==['admitted','waiting','waiting','rejected']
    assert request(p,'b',20)['requested_sim_time']==1 and request(p,'d',30)['status']=='rejected'
    assert len(p.snapshot()['desk']['tickets'])==3

def test_new_arrival_cannot_bypass_old_caller_that_has_not_polled_again():
    p=Admission();request(p,'a');request(p,'b',1)
    p.release(token('a'),2,physical_clear=True)
    assert request(p,'new',2)['status']=='waiting'
    assert request(p,'b',3)['status']=='admitted'

def test_cancelling_outside_and_head_preserves_fifo_and_physical_occupancy():
    p=Admission();request(p,'a');request(p,'b',1);request(p,'c',2)
    p.release(token('b'),3,reason='cancelled')
    with pytest.raises(SimPeopleError):p.release(token('a'),4,reason='cancelled')
    assert request(p,'c',5)['status']=='waiting'
    p.release(token('a'),6,physical_clear=True,reason='cancelled')
    assert request(p,'c',7)['status']=='admitted'

def test_old_instance_cannot_release_new_ticket():
    p=Admission();request(p,'a');p.release(token('a'),1,physical_clear=True)
    new=(*token('a',1)[:1],'recreated',1,'new-task');p.request_admission('desk',new,2,actor_id='a')
    p.release(token('a'),3,physical_clear=True)
    assert p.find('desk',new)['status']=='admitted'

def test_physical_queue_remembers_outside_arrival_order():
    q=Queues(max_outside=2);q.join('q','a',1,token=token('a'),now=0)
    with pytest.raises(SimPeopleError):q.join('q','b',1,token=token('b'),now=1)
    q.remove('a',token=token('a'),now=2)
    with pytest.raises(SimPeopleError):q.join('q','new',1,token=token('new'),now=2)
    assert q.join('q','b',1,token=token('b'),now=3)==0

def test_legacy_unscoped_callers_can_reenter_after_release():
    from simpeople.core.resources import Resources
    r=Resources();assert r.acquire('r','a');r.release('a');assert r.acquire('r','a')
    q=Queues();assert q.join('q','a',1)==0;q.remove('a');assert q.join('q','a',1)==0
