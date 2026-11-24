"""Finite measured hold and cancellation of one native gesture overlay."""
from .errors import SimPeopleError


def step(engine,task,actor,spec,obs):
    backend=engine.backend;handle=actor['handle']
    if task['step_phase']=='gesture_releasing':
        if engine.settled(task,backend.gesture_stop_settled(handle,obs)):
            engine.event('gesture_released',task_id=task['task_id'],actor_id=task['actor_id'],native_task_id=task['native_task_id'])
            engine.advance(task)
        return
    metrics=backend.gesture_status(handle,task['native_task_id'],spec,obs)
    task['gesture_evidence']=metrics
    if task['step_phase']=='executing':
        if engine.settled(task,metrics['aligned'],duration=.3):
            task['step_phase']='gesture_holding';task['gesture_hold_started']=engine.sim_time
            engine.event('gesture_aligned',task_id=task['task_id'],actor_id=task['actor_id'],metrics=metrics)
    elif task['step_phase']=='gesture_holding':
        if not metrics['aligned']:
            engine.event('gesture_alignment_lost',task_id=task['task_id'],actor_id=task['actor_id'],metrics=metrics)
            task['step_phase']='executing';task['stable_since']=None;task.pop('gesture_hold_started',None)
        elif engine.sim_time-task['gesture_hold_started']>=spec['duration_s']-1e-7:
            task['gesture_verified_hold_sim_s']=engine.sim_time-task['gesture_hold_started']
            backend.end_gesture(handle,task['native_task_id']);task['step_phase']='gesture_releasing';task['stable_since']=None
            engine.event('gesture_hold_completed',task_id=task['task_id'],actor_id=task['actor_id'],hold_sim_s=task['gesture_verified_hold_sim_s'],metrics=metrics)
