"""Strict validation before a request can acquire control of an actor."""
import math
import re
from .errors import SimPeopleError

TERMINAL = {'succeeded', 'failed', 'cancelled'}
ACTIONS = {'move_to','wait','look_at','sit','leave_seat','follow','custom_action','queue'}

def fail(message):
    raise SimPeopleError('INVALID_REQUEST', message)

def identifier(value, name):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):
        fail(name+' must contain 1–100 ASCII letters, digits, underscores or hyphens')
    return value

def number(value, name, low=0, high=86400):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
        fail(f'{name} must be a finite number in [{low}, {high}]')
    return float(value)

def target(value):
    if isinstance(value,str) and value: return value
    if isinstance(value,list) and len(value)==3:
        return [number(x,'coordinate',-100000,100000) for x in value]
    fail('target must be a semantic ID, prim path or [x,y,z] in metres')

def activity(params):
    identifier(params.get('actor_id'),'actor_id')
    steps=params.get('steps')
    if not isinstance(steps,list) or not 1<=len(steps)<=1000: fail('steps must contain 1–1000 items')
    if params.get('schema_version','simpeople.task.v1')!='simpeople.task.v1': fail('unsupported schema_version')
    if params.get('on_cancel','stop_activity')!='stop_activity': fail('on_cancel must be stop_activity')
    if params.get('on_blocked','report') not in {'report','replan_or_report'}: fail('unsupported on_blocked policy')
    clean=[]
    for raw in steps:
        if not isinstance(raw,dict): fail('each step must be an object')
        s=dict(raw); action=s.get('action')
        if action not in ACTIONS: raise SimPeopleError('ACTION_UNSUPPORTED',f'Unknown action: {action}')
        allowed={'action','target','duration_s','timeout_s','gait','speed_mps','distance_m','tolerance_m','resource_id','via'}
        if set(s)-allowed: fail('unknown step fields: '+', '.join(sorted(set(s)-allowed)))
        if 'resource_id' in s:identifier(s['resource_id'],'resource_id')
        if 'via' in s and action!='move_to':fail('via is only valid for move_to')
        if action in {'move_to','look_at','sit','follow','custom_action','queue'}: s['target']=target(s.get('target'))
        if action in {'wait','sit','follow','custom_action','queue'}: s['duration_s']=number(s.get('duration_s'),'duration_s',0.01)
        if 'timeout_s' in s: s['timeout_s']=number(s['timeout_s'],'timeout_s',0.1)
        if 'distance_m' in s:s['distance_m']=number(s['distance_m'],'distance_m',0.3,20)
        if action=='move_to':
            if 'via' in s:
                if not isinstance(s['via'],list) or not 1<=len(s['via'])<=64:fail('via must contain 1–64 waypoints')
                s['via']=[target(point) for point in s['via']]
            if s.get('gait','walk') not in {'walk','run'}: fail('gait must be walk or run')
            s['gait']=s.get('gait','walk')
            if 'speed_mps' in s: s['speed_mps']=number(s['speed_mps'],'speed_mps',0.1,5)
            if 'tolerance_m' in s: s['tolerance_m']=number(s['tolerance_m'],'tolerance_m',0.01,1)
        clean.append(s)
    return clean
