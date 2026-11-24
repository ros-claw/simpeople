"""Loopback Unix socket provider. All pose execution remains outside this client."""
import json
import socket
from simpeople.core.errors import SimPeopleError


class MotionBricksProvider:
    def __init__(self,endpoint,timeout_s=10):self.endpoint=str(endpoint);self.timeout_s=timeout_s
    def request(self,op,**params):
        try:data=json.dumps({'op':op,**params},allow_nan=False).encode()+b'\n'
        except (ValueError,TypeError) as error:raise SimPeopleError('MOTION_INVALID_REQUEST','motion IPC requires finite JSON data') from error
        if len(data)>2_000_000:raise SimPeopleError('MOTION_REQUEST_TOO_LARGE','motion IPC envelope exceeds limit')
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as channel:
                channel.settimeout(self.timeout_s);channel.connect(self.endpoint);channel.sendall(data)
                with channel.makefile('rb') as stream:line=stream.readline(2_000_001)
            if not line or len(line)>2_000_000:raise ValueError('invalid worker response size')
            response=json.loads(line,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite worker JSON')))
            if not isinstance(response,dict) or set(response) not in ({'result'},{'error'}):raise ValueError('invalid worker response envelope')
            if 'result' in response and not isinstance(response['result'],dict):raise ValueError('invalid worker result')
            if 'error' in response and (not isinstance(response['error'],dict) or any(not isinstance(response['error'].get(k),str) for k in ('code','message'))):raise ValueError('invalid worker error')
        except (OSError,ValueError) as error:raise SimPeopleError('MOTION_WORKER_UNAVAILABLE',str(error),stage='transport') from error
        if 'error' in response:
            e=response['error'];raise SimPeopleError(e['code'],e['message'],stage=e.get('stage','generation'))
        return response['result']
    def prepare(self,spec,expected_worker=None):return self.request('prepare',spec=spec,expected_worker=expected_worker)
    def status(self,job_id,expected_worker):return self.request('status',job_id=job_id,expected_worker=expected_worker)
    def cancel(self,job_id,expected_worker):return self.request('cancel',job_id=job_id,expected_worker=expected_worker)
    def ping(self):return self.request('ping')
