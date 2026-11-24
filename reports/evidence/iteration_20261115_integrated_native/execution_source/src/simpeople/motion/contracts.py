"""Strict model-independent motion request and asynchronous result identities."""
import copy
import hashlib
import json
import math
import re
from simpeople.core.errors import SimPeopleError

SPEC_SCHEMA='simpeople.motion-spec.v1'


def fail(message,code='MOTION_INVALID_REQUEST'):
    raise SimPeopleError(code,message,stage='validation')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',value):fail('invalid motion request ID')
    return value


def poses(value,frames,joints):
    if not isinstance(value,list) or len(value) not in frames:fail('incorrect pose frame count')
    for pose in value:
        if not isinstance(pose,list) or len(pose)!=joints:fail('incorrect full joint count')
        for transform in pose:
            if not isinstance(transform,list) or len(transform)!=7 or any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) for x in transform):fail('poses must contain finite XYZ/XYZW transforms')
            if any(abs(x)>10000 for x in transform[:3]):fail('pose translation exceeds bounds')
            if abs(math.sqrt(sum(x*x for x in transform[3:]))-1)>.001:fail('pose quaternion is not unit length')


def validate_spec(raw,rig):
    if not isinstance(raw,dict):fail('motion spec must be an object')
    if set(raw)-{'schema_version','request_id','rig_sha256','context','target','binding'}:fail('unknown motion spec fields')
    if raw.get('schema_version')!=SPEC_SCHEMA:fail('unsupported motion spec schema')
    identifier(raw.get('request_id'))
    if raw.get('rig_sha256')!=rig['rig_sha256']:fail('rig revision mismatch','MOTION_RIG_MISMATCH')
    context=raw.get('context');target=raw.get('target')
    if not isinstance(context,dict) or set(context)!={'source','sample_times_s','local_poses'}:fail('context requires source, sample times and actual poses')
    if context['source'] not in {'authored_fixture','executed_history'}:fail('predicted context is not accepted as observed history')
    times=context['sample_times_s']
    if not isinstance(times,list) or len(times)!=4 or any(isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) for t in times):fail('four finite context times required')
    if any(abs((b-a)-1/30)>1e-6 for a,b in zip(times,times[1:])):fail('context must contain four consecutive 30 Hz samples')
    poses(context['local_poses'],{4},len(rig['joint_names']))
    if not isinstance(target,dict) or set(target)!={'local_poses'}:fail('target requires local poses only')
    poses(target['local_poses'],{1,2,3,4},len(rig['joint_names']))
    binding=raw.get('binding')
    if context['source']=='executed_history' and binding is None:fail('executed history requires an execution fence')
    if binding is not None:
        keys={'session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id','context_revision'}
        if not isinstance(binding,dict) or set(binding)!=keys:fail('complete motion execution fence required')
        for key in keys-{'control_epoch'}:
            if not isinstance(binding[key],str) or not binding[key]:fail('empty motion fence value')
        if isinstance(binding['control_epoch'],bool) or not isinstance(binding['control_epoch'],int) or binding['control_epoch']<0:fail('invalid actor control epoch')
        if binding['context_revision']!=digest(context):fail('context revision does not describe these actual samples')
    return copy.deepcopy(raw)


def binding_matches(expected,current):
    keys=('session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id','context_revision')
    return expected is not None and current is not None and all(k in expected and k in current and expected[k]==current[k] for k in keys)
