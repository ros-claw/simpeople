"""Optional asset-generation operation, independent of native actor ownership."""
import copy
import hashlib
import os
from simpeople.core.errors import SimPeopleError
from simpeople.motion.providers.motionbricks import MotionBricksProvider


def motion_operation(op,client_id,spec=None,job_id=None,expected_worker=None):
    endpoint=os.environ.get('SIMPEOPLE_MOTION_ENDPOINT')
    if not endpoint:raise SimPeopleError('ACTION_UNSUPPORTED','motion asset worker is disabled; native actions remain available')
    provider=MotionBricksProvider(endpoint)
    if op=='prepare':
        if not isinstance(spec,dict) or job_id is not None:raise SimPeopleError('MOTION_INVALID_REQUEST','prepare requires a MotionSpec and no job ID')
        data=copy.deepcopy(spec)
        if not isinstance(data.get('request_id'),str):raise SimPeopleError('MOTION_INVALID_REQUEST','prepare requires a request ID')
        data['request_id']='mcp-'+hashlib.sha256((client_id+':'+data['request_id']).encode()).hexdigest()
        worker=expected_worker or provider.ping()['worker_instance_id']
        return provider.prepare(data,worker)
    if op not in {'status','cancel'} or spec is not None or not isinstance(job_id,str) or not job_id or not isinstance(expected_worker,str) or not expected_worker:
        raise SimPeopleError('MOTION_INVALID_REQUEST','status/cancel require job ID and worker instance, without a spec')
    return getattr(provider,op)(job_id,expected_worker)
