"""Record the existing predicate results, without extra queries or commands."""
import math


PHASES = {'start_candidate_unavailable', 'goal_candidate_unavailable',
          'grid_path_unavailable', 'goal_footprint_blocked'}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def point(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3 or not all(finite(v) for v in value):
        raise ValueError('planner point is not a finite three-vector')
    return list(value)


def node(value):
    if value is None: return None
    if len(value) != 2 or any(type(v) is not int for v in value):
        raise ValueError('planner node is not an integer grid pair')
    return list(value)


def select_candidate(nodes, blocked, clearance, connector, *, connector_first=False, clearance_required=True):
    """Preserve the original lazy predicate order and record each actual test."""
    checks = []
    for candidate in nodes:
        row = {'node': candidate, 'in_blocked_set': candidate in blocked,
               'swept_clearance': None, 'connector': None,
               'clearance_required': clearance_required, 'accepted': False}
        checks.append(row)
        if row['in_blocked_set']: continue
        if not connector_first:
            row['swept_clearance'] = bool(clearance(candidate))
            if not row['swept_clearance']: continue
        row['connector'] = bool(connector(candidate))
        if not row['connector']: continue
        if connector_first and clearance_required:
            row['swept_clearance'] = bool(clearance(candidate))
            if not row['swept_clearance']: continue
        row['accepted'] = True
        return candidate, checks
    return None, checks


def report_search_wait(backend, handle, rid, job, observation, phase, goal,
                       starts, blocked, *, start=None, ends=None, end=None, goal_cells=None,
                       start_checks=None, goal_checks=None):
    """Record the branch already taken, at most once per two seconds/phase.

    Only cached coordinates and the caller's actual candidate/blocked sets are
    read. Explicit checks distinguish False from not evaluated (None). A
    candidate outside the blocked set has NOT thereby passed its other tests.
    The private per-route cache only limits log volume; it does not drive jobs.
    """
    now = backend.now
    previous = job.get('_path_diagnostic_last')
    previous = previous if isinstance(previous, dict) else {}
    goal_key = tuple(goal) if isinstance(goal, (list, tuple)) and len(goal) == 3 and all(finite(v) for v in goal) else None
    signature = (phase, job.get('goal_index'), goal_key)
    if (finite(now) and previous.get('signature') == signature and finite(previous.get('time'))
            and 0 <= now-previous['time'] < 2):
        return
    base = {'route_id': rid, 'agent': handle, 'planner_phase': phase,
            'sample_sim_time': now if finite(now) else None}
    try:
        if phase not in PHASES or not finite(now): raise ValueError('invalid planner phase or clock')
        def candidates(values):
            if values is None: return None  # Goal selection was not reached.
            return [{'node': node(n), 'point_m': point(backend.grid.point(n)),
                     'in_blocked_set': n in blocked} for n in values]
        def recorded_checks(values):
            return None if values is None else [{**v, 'node': node(v['node'])} for v in values]
        payload = {**base, 'body_instance_id': backend.instances.get(handle, {}).get('traffic_instance_id'),
            'origin_m': point(observation['position_m']), 'target_m': point(goal),
            'goal_index': job.get('goal_index'), 'route_status_before_wait': job.get('status'),
            'route_requested_sim_time': job.get('requested_sim_time'),
            'route_native_task_id': job.get('native_task_id'),
            'observed_native_task_id': observation.get('native_task_id'),
            'observed_native_action': observation.get('action'),
            'observation_sim_time': observation.get('observation_sim_time'),
            'position_source': observation.get('position_source'),
            'node_count': len(backend.grid.nodes), 'blocked_cell_count': len(blocked),
            'start_candidates': candidates(starts), 'goal_candidates': candidates(ends),
            'start_checks': recorded_checks(start_checks), 'goal_checks': recorded_checks(goal_checks),
            'selected_start': node(start), 'selected_goal': node(end),
            'connection_results_recorded': start_checks is not None and (ends is None or goal_checks is not None), 'blocker_ids': None,
            'physical_feasibility_verified': False, 'causal_blocker_verified': False}
        if phase == 'goal_footprint_blocked':
            if goal_cells is None: raise ValueError('goal footprint result was not supplied')
            payload['goal_blocked_cells'] = [node(n) for n in sorted(goal_cells & blocked)]
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        backend.emit('traffic_path_search_diagnostic_unavailable', **base,
                     error_type=type(error).__name__, message=str(error))
    else:
        backend.emit('traffic_path_search_wait', **payload)
    # Sink errors propagate: an incomplete journal must not become a pass.
    if finite(now): job['_path_diagnostic_last'] = {'time': now, 'signature': signature}
