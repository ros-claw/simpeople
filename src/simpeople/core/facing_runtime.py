"""One owned look_at step, bounded SDK feedback; no Kit imports or pose writes."""
import math
from .errors import SimPeopleError


def step(engine, task, actor, spec, observation):
    now=engine.sim_time
    state=task.setdefault('precise_facing',{'commands':0,'mode':'nominal','last_time':None,
        'last_angle':None,'stationary':0,'first_bound_time':None})
    deadline=min(task.get('step_deadline_sim_time',task['step_started']+8),task['step_started']+8)
    if now>deadline+1e-8:
        raise SimPeopleError('TIMEOUT','precise native facing exceeded 8 simulation seconds',commands=state['commands'])
    if state['last_time'] is not None and now<=state['last_time']+1e-9:return
    stamp=observation.get('observation_sim_time')
    if not isinstance(stamp,(int,float)) or isinstance(stamp,bool) or not math.isfinite(stamp) or abs(stamp-now)>1e-7:
        raise SimPeopleError('BACKEND_ERROR','precise facing requires a current simulation-time observation')
    if observation.get('native_task_id')!=task['native_task_id']:
        # start_native submits after the latest world read: only that same tick
        # can still contain the old native task. A later tick must bind it.
        if now-task.get('facing_command_sim_time',task['step_started'])>1/30+1e-7:
            raise SimPeopleError('BACKEND_TASK_FAILED','precise facing native binding was not observed')
        task['stable_since']=None;return
    position=observation['position_m'];facing=observation['facing_direction'];goal=engine.backend.resolve_target(spec['target'])
    if (len(position)!=3 or len(facing)!=3 or not all(math.isfinite(v) for v in [*position,*facing,*goal])
        or abs(math.hypot(*facing[:2])-1)>.001):
        raise SimPeopleError('BACKEND_ERROR','invalid actual facing observation')
    dx,dy=goal[0]-position[0],goal[1]-position[1]
    if math.hypot(dx,dy)<.05:raise SimPeopleError('TARGET_INVALID','precise facing requires a distinct horizontal target')
    angle=math.atan2(facing[0],facing[1]);desired=math.atan2(dx,dy)
    error=math.atan2(math.sin(desired-angle),math.cos(desired-angle));error_deg=math.degrees(error)
    speed=observation['speed_mps']
    if isinstance(speed,bool) or not isinstance(speed,(int,float)) or not math.isfinite(speed) or speed<0:
        raise SimPeopleError('BACKEND_ERROR','invalid actual speed observation')
    old_angle=state['last_angle'];delta=None if old_angle is None else abs(math.degrees(math.atan2(math.sin(angle-old_angle),math.cos(angle-old_angle))))
    state['stationary']=state['stationary']+1 if delta is not None and delta<.01 and speed<.15 else 0
    state.update(last_angle=angle,last_time=now)
    command=None
    if abs(error_deg)<=spec['max_angle_deg'] and state['mode']!='nominal':command=desired;state['mode']='nominal'
    elif abs(error_deg)>spec['max_angle_deg'] and state['stationary']>=3:
        command=desired+math.radians(5. if error_deg>0 else -5.2);state['mode']='bias'
    if command is not None:
        if state['commands']>=16:raise SimPeopleError('TIMEOUT','precise native facing exhausted 16 SDK commands')
        previous=task['native_task_id'];direction=[math.sin(command),math.cos(command),0.]
        internal={**spec,'_native_facing_direction':direction,'_expected_native_task_id':previous}
        native=engine.start_native(task,actor,internal);task.update(native_task_id=native,facing_command_sim_time=now,stable_since=None)
        state.update(commands=state['commands']+1,stationary=0)
        engine.event('precise_facing_command',task_id=task['task_id'],actor_id=task['actor_id'],
            previous_native_task_id=previous,native_task_id=native,command_number=state['commands'],
            actual_error_deg=error_deg,requested_direction=direction,deadline_sim_time=deadline)
        return
    ready=(state['mode']=='nominal' and abs(error_deg)<=spec['max_angle_deg']
           and speed<.15 and observation.get('action')=='Idle')
    if engine.settled(task,ready):
        engine.event('precise_facing_settled',task_id=task['task_id'],actor_id=task['actor_id'],
                     native_task_id=task['native_task_id'],actual_error_deg=error_deg,
                     command_count=state['commands'],actual_sim_time=now)
        engine.advance(task)
