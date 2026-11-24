"""Bounded NavMesh detours around an actual stopped, unowned body.

Opt-in planning only. Recheck the original 1cm path simplification, preserve the
route/deadline and atomic admission. The idle blocker never gets a task.
"""
import math

from simpeople.core.passage_prefix import protected_prefix
from simpeople.core.stationary_blockers import stopped_blockers
from simpeople.core.traffic import simplify_polyline


def start(backend, handle, rid, job, observation, submit, *, horizon_m=None):
    backend.assert_thread()
    if (not backend.runtime_policy.get('stationary_blocker_repair_enabled', False)
            or backend.runtime_policy.get('tail_release_enabled', False)
            or backend.owner_routes.get(handle) != rid
            or backend.routes.get(rid) is not job
            or job.get('phase') != 'travel' or job.get('native_task_id') is not None):
        return False
    blockers = stopped_blockers(handle, job.get('blocked_details'), backend.instances,
        backend.owner_routes, backend.local_yield_stops, backend.observations, backend.now)
    if not blockers:
        return False
    here = observation['position_m']; goal = job['goals'][job['goal_index']]
    nodes = [n for n in backend.grid.nodes
             if .5 <= math.dist(here[:2], backend.grid.point(n)[:2]) <= 4]
    nodes.sort(key=lambda n: (math.dist(here[:2], backend.grid.point(n)[:2])
                             + math.dist(backend.grid.point(n)[:2], goal[:2]), n))
    queries = 0
    for node in nodes[:12]:
        via = backend.grid.point(node)
        if not backend.grid.can_reserve(handle, backend.grid.footprint(via),
                                        backend.positions, via, via):
            continue
        path = []; valid = True
        for first, last in ((here, via), (via, goal)):
            queries += 1; leg = backend.segment(first, last)
            if (not leg or not 2 <= len(leg) <= 256
                    or any(len(p) != 3 or any(type(v) not in (int, float)
                        or not math.isfinite(v) for v in p) for p in leg)
                    or math.dist(leg[0], first) > .02 or math.dist(leg[-1], last) > .02):
                valid = False; break
            leg = [list(first), *[list(p) for p in leg[1:-1]], list(last)]
            path.extend(leg if not path else leg[1:])
        if not valid or not all(backend.grid.can_reserve(handle, backend.grid.sweep(a, b),
                backend.positions, a, b) for a, b in zip(path, path[1:])):
            continue
        raw_path = path
        path = simplify_polyline(raw_path, .01)
        if not all(backend.grid.can_reserve(handle, backend.grid.sweep(a, b),
                backend.positions, a, b) for a, b in zip(path, path[1:])):
            continue
        length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
        horizon = length
        if len(backend.instances) > 12:
            horizon = horizon_m
            if (type(horizon) not in (int, float)
                    or not math.isfinite(horizon) or horizon <= 0):
                return False
        try:
            prefix, profile = protected_prefix(path, horizon,
                getattr(backend, 'passage_no_stop_probe_zones', []))
        except ValueError:
            continue
        original_intent = job.get('intent_points')
        original_escape = job.get('drain_escape_points')
        job['intent_points'] = prefix
        job['drain_escape_points'] = path
        if not backend.admit_reservation(handle, rid, job, prefix, polyline=True,
                                        drain_exit_cells=backend.grid.footprint(goal)):
            job['intent_points'] = original_intent
            job['drain_escape_points'] = original_escape
            continue
        if job['status'] == 'blocked':
            backend.emit('traffic_wait_ended', route_id=rid,
                         wait_sim_s=backend.now-job['blocked_since'])
        spec = dict(action='move_to', target=list(prefix[-1]), gait=job['step'].get('gait', 'walk'))
        if len(prefix) > 2: spec['via'] = [list(p) for p in prefix[1:-1]]
        if 'speed_mps' in job['step']: spec['speed_mps'] = job['step']['speed_mps']
        job.update(status='running', blocked_since=None, segment_goal=list(prefix[-1]),
                   continuous_active=True, continuous_next_goal_index=job['goal_index'],
                   history_segment=False, corridor_candidate=None)
        job.pop('tail', None)
        job['native_task_id'] = submit(handle, spec)
        backend.emit('traffic_stationary_body_detour', route_id=rid, agent=handle,
            native_task_id=job['native_task_id'], actual_blockers=blockers,
            waypoint_m=via, full_navmesh_path_m=path, submitted_points_m=prefix,
            raw_navmesh_path_m=raw_path, simplification_tolerance_m=.01,
            original_current_goal_m=list(goal), original_goals_m=[list(p) for p in job['goals']],
            original_requested_sim_time=job['requested_sim_time'], actual_navmesh_queries=queries,
            prefix_profile=profile, strategy='same_goal_navmesh_detour_around_stopped_body')
        backend.emit('traffic_native_started', route_id=rid, native_task_id=job['native_task_id'],
            action='stationary_body_detour', points_m=prefix, final_auto_brake=True)
        return True
    return False
