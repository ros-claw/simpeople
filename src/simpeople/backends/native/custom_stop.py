"""Retain a cancelled preloaded action until its owned Native Idle is observed.

This helper has no effect until a Native adapter explicitly records the stop.
"""
import math


def needs_settlement(entry):
    """Include canonical finite loops, which also need an actual Idle exit."""
    return bool(isinstance(entry,dict) and (
        entry.get('playback_mode')=='out_and_back'
        or isinstance(entry.get('canonical_entry'),dict) and entry['canonical_entry']))


def ready(backend, handle, observation=None, require_window=False):
    instance=getattr(backend,'instances',{}).get(handle,{})
    record=instance.get('custom_stop')
    if record is None:return True
    backend.assert_thread()
    obs=observation if observation is not None else backend.observe(handle)
    agent=backend.api.get_agent(handle)
    if record.get('cooperative_finite_stop'):
        from .cooperative_finite_stop import advance
        if not advance(backend,handle,record,obs,agent):
            record.setdefault('actual_idle_times',[]).clear();return False
    if record.get('deferred_native_cancel'):
        from .deferred_custom_stop import advance
        if not advance(backend,handle,record,obs,agent):
            record.setdefault('actual_idle_times',[]).clear();return False
    expected=record.get('idle_request_native_task_id')
    retired=record.get('retired_native_task_id')
    idle=bool(agent and obs.get('ready') and obs.get('action')=='Idle'
              and type(expected) is int and expected>0
              and type(retired) is int and retired>0 and expected!=retired
              and obs.get('native_task_id')==expected
              and obs.get('native_task_id')==agent.get_action_task_id()
              and backend.task_state(handle,expected)=='running'
              and backend.task_state(handle,retired)!='running'
              and isinstance(obs.get('speed_mps'),(int,float)) and not isinstance(obs.get('speed_mps'),bool)
              and math.isfinite(obs['speed_mps']) and 0<=obs['speed_mps']<.15)
    stamp=obs.get('observation_sim_time')
    samples=record.setdefault('actual_idle_times',[])
    requested=record.get('idle_requested_sim_time',record.get('requested_sim_time'))
    if (not idle or isinstance(stamp,bool) or not isinstance(stamp,(int,float)) or not math.isfinite(stamp)
        or type(requested) not in (int,float) or not math.isfinite(requested)
        or stamp<=requested+1e-9
        or abs(stamp-backend.timeline.get_current_time())>1e-7):
        samples.clear();return False
    if samples and (stamp<samples[-1]-1e-9 or stamp-samples[-1]>1/30+1e-7):samples.clear()
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
