"""Measured native gesture geometry. These are joint proxies, not contact forces."""
import math
from .errors import SimPeopleError

GESTURES={'head_look','reach_hand'}


def unit(v):
    n=math.sqrt(sum(x*x for x in v))
    return [x/n for x in v] if n>1e-9 else None


def angle(a,b):
    a=unit(a);b=unit(b)
    return math.degrees(math.acos(max(-1,min(1,sum(x*y for x,y in zip(a,b)))))) if a and b else None


def rotate(q,v,inverse=False):
    x,y,z,w=q
    if inverse:x,y,z=-x,-y,-z
    n=math.sqrt(x*x+y*y+z*z+w*w);x,y,z,w=[a/n for a in [x,y,z,w]]
    u=[x,y,z];cross=lambda a,b:[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    uv=cross(u,v);uuv=cross(u,uv)
    return [v[i]+2*(w*uv[i]+uuv[i]) for i in range(3)]


def stage_vector(v,up):return list(v) if up=='Z' else [v[0],v[2],-v[1]]
def public_vector(v,up):return list(v) if up=='Z' else [v[0],-v[2],v[1]]


def head_forward(baseline,obs,up='Z'):
    q0=baseline.get('joint_rotations_xyzw_stage',{}).get('Head');q=obs.get('joint_rotations_xyzw_stage',{}).get('Head')
    if q0 is None or q is None:return None
    local=baseline.get('head_local_forward') or rotate(q0,stage_vector(baseline['facing_direction'],up),inverse=True)
    return public_vector(rotate(q,local),up)


def measure(action,hand,target,baseline,obs,up='Z'):
    joints=obs.get('joints_m',{});old=baseline.get('joints_m',{})
    root=math.dist(baseline['position_m'],obs['position_m'])
    yaw=angle(baseline['facing_direction'][:2],obs['facing_direction'][:2])
    ratios={}
    for side in ['Left','Right']:
        for a,b in [('Arm','ForeArm'),('ForeArm','Hand'),('Leg','Foot')]:
            a,b=side+a,side+b
            if all(k in j for j in [joints,old] for k in [a,b]):
                length=math.dist(old[a],old[b])
                if length>1e-5:ratios[a+'-'+b]=math.dist(joints[a],joints[b])/length
    result={'root_displacement_m':root,'root_facing_change_deg':yaw,'bone_length_ratios':ratios,
        'bone_length_max_deviation':max((abs(r-1) for r in ratios.values()),default=None)}
    # Leg->Foot can span intervening ankle/twist joints. Keep those raw ratios,
    # but certify the active arm's two directly connected segments separately.
    active=[v for k,v in ratios.items() if hand and k.startswith(hand.title()) and ('Arm-' in k)]
    result['active_arm_length_max_deviation']=max((abs(r-1) for r in active),default=0 if action=='head_look' else None)
    if action=='head_look':
        forward=head_forward(baseline,obs,up);head=joints.get('Head')
        result['head_angle_error_deg']=angle(forward,[target[i]-head[i] for i in range(3)]) if forward and head else None
        reached=result['head_angle_error_deg'] is not None and result['head_angle_error_deg']<=12
    else:
        tag=hand.title()+'Hand';result['hand_joint']=tag
        result['hand_error_m']=math.dist(joints[tag],target) if tag in joints else None
        reached=result['hand_error_m'] is not None and result['hand_error_m']<=.05
    result['aligned']=bool(reached and root<=.05 and yaw is not None and yaw<=5 and
        result['active_arm_length_max_deviation'] is not None and result['active_arm_length_max_deviation']<=.02 and obs['speed_mps']<.15)
    return result


def return_ready(action,hand,baseline,obs,up='Z'):
    if not obs.get('ready') or obs['speed_mps']>=.15:return False
    if action=='head_look':
        forward=head_forward(baseline,obs,up)
        neutral=head_forward(baseline,baseline,up)
        value=angle(forward,neutral) if forward and neutral else None
        return value is not None and value<=10
    tag=hand.title()+'Hand';shoulder=hand.title()+'Arm'
    old=baseline.get('joints_m',{});now=obs.get('joints_m',{})
    if any(k not in j for j in [old,now] for k in [tag,shoulder]):return False
    # Native Idle can shift the root/shoulder. Measure return relative to the
    # shoulder rather than comparing two world positions across that shift.
    return math.dist([now[tag][i]-now[shoulder][i] for i in range(3)],[old[tag][i]-old[shoulder][i] for i in range(3)])<=.12


def validate_target(action,hand,target,obs,domain):
    if not obs.get('ready'):raise SimPeopleError('SIM_NOT_READY','gesture requires actual native pose')
    if obs['speed_mps']>=.15:raise SimPeopleError('ACTOR_BUSY','gesture requires a settled standing actor')
    if action=='head_look':
        head=obs.get('joints_m',{}).get('Head')
        if head is None:raise SimPeopleError('ACTION_UNSUPPORTED','actual Head joint unavailable')
        delta=[target[i]-head[i] for i in range(3)];horizontal=math.hypot(*delta[:2])
        yaw=angle(delta[:2],obs['facing_direction'][:2]);pitch=math.degrees(math.atan2(delta[2],horizontal))
        if not domain['min_distance_m']<=math.sqrt(sum(x*x for x in delta))<=domain['max_distance_m'] or yaw is None or yaw>domain['max_yaw_deg'] or abs(pitch)>domain['max_pitch_deg']:
            raise SimPeopleError('TARGET_UNREACHABLE','target outside audited head-look domain',yaw_deg=yaw,pitch_deg=pitch,domain=domain)
    else:
        joints=obs.get('joints_m',{});side=hand.title();shoulder=joints.get(side+'Arm');elbow=joints.get(side+'ForeArm');wrist=joints.get(side+'Hand')
        if any(p is None for p in [shoulder,elbow,wrist]):raise SimPeopleError('ACTION_UNSUPPORTED','actual arm joints unavailable',hand=hand)
        length=math.dist(shoulder,elbow)+math.dist(elbow,wrist);distance=math.dist(shoulder,target)
        root=obs['position_m'];delta=[target[i]-root[i] for i in range(3)]
        forward=sum(delta[i]*obs['facing_direction'][i] for i in range(2));height=delta[2]
        if not domain['min_height_m']<=height<=domain['max_height_m'] or not domain['min_forward_m']<=forward<=domain['max_forward_m'] or distance>length*domain['max_arm_fraction']:
            raise SimPeopleError('TARGET_UNREACHABLE','target outside audited hand-reach domain',shoulder_distance_m=distance,arm_length_m=length,domain=domain)
