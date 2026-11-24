"""Owned Behavior overlay tasks, with actual-joint completion and native cancellation."""
import math
from pathlib import Path
import carb
import omni.anim.behavior.core as bh
from simpeople.core.errors import SimPeopleError
from simpeople.core.gestures import measure,return_ready,validate_target,head_forward,angle


def profile(backend,handle,action):
    asset=next(a for a in backend.assets if a['asset_id']==backend.instances[handle]['asset_id'])
    record=backend.gesture_catalog.query(asset.get('quality_revision_sha256'),asset.get('motion_revision_sha256'),asset['rig_id'],action,runtime_revision=backend.runtime_revision)
    if backend.up!='Z' or abs(backend.mpu-1)>1e-12:
        return {'status':'unverified','reason':'native gesture acceptance currently covers Z-up metre stages only'}
    if getattr(backend,'native_idle_profile',None) and record.get('startup_profiles'):
        import carb.settings
        from simpeople.core.gesture_profiles import implementation_revision,select_profile
        settings=carb.settings.get_settings();prefix='/exts/omni.anim.behavior.core/'
        effective={'idle_tags':settings.get(prefix+'idleAnimationTags'),
                   'response_time_s':settings.get(prefix+'agentResponseTime'),
                   'response_random_offset_s':settings.get(prefix+'agentResponseTimeMaxRandomOffset')}
        record=select_profile(record,backend.native_idle_profile,effective,
                              implementation_revision(Path(__file__).parents[2]),backend.allow_unverified)
    return record


def observe(backend,handle):
    before=backend.observe(handle)
    if not backend.instances[handle].get('gesture_sampling'):
        backend.instances[handle]['gesture_sampling']=True
        backend.observation_frame_ids[handle]=object()
        result=backend.observe(handle)
        # Resampling a single sim instant must not erase measured root speed.
        # Update the cached object as well: a second validation in the same
        # simulation frame must not turn a moving actor into a stationary one.
        result.update(speed_mps=before['speed_mps'],planar_speed_mps=before.get('planar_speed_mps',before['speed_mps']))
        if 'velocity_mps' in before:result['velocity_mps']=list(before['velocity_mps'])
        return result
    return before


def validate(backend,handle,step):
    backend.refresh_quality_revisions()
    record=profile(backend,handle,step['action'])
    if record.get('status')!='verified' and not (backend.allow_unverified and record.get('status')=='discovered'):
        raise SimPeopleError('ACTION_UNSUPPORTED','no exact-revision native gesture audit',capability=record)
    if step['duration_s']>record.get('max_hold_duration_s',0):raise SimPeopleError('ACTION_UNSUPPORTED','hold duration outside audited domain')
    experimental_base=getattr(backend,'experimental_gesture_base',None)
    if experimental_base:
        if not backend.allow_unverified or record.get('status')!='discovered':
            raise SimPeopleError('ACTION_UNSUPPORTED','alternate base stance is a run-local unverified experiment')
        if experimental_base not in getattr(backend,'custom_actions',{}) or experimental_base not in backend.agent(handle).get_custom_action_names():
            raise SimPeopleError('ACTION_UNSUPPORTED','experimental native base clip is not preloaded')
    obs=observe(backend,handle)
    if not backend.is_standing(handle,obs):raise SimPeopleError('ACTOR_BUSY','gesture requires standing posture')
    target=backend.resolve_target(step['target'])
    validate_target(step['action'],step.get('hand'),target,obs,record['domain'])
    if step['action']=='head_look' and not record.get('head_local_forward'):raise SimPeopleError('ACTION_UNSUPPORTED','head bind-axis audit missing')
    for other in backend.instances:
        if other==handle:continue
        body=backend.observe(other)
        if body.get('ready') and math.dist(body['position_m'][:2],target[:2])<.5:
            raise SimPeopleError('TARGET_BLOCKED','gesture target is inside another managed body proxy',actor_path=other)
    return record,obs,target


def start(backend,handle,step):
    record,base,target=validate(backend,handle,step)
    stop(backend,handle)
    agent=backend.agent(handle)
    previous=backend.instances[handle].get('gesture',{})
    if previous.get('return_task_id') is not None:agent.cancel_task(previous['return_task_id'])
    if previous.get('base_task_id') is not None:agent.cancel_task(previous['base_task_id'])
    # The base stance remains native-owned. A facing Idle prevents random Idle
    # direction changes from being mistaken for independent head tracking.
    base_clip=getattr(backend,'experimental_gesture_base',None);base_tid=None
    if base_clip:
        base_tid=agent.custom_action(base_clip,duration=0)
        if base_tid==bh.BEHAVIOR_TASK_ID_INVALID:raise SimPeopleError('BACKEND_TASK_FAILED','native experimental base rejected')
    else:agent.idle(facing=carb.Float3(*backend.to_stage(base['facing_direction'])))
    if step['action']=='head_look':tid=agent.look_at(tuple(backend.to_stage(target)),duration=0)
    else:tid=agent.reach_hand(bh.BehaviorHandUsage.LEFT_HAND if step['hand']=='left' else bh.BehaviorHandUsage.RIGHT_HAND,tuple(backend.to_stage(target)),duration=0)
    if tid==bh.BEHAVIOR_TASK_ID_INVALID:
        if base_tid is not None:agent.cancel_task(base_tid)
        raise SimPeopleError('BACKEND_TASK_FAILED','native gesture rejected')
    baseline={**base,'head_local_forward':record.get('head_local_forward')}
    backend.instances[handle]['gesture']={'native_task_id':tid,'action':step['action'],'hand':step.get('hand'),'target_m':target,'baseline':baseline,'releasing':False}
    if base_tid is not None:backend.instances[handle]['gesture'].update(base_task_id=base_tid,experimental_base_clip=base_clip)
    if backend.on_event:backend.on_event('native_gesture_started',agent=handle,native_task_id=tid,action=step['action'],hand=step.get('hand'),target_m=target,baseline=baseline,
        base_task_id=base_tid,experimental_base_clip=base_clip)
    return tid


def stop(backend,handle,tid=None):
    state=backend.instances[handle].get('gesture')
    if state is None or tid is not None and state['native_task_id']!=tid:return
    if not state['releasing']:
        agent=backend.api.get_agent(handle)
        if agent:agent.cancel_task(state['native_task_id'])
        state['releasing']=True
        state['release_started_sim_time']=backend.timeline.get_current_time()
        if agent and state['action']=='head_look':
            obs=backend.observe(handle);head=obs['joints_m']['Head'];f=obs['facing_direction']
            target=[head[i]+f[i] for i in range(3)]
            state['return_target_m']=target
            state['return_task_id']=agent.look_at(tuple(backend.to_stage(target)),duration=0)
            if state['return_task_id']==bh.BEHAVIOR_TASK_ID_INVALID:raise SimPeopleError('STOP_FAILED','native neutral head return rejected')
            if backend.on_event:backend.on_event('native_gesture_return_started',agent=handle,original_native_task_id=state['native_task_id'],native_task_id=state['return_task_id'],target_m=target)


def status(backend,handle,tid,step,obs):
    state=backend.instances[handle].get('gesture')
    if state is None or state['native_task_id']!=tid:raise SimPeopleError('BACKEND_TASK_FAILED','gesture owner changed')
    current=backend.resolve_target(step['target'])
    if math.dist(current,state['target_m'])>.001:raise SimPeopleError('TARGET_STALE','gesture target moved after native task started')
    return measure(state['action'],state['hand'],state['target_m'],state['baseline'],obs,backend.up)


def settled(backend,handle,obs):
    state=backend.instances[handle].get('gesture')
    if state is None:return True
    if state.get('cleanup_error'):raise SimPeopleError('STOP_FAILED',state['cleanup_error'])
    if not state['releasing']:return False
    if not obs.get('ready'):return False
    agent=backend.api.get_agent(handle)
    if agent and agent.get_task_status(state['native_task_id'])==bh.BehaviorTaskStatus.RUNNING:return False
    if state['action']=='head_look':
        if 'return_task_id' not in state and 'cancelled_return_task_id' not in state:
            raise SimPeopleError('STOP_FAILED','native gesture owner disappeared before neutral return')
        if state.get('return_task_id') is not None:
            head=obs['joints_m'].get('Head');forward=head_forward(state['baseline'],obs,backend.up)
            error=angle(forward,[state['return_target_m'][i]-head[i] for i in range(3)]) if head and forward else None
            if error is None or error>10 or obs['speed_mps']>=.15:
                state.pop('return_aligned_since',None);return False
            since=state.setdefault('return_aligned_since',backend.timeline.get_current_time())
            if backend.timeline.get_current_time()-since<.3:return False
            agent.cancel_task(state['return_task_id']);state['cancelled_return_task_id']=state.pop('return_task_id');return False
        if agent and agent.get_task_status(state['cancelled_return_task_id'])==bh.BehaviorTaskStatus.RUNNING:return False
        ready=obs['speed_mps']<.15
    else:ready=return_ready(state['action'],state['hand'],state['baseline'],obs,backend.up)
    if ready and state.get('base_task_id') is not None:
        base_tid=state.pop('base_task_id');owned=agent and agent.get_action_task_id()==base_tid
        if agent:agent.cancel_task(base_tid)
        if owned:agent.idle(facing=carb.Float3(*backend.to_stage(state['baseline']['facing_direction'])))
        state['cancelled_base_task_id']=base_tid
        return False
    if ready and agent and state.get('cancelled_base_task_id') is not None and agent.get_task_status(state['cancelled_base_task_id'])==bh.BehaviorTaskStatus.RUNNING:return False
    if ready:backend.instances[handle].pop('gesture',None)
    return ready


def tick(backend):
    # Failed tasks no longer enter Engine.step(). Their owned return task must
    # nevertheless be advanced and cancelled once the observed return settles.
    for handle,instance in list(backend.instances.items()):
        state=instance.get('gesture')
        if not state or not state['releasing'] or state.get('cleanup_error'):continue
        try:
            if settled(backend,handle,backend.observe(handle)):continue
            if backend.timeline.get_current_time()-state['release_started_sim_time']>5:
                raise SimPeopleError('STOP_FAILED','gesture return did not settle within five simulation seconds')
        except SimPeopleError as error:
            agent=backend.api.get_agent(handle)
            if agent and state.get('return_task_id') is not None:agent.cancel_task(state['return_task_id'])
            if agent and state.get('base_task_id') is not None:agent.cancel_task(state['base_task_id'])
            state['cleanup_error']=str(error)
            if backend.on_event:backend.on_event('native_gesture_cleanup_failed',agent=handle,original_native_task_id=state['native_task_id'],error=error.as_dict())
