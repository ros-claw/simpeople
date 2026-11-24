"""Read-only seat cleanup diagnostics. No commands, leases or clocks are changed."""
import copy
import math


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def point(value):
    return isinstance(value,(list,tuple)) and len(value)==3 and all(finite(v) for v in value)


def seat_cleanup_state(backend,actor,observation,sim_time):
    """Describe the existing 15-s cleanup budget separately from task completion.

    A failed activity may still own physical seat cleanup. This function neither
    retries it nor releases occupancy. Missing SDK/route data stays unavailable.
    """
    if not actor.get('release_seat_when_standing'):return {'pending':False}
    result={'schema_version':'simpeople.seat-cleanup-state.v1','pending':True,'seat_id':actor.get('seat'),
            'actor_instance_id':actor.get('actor_instance_id'),'control_epoch':actor.get('control_epoch'),
            'snapshot_sim_time':sim_time if finite(sim_time) else None,
            'since_sim_time':actor.get('cleanup_started') if finite(actor.get('cleanup_started')) else None,'budget_s':15.,
            'deadline_scope':'seat_cleanup',
            'deadline_sim_time':None,'remaining_sim_s':None,'phase':'unavailable',
            'exit_target':copy.deepcopy(actor.get('cleanup_target')),'exit_position_m':None,'exit_distance_m':None,
            'route_goal_m':None,'route_goal_distance_m':None,
            'exit_backend_task_id':actor.get('cleanup_task'),'exit_task_status':None,'route_status':None,
            'body_native_task_id':observation.get('native_task_id') if type(observation.get('native_task_id')) is int else None,
            'traffic':None,'last_cleanup_error':copy.deepcopy(actor.get('cleanup_error')),'read_errors':[],
            'actual_observation_ready':False,'position_source':observation.get('position_source')}
    def unavailable(operation,message):
        result['read_errors'].append({'operation':operation,'message':message})
    if not finite(sim_time) or not finite(actor.get('cleanup_started')) or actor['cleanup_started']>sim_time+1e-7:
        unavailable('cleanup_clock','original simulation clock unavailable');return result
    result['deadline_sim_time']=actor['cleanup_started']+15
    result['remaining_sim_s']=max(0.,result['deadline_sim_time']-sim_time)
    result['retry_at_sim_time']=actor.get('cleanup_retry_at') if finite(actor.get('cleanup_retry_at')) else None
    fresh=(observation.get('ready') is True and point(observation.get('position_m'))
           and observation.get('position_source')=='BehaviorAgent.get_world_translation'
           and finite(observation.get('speed_mps')) and observation['speed_mps']>=0
           and finite(observation.get('observation_sim_time')) and abs(observation['observation_sim_time']-sim_time)<=1e-7)
    result['actual_observation_ready']=fresh
    result['position_source']=observation.get('position_source')
    if not fresh:
        result['phase']='observation_unavailable';return result
    handle=actor.get('handle')
    if not handle or not actor.get('seat'):
        unavailable('cleanup_owner','current seat owner/handle unavailable');return result
    tid=actor.get('cleanup_task');routes=getattr(backend,'routes',{})
    route=routes.get(tid) if isinstance(tid,(int,str)) and not isinstance(tid,bool) and isinstance(routes,dict) else None
    if route is not None and route.get('handle')!=handle:
        unavailable('exit_route_owner','cleanup route belongs to another Native actor');return result
    if tid:
        if not isinstance(tid,(int,str)) or isinstance(tid,bool):
            unavailable('exit_task','invalid cleanup backend task ID');return result
        try:result['exit_task_status']=backend.task_state(handle,tid)
        except Exception as error:
            unavailable('exit_task_status',str(error));return result
        if route is not None:
            result['route_status']=route.get('status')
            result['route_phase']=route.get('phase')
            result['movement_native_task_id']=route.get('native_task_id')
            goals=route.get('goals')
            if isinstance(goals,list) and goals and point(goals[-1]):
                result['route_goal_m']=list(goals[-1])
                result['route_goal_distance_m']=math.dist(observation['position_m'][:2],goals[-1][:2])
        reader=getattr(backend,'blocked_reason',None)
        if reader:
            try:result['traffic']=copy.deepcopy(reader(handle,tid))
            except Exception as error:unavailable('exit_blocked_details',str(error))
        status=result['exit_task_status']
        if status in {'failed','cancelled'}:result['phase']='exit_route_failed'
        elif result['traffic'] or result['route_status']=='blocked':result['phase']='exit_wait'
        elif status=='succeeded':result['phase']='settling_exit'
        elif status=='running':result['phase']='exit_route_pending' if route is not None and route.get('native_task_id') is None else 'exit_route_running'
        else:unavailable('exit_task_status','unsupported cleanup backend status')
    else:
        try:standing=bool(backend.is_standing(handle,observation))
        except Exception as error:
            unavailable('standing_readback',str(error));return result
        if not standing:result['phase']='standing_transition'
        elif observation['speed_mps']>=.15:result['phase']='settling_stand'
        elif result['retry_at_sim_time'] is not None and sim_time<result['retry_at_sim_time']:result['phase']='exit_retry_wait'
        elif actor.get('cleanup_error'):result['phase']='exit_selection_blocked'
        elif 'cleanup_target' not in actor:result['phase']='selecting_exit'
        elif actor['cleanup_target'] is None:result['phase']='releasing_seat'
        else:result['phase']='starting_exit'
    target=actor.get('cleanup_target')
    if target is not None:
        try:
            goal=backend.resolve_target(target)
            if not point(goal):raise ValueError('nonfinite exit goal')
            result['exit_position_m']=list(goal)
            result['exit_distance_m']=math.dist(observation['position_m'][:2],goal[:2])
        except Exception as error:unavailable('exit_target',str(error))
    return result
