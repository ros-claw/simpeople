"""Opt-in cleanup of a cancelled canonical task, on the existing Kit thread.

Only a recorded body-owned cancellation may use this helper. It never advances
the world, writes poses, adopts an unowned default Idle or extends the budget.
"""
import math


def request(backend, handle, entry, current, name, agent):
    """Opt in only for a known canonical Idle-entry task of this exact body."""
    backend.assert_thread()
    instance = backend.instances.get(handle, {})
    generation = instance.get('traffic_instance_id')
    if (not getattr(backend, 'deferred_custom_stop_probe_enabled', False)
            or not isinstance(entry.get('canonical_entry'), dict) or not entry['canonical_entry']
            or entry.get('entry_base_action') != 'Idle'
            or type(current) is not int or current <= 0
            or current not in instance.get('engine_native_ids', [])
            or not isinstance(generation, str) or not generation):
        return False
    if instance.get('custom_stop'):
        return True  # Never reset a cancellation clock or command on repetition.
    record = dict(retired_native_task_id=current, clip=name,
                  requested_sim_time=backend.timeline.get_current_time(),
                  actual_idle_times=[], idle_request_native_task_id=None,
                  deferred_native_cancel=True, body_generation=generation,
                  phase='native_cancel_requested')
    instance['custom_stop'] = record
    agent.cancel_task(current)
    if backend.on_event:
        backend.on_event('native_custom_stop_requested', agent=handle, **record)
    return True


def advance(backend, handle, record, observation, agent):
    backend.assert_thread()
    instance = backend.instances.get(handle, {})
    generation = record.get('body_generation')
    if not isinstance(generation, str) or not generation or instance.get('traffic_instance_id') != generation:
        return False
    now = backend.timeline.get_current_time(); stamp = observation.get('observation_sim_time')
    requested = record.get('requested_sim_time'); retired = record.get('retired_native_task_id')
    if (type(now) not in (int, float) or not math.isfinite(now)
            or type(stamp) not in (int, float) or not math.isfinite(stamp) or abs(stamp-now) > 1e-7
            or type(requested) not in (int, float) or not math.isfinite(requested)
            or not requested+1e-9 < stamp <= requested+15+1e-7
            or type(retired) is not int or retired <= 0 or observation.get('ready') is not True
            or agent is None):
        return False
    if record.get('idle_request_native_task_id') is not None:
        return True
    if record.get('idle_request_failed'):
        return False
    current = agent.get_action_task_id()
    if type(current) is not int or observation.get('native_task_id') != current:
        return False
    known_idle = (current in instance.get('engine_native_ids', [])
                  and agent.get_task_name(current) == 'Idle')
    if current not in (0, retired) and not known_idle:
        return False  # A later/foreign SDK owner must not be interrupted.
    speed = observation.get('speed_mps')
    quiet = type(speed) in (int, float) and math.isfinite(speed) and 0 <= speed < .15
    ended = backend.task_state(handle, retired) in {'succeeded', 'failed', 'cancelled'}
    natural = ended and observation.get('action') in ('Idle', '') and quiet
    forced = now-requested >= 14-1e-7
    if not natural and not forced:
        return False
    record['idle_request_attempted_sim_time'] = now
    record['forced_idle_request'] = not natural
    try:
        receipt = agent.idle()
        if type(receipt) is not int or receipt <= 0 or receipt == retired:
            raise ValueError('Native Idle did not return a distinct positive receipt')
    except Exception as error:
        record.update(idle_request_failed=True, phase='idle_request_failed',
                      idle_request_error={'type': type(error).__name__, 'message': str(error)})
        if backend.on_event:
            backend.on_event('native_custom_idle_request_failed', agent=handle,
                retired_native_task_id=retired, requested_sim_time=requested,
                error=record['idle_request_error'])
        return False  # A failed request is never retried indefinitely.
    record.update(idle_request_native_task_id=receipt, idle_requested_sim_time=now, phase='idle_requested')
    known = instance.setdefault('engine_native_ids', [])
    if receipt not in known:
        known.append(receipt)
    del known[:-32]
    if backend.on_event:
        backend.on_event('native_custom_idle_requested', agent=handle,
            retired_native_task_id=retired, idle_request_native_task_id=receipt,
            requested_sim_time=requested, idle_requested_sim_time=now,
            forced_idle_request=not natural, body_generation=generation)
    return False  # The issuing frame cannot establish an actual Idle sample.
