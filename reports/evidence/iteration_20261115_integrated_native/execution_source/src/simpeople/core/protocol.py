"""Strict validation before a request can acquire control of an actor."""
import math
import re
from .errors import SimPeopleError

TERMINAL = {'succeeded', 'failed', 'cancelled'}
ACTIONS = {'move_to','wait','look_at','sit','leave_seat','follow','custom_action','queue','head_look','reach_hand'}
STEP_FIELDS={'action','target','duration_s','timeout_s','gait','speed_mps','distance_m','tolerance_m','resource_id','via','interaction_revision','hand','max_angle_deg'}

def activity_contract():
    """Describe plan verbs separately from backend capability/gait labels."""
    return {'schema_version':'simpeople.task.v1','step_action_values':sorted(ACTIONS),
            'step_fields':sorted(STEP_FIELDS),
            'capability_to_step_fields':{'walk':{'action':'move_to','gait':'walk'},'run':{'action':'move_to','gait':'run'},
                **{a:{'action':a} for a in sorted(ACTIONS-{'move_to'})}},
            'target_required_for':sorted({'move_to','look_at','sit','follow','custom_action','queue','head_look','reach_hand'}),
            'duration_required_for':sorted({'wait','sit','follow','custom_action','queue','head_look','reach_hand'}),
            'hand_required_for':{'reach_hand':['left','right']},
            'precise_look_at':{'optional_field':'max_angle_deg','target_kind':'fixed_world_point','range_deg':[.1,2],'max_sim_seconds':8,'max_sdk_commands':16,'status':'experimental_requires_explicit_probe_runtime'},
            'note':'walk/run are capability and gait names, not activity action values. Add a real target and required duration/hand to the selected step fields, honor actor-specific verified capability/domain, then validate the complete plan.'}

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
        if action not in ACTIONS:
            hint=activity_contract()['capability_to_step_fields'].get(action)
            raise SimPeopleError('ACTION_UNSUPPORTED',f'Unknown action: {action}',allowed_step_actions=sorted(ACTIONS),step_fields_hint=hint)
        if set(s)-STEP_FIELDS: fail('unknown step fields: '+', '.join(sorted(set(s)-STEP_FIELDS)))
        if 'resource_id' in s:identifier(s['resource_id'],'resource_id')
        if 'interaction_revision' in s:
            if not isinstance(s['interaction_revision'],str) or not re.fullmatch(r'[0-9a-f]{64}',s['interaction_revision']):fail('interaction_revision must be a SHA256 hex digest')
            if action not in {'sit','queue','wait','custom_action','head_look','reach_hand'} or action in {'wait','custom_action','head_look','reach_hand'} and 'resource_id' not in s:fail('interaction_revision requires a seat, queue or explicit interaction resource')
        if 'via' in s and action!='move_to':fail('via is only valid for move_to')
        if 'max_angle_deg' in s:
            if action!='look_at':fail('max_angle_deg is only valid for look_at')
            if not isinstance(s.get('target'),list):fail('precise look_at requires a fixed world coordinate point')
            s['max_angle_deg']=number(s['max_angle_deg'],'max_angle_deg',.1,2)
            s.setdefault('timeout_s',8)
            if 'resource_id' in s:fail('precise look_at cannot acquire an interaction resource')
        if action in {'move_to','look_at','sit','follow','custom_action','queue','head_look','reach_hand'}: s['target']=target(s.get('target'))
        if action=='custom_action':s['target']=identifier(s['target'],'custom action name')
        if action in {'wait','sit','follow','custom_action','queue'}: s['duration_s']=number(s.get('duration_s'),'duration_s',0.01)
        if action in {'head_look','reach_hand'}:s['duration_s']=number(s.get('duration_s'),'duration_s',.01,5)
        if action=='reach_hand':
            if s.get('hand') not in {'left','right'}:fail('reach_hand requires hand left or right')
        elif 'hand' in s:fail('hand is only valid for reach_hand')
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
