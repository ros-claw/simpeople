"""Canonical preloaded entry comparison, independent of world XY placement."""
import math
from .rig import validate_poses, rotate, multiply


def entry_error(world_pose, facing_direction, reference):
    import numpy as np
    expected = validate_poses([reference['world_pose']], len(world_pose))[0]
    actual = validate_poses([world_pose], len(world_pose))[0]
    def body(values, facing):
        if len(facing) < 2 or not np.isfinite(facing).all() or abs(np.linalg.norm(facing[:2])-1) > .001:
            raise ValueError('finite unit-facing direction required')
        yaw = math.atan2(facing[0], -facing[1]);q = np.array([0, 0, math.sin(-yaw / 2), math.cos(-yaw / 2)])
        return rotate(q, values[:, :3] - values[0, :3]), multiply(q, values[:, 3:])
    wanted, wanted_q = body(expected, reference['facing_direction'])
    current, current_q = body(actual, facing_direction)
    p = float(np.linalg.norm(wanted - current, axis=-1).max())
    angle = float(np.degrees(2 * np.arccos(np.clip(np.abs(np.sum(wanted_q * current_q, axis=-1)), 0, 1))).max())
    height = float(abs(expected[0, 2] - actual[0, 2]))
    return {'max_joint_position_error_m': p, 'max_joint_angle_error_deg': angle, 'floor_reference_error_m': height,
            'passed': p <= .02 and angle <= 2 and height <= .02}


def heading_window_error(history, observation, domain):
    """An explicit, observed world-heading domain, never arbitrary-yaw acceptance."""
    import numpy as np
    fields={'world_facing_direction','max_angle_deg','stable_frames','sample_rate','base_action'}
    if not isinstance(domain,dict) or set(domain)!=fields:raise ValueError('explicit native heading domain required')
    desired=np.asarray(domain['world_facing_direction'],dtype=float)
    if desired.shape!=(3,) or not np.isfinite(desired).all() or abs(desired[2])>1e-6 or abs(np.linalg.norm(desired)-1)>.001:
        raise ValueError('finite planar unit heading domain required')
    count=domain['stable_frames'];fps=domain['sample_rate'];limit=domain['max_angle_deg']
    if (isinstance(count,bool) or not isinstance(count,int) or not 4<=count<=8 or fps!=30
        or isinstance(limit,bool) or not isinstance(limit,(int,float)) or not math.isfinite(limit) or not 0<limit<=.2
        or not isinstance(domain['base_action'],str) or not domain['base_action']):raise ValueError('invalid native heading domain bounds')
    chosen=history[-count:];errors=[];angles=[]
    if len(chosen)!=count:errors.append('actual stable heading samples absent')
    for r in chosen:
        facing=np.asarray(r.get('facing_direction'),dtype=float)
        speed=r.get('speed_mps');stamp=r.get('observation_sim_time')
        valid=(r.get('ready') is True and r.get('native_task_id')==observation.get('native_task_id')
               and r.get('action')==domain['base_action']
               and isinstance(speed,(int,float)) and not isinstance(speed,bool) and math.isfinite(speed) and 0<=speed<.15
               and isinstance(stamp,(int,float)) and not isinstance(stamp,bool) and math.isfinite(stamp)
               and facing.shape==(3,) and np.isfinite(facing).all() and abs(facing[2])<.001 and abs(np.linalg.norm(facing)-1)<.001)
        if not valid:errors.append('actual heading/base-task sample invalid');continue
        angle=math.degrees(math.acos(float(np.clip(np.dot(facing,desired),-1,1))));angles.append(angle)
        if angle>limit+1e-7:errors.append('outside supported world heading')
    if chosen and (any(chosen[-1].get(k)!=observation.get(k) for k in ['observation_sim_time','native_task_id','action','facing_direction','speed_mps','ready']) or any(abs(b['observation_sim_time']-a['observation_sim_time']-1/fps)>1e-7 for a,b in zip(chosen,chosen[1:]))):
        errors.append('heading window stale or not continuous actual 30Hz')
    return {'passed':not errors,'errors':errors,'actual_samples':len(chosen),'max_heading_error_deg':max(angles,default=None),
            'supported_world_facing_direction':domain['world_facing_direction'],'scope':'Explicit canonical entry only; no arbitrary native posture/heading or generated rig qualification.'}
