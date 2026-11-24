import pytest
from simpeople.core.errors import SimPeopleError
from simpeople.tools.motion import motion_operation


def test_disabled_generation_is_separate_from_native_bridge(monkeypatch):
    monkeypatch.delenv('SIMPEOPLE_MOTION_ENDPOINT',raising=False)
    with pytest.raises(SimPeopleError) as error:motion_operation('prepare','client',spec={'request_id':'one'})
    assert error.value.code=='ACTION_UNSUPPORTED'


def test_generation_ids_are_isolated_and_poll_requires_worker_fence(monkeypatch):
    monkeypatch.setenv('SIMPEOPLE_MOTION_ENDPOINT','/unused.sock')
    class Provider:
        def __init__(self,*_):pass
        def ping(self):return {'worker_instance_id':'instance'}
        def prepare(self,spec,worker):return {'request_id':spec['request_id'],'worker':worker}
    monkeypatch.setattr('simpeople.tools.motion.MotionBricksProvider',Provider)
    data={'request_id':'same'}
    first=motion_operation('prepare','one',spec=data);again=motion_operation('prepare','one',spec=data);other=motion_operation('prepare','two',spec=data)
    assert first==again and first!=other and data['request_id']=='same'
    with pytest.raises(SimPeopleError):motion_operation('status','one',job_id='job')
    with pytest.raises(SimPeopleError):motion_operation('execute','one',job_id='job',expected_worker='instance')
