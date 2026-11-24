"""Retain a cancelled phased custom action until actual Native Idle is observed."""
import math


def ready(backend, handle, observation=None, require_window=False):
    instance=getattr(backend,'instances',{}).get(handle,{})
    record=instance.get('custom_stop')
    if record is None:return True
    backend.assert_thread()
    obs=observation if observation is not None else backend.observe(handle)
    agent=backend.api.get_agent(handle)
    idle=bool(agent and obs.get('ready') and obs.get('action')=='Idle'
              and obs.get('native_task_id')==agent.get_action_task_id()
              and obs.get('native_task_id')!=record['retired_native_task_id']
              and backend.task_state(handle,record['retired_native_task_id'])!='running'
              and isinstance(obs.get('speed_mps'),(int,float)) and not isinstance(obs.get('speed_mps'),bool)
              and math.isfinite(obs['speed_mps']) and 0<=obs['speed_mps']<.15)
    stamp=obs.get('observation_sim_time')
    samples=record.setdefault('actual_idle_times',[])
    if not idle or isinstance(stamp,bool) or not isinstance(stamp,(int,float)) or not math.isfinite(stamp):
        samples.clear();return False
    if samples and (stamp<samples[-1]-1e-9 or stamp-samples[-1]>.1+1e-7):samples.clear()
    if not samples or stamp>samples[-1]+1e-9:samples.append(stamp)
    # Bounded storage; 30Hz needs16 reads spanning0.5s. Higher-rate input keeps
    # its first time as well, and cannot establish a window with duplicate reads.
    if len(samples)>128:samples[1:2]=[]
    window=len(samples)>=16 and samples[-1]-samples[0]>=.5-1e-7
    if window and not record.get('settled_emitted'):
        record['settled_emitted']=True
        if backend.on_event:backend.on_event('native_custom_stop_settled',agent=handle,
            retired_native_task_id=record['retired_native_task_id'],actual_idle_native_task_id=obs['native_task_id'],
            actual_idle_samples=len(samples),first_actual_sim_time=samples[0],last_actual_sim_time=samples[-1])
    return window if require_window else idle
