"""Read-only candidates for body-aware search after a blocker loses its route.

This selects a search graph, never an admission or permission to move the idle
person. The caller still checks all bodies, leases and fair order on every leg.
"""
import math


def settled_stop_receipt(stop, observation, body_generation, now):
    """Record an already verified cancellation settlement, never infer one from Idle.

    The stop owner calls this after its 16 adjacent samples / 0.5 second gate.
    Consumers must still match the current generation, SDK task and position.
    """
    if (body_generation != stop.get('body_generation')
            or type(now) not in (int, float) or not math.isfinite(now)
            or type(stop.get('stable_since')) not in (int, float)
            or not math.isfinite(stop['stable_since'])
            or not 0 <= now-stop['stable_since']
            or now-stop['stable_since'] < .5-1e-7
            or type(stop.get('stable_samples')) is not int or stop['stable_samples'] < 16
            or stop.get('last_sample_time') != now
            or observation.get('observation_sim_time') != now
            or observation.get('position_source') != 'BehaviorAgent.get_world_translation'
            or observation.get('ready') is not True or observation.get('action') != 'Idle'
            or type(observation.get('native_task_id')) is not int
            or type(observation.get('speed_mps')) not in (int, float)
            or not math.isfinite(observation['speed_mps'])
            or not 0 <= observation['speed_mps'] < .15):
        return None
    position = observation.get('position_m')
    if (not isinstance(position, (tuple, list)) or len(position) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in position)
            or position != stop.get('last_position_m')):
        return None
    return dict(body_generation=body_generation, native_task_id=observation['native_task_id'],
                position_m=list(position), settled_sim_time=now,
                stable_since_sim_time=stop['stable_since'], actual_stable_samples=stop['stable_samples'],
                source='verified_cancelled_yield_stop')


def stopped_blockers(requester, details, instances, owner_routes, retained_stops,
                     observations, now):
    if type(now) not in (int, float) or not math.isfinite(now):
        return []
    handles = details.get('blocker_handles', []) if isinstance(details, dict) else []
    if not isinstance(handles, list) or any(not isinstance(h, str) for h in handles):
        return []
    result = []
    for handle in sorted(set(handles)):
        instance = instances.get(handle, {})
        body = instance.get('traffic_instance_id')
        if (handle == requester or not isinstance(body, str) or not body
                or owner_routes.get(handle) is not None or handle in retained_stops):
            continue
        cached = observations.get(handle)
        if not isinstance(cached, (tuple, list)) or len(cached) != 2 or cached[0] != now:
            continue
        obs = cached[1]
        if not isinstance(obs, dict):
            continue
        speed = obs.get('speed_mps'); position = obs.get('position_m')
        if (obs.get('ready') is not True or obs.get('action') != 'Idle'
                or obs.get('observation_sim_time') != now
                or obs.get('position_source') != 'BehaviorAgent.get_world_translation'
                or type(speed) not in (int, float) or not math.isfinite(speed)
                or not 0 <= speed < .15
                or not isinstance(position, (list, tuple)) or len(position) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in position)):
            continue
        receipt = instance.get('settled_stop_receipt')
        if (not isinstance(receipt, dict)
                or receipt.get('source') != 'verified_cancelled_yield_stop'
                or receipt.get('body_generation') != body
                or type(obs.get('native_task_id')) is not int
                or receipt.get('native_task_id') != obs['native_task_id']
                or type(receipt.get('settled_sim_time')) not in (int, float)
                or not math.isfinite(receipt['settled_sim_time'])
                or receipt['settled_sim_time'] > now
                or not isinstance(receipt.get('position_m'), (tuple, list))
                or len(receipt['position_m']) != 3
                or any(type(v) not in (int, float) or not math.isfinite(v)
                       for v in receipt['position_m'])
                or math.dist(position, receipt['position_m']) > .02):
            continue
        result.append(dict(handle=handle, body_generation=body, position_m=list(position)))
    return result
