"""Retain a cancelled local-yield body's claim until observed stop, on Kit thread."""
import copy
import math


def retain(backend, handle, rid):
    backend.assert_thread()
    if handle in backend.local_yield_stops:
        return True  # Repeated stop must not free a body that is still braking.
    job = backend.routes.get(rid, {})
    data = job.get('local_yield')
    if not data:
        return False
    body = backend.instances.get(handle, {}).get('traffic_instance_id')
    cells = backend.grid.claims.get(handle)
    if body != data['body_generation'] or not cells:
        # Stale work never releases a different incarnation's claim.
        return body != data['body_generation']
    backend.local_yield_stops[handle] = {
        'route_id': rid, 'body_generation': body, 'cells': copy.deepcopy(cells),
        'started_sim_time': backend.now, 'stable_since': None, 'stable_samples': 0,
        'last_sample_time': None, 'last_position_m': None}
    backend.emit('traffic_cancelled_yield_claim_retained', route_id=rid, agent=handle,
                 body_instance_id=body, cells=sorted(cells))
    return True


def advance_stops(backend, observations):
    backend.assert_thread()
    for handle, stop in list(backend.local_yield_stops.items()):
        body = backend.instances.get(handle, {}).get('traffic_instance_id')
        if body != stop['body_generation'] or backend.grid.claims.get(handle) != stop['cells']:
            # Drop stale bookkeeping, never touch a subsequent owner's cells.
            backend.local_yield_stops.pop(handle)
            backend.emit('traffic_cancelled_yield_settlement_stale', route_id=stop['route_id'],
                         agent=handle, body_instance_id=stop['body_generation'])
            continue
        obs = observations.get(handle, {})
        p = obs.get('position_m'); speed = obs.get('speed_mps')
        valid = (obs.get('ready') is True and obs.get('action') == 'Idle'
                 and obs.get('observation_sim_time') == backend.now
                 and isinstance(speed, (int, float)) and not isinstance(speed, bool)
                 and math.isfinite(speed) and 0 <= speed < .15
                 and isinstance(p, (list, tuple)) and len(p) == 3
                 and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in p))
        previous = stop['last_sample_time']; previous_p = stop['last_position_m']
        if valid and previous is not None:
            dt = backend.now-previous
            valid = (abs(dt-1/30) < 1e-6 and math.dist(p[:2], previous_p[:2])/dt < .15)
        if not valid:
            stop.update(stable_since=None, stable_samples=0, last_sample_time=None, last_position_m=None)
            continue
        if stop['stable_since'] is None:stop['stable_since'] = backend.now
        stop['stable_samples'] += 1
        stop.update(last_sample_time=backend.now, last_position_m=list(p))
        if backend.now-stop['stable_since'] < .5-1e-7 or stop['stable_samples'] < 16:continue
        # Exact body and exact held claim were checked in this same main-thread tick.
        from simpeople.core.stationary_blockers import settled_stop_receipt
        receipt = settled_stop_receipt(stop, obs, body, backend.now)
        if receipt is not None:
            backend.instances[handle]['settled_stop_receipt'] = receipt
        backend.grid.release(handle);backend.local_yield_stops.pop(handle)
        backend.emit('traffic_cancelled_yield_claim_released', route_id=stop['route_id'], agent=handle,
                     body_instance_id=body, cells=sorted(stop['cells']), physical_stop_verified=True,
                     stable_since_sim_time=stop['stable_since'], actual_stable_samples=stop['stable_samples'])


def may_start(backend, handle):
    """A newly accepted action still waits for the prior moving body's stop."""
    backend.assert_thread()
    return handle not in backend.local_yield_stops
