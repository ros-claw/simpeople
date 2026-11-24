import socket
import threading
import pytest
from simpeople.core.errors import SimPeopleError
from simpeople.motion.providers.motionbricks import MotionBricksProvider


def test_disconnected_provider_and_nonfinite_input_are_explicit(tmp_path):
    provider=MotionBricksProvider(tmp_path/'missing.sock',timeout_s=.2)
    with pytest.raises(SimPeopleError) as error:provider.ping()
    assert error.value.code=='MOTION_WORKER_UNAVAILABLE'
    with pytest.raises(SimPeopleError) as error:provider.prepare({'bad':float('nan')})
    assert error.value.code=='MOTION_INVALID_REQUEST'


@pytest.mark.parametrize('wire',[b'[]\n',b'{"result":[]}\n',b'{"error":{}}\n',b'{"result":{"value":NaN}}\n',b'{"unexpected":1}\n'])
def test_malformed_ipc_response_cannot_escape_as_untyped_exception(tmp_path,wire):
    endpoint=tmp_path/'worker.sock'
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
        server.bind(str(endpoint));server.listen(1);server.settimeout(2)
        def reply():
            channel,_=server.accept()
            with channel:channel.recv(1000);channel.sendall(wire)
        thread=threading.Thread(target=reply);thread.start()
        try:
            with pytest.raises(SimPeopleError) as error:MotionBricksProvider(endpoint,timeout_s=.5).ping()
            assert error.value.code=='MOTION_WORKER_UNAVAILABLE'
        finally:thread.join(timeout=2)
