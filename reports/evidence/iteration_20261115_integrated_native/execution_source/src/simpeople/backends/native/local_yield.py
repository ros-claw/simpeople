"""Bounded NavMesh proposals for explicitly authorized route recovery.

Kit-thread adapter helper. No task, pose, reservation or fair-age mutation.
The existing Engine.try_recovery remains the on_blocked/budget authorizer.
Experimental staging only; no product runtime hook is installed yet.
"""
import math
import copy

from simpeople.core.drainage_candidate import check_candidate


def snapshot(backend, handle, rid, phase):
    """Cached tick-start observations, not a second SDK/world advancement."""
    try:
        from simpeople.core.wait_snapshot import capture_wait_snapshot
        observations = {h: cached[1] for h, cached in backend.observations.items()
                        if abs(cached[0]-backend.now) < 1e-7}
        data = capture_wait_snapshot(backend.grid, backend.fair_gate, backend.routes, backend.owner_routes,
                    backend.instances, backend.positions, observations, backend.now, {},
                    backend.static_bounds, backend.dynamic_bounds)
        data['schema_version'] = 'simpeople.route-repair-snapshot.v1'
        data.pop('cycle')
        data['repair_context'] = {'agent': handle, 'route_id': rid, 'phase': phase}
        data['scope'] += ' Repair phase memory only, not a newly reported cycle or post-command SDK readback.'
        backend.emit('traffic_local_yield_snapshot', route_id=rid, agent=handle, phase=phase, snapshot=data)
    except Exception as error:
        backend.emit('traffic_local_yield_snapshot_unavailable', route_id=rid, agent=handle,
                     phase=phase, error_type=type(error).__name__, message=str(error))


def propose(backend, handle, rid, job):
    backend.assert_thread()
    if not backend.runtime_policy.get('cycle_drainage_enabled', False):
        return None
    if (backend.owner_routes.get(handle) != rid or backend.routes.get(rid) is not job
            or job['status'] != 'blocked' or job['phase'] != 'travel'
            or job['step']['action'] != 'move_to' or job.get('native_task_id') is not None
            or job.get('local_yield') is not None or job.get('local_yield_attempted')
            or not any(handle in members for members in backend.wait_graph.since)):
        return None
    obs = backend.observe(handle); instance = backend.instances.get(handle, {})
    body = instance.get('traffic_instance_id'); pending = backend.fair_gate.pending.get(rid)
    if (not pending or pending['actor'] != handle or pending['occupant_token'] != body
            or pending['state'] != 'waiting' or pending['wait_since'] is None
            or backend.now-pending['wait_since'] < backend.runtime_policy['recovery_after_wait_sim_s']-1e-7
            or obs.get('ready') is not True or obs.get('action') != 'Idle'
            or not isinstance(obs.get('speed_mps'), (int, float)) or isinstance(obs['speed_mps'], bool) or not math.isfinite(obs['speed_mps'])
            or not 0 <= obs['speed_mps'] < .15 or obs.get('observation_sim_time') != backend.now):
        return None
    agent = backend.agent(handle); sdk_id = obs['native_task_id']
    if (not isinstance(sdk_id, int) or isinstance(sdk_id, bool)
            or agent.get_action_task_id() != sdk_id or agent.get_task_name(sdk_id) != 'Idle'):
        return None
    stamp = (backend.now, pending['since'], pending['sequence'], pending['wait_since'])
    origin = obs['position_m']
    nodes = sorted((n for n in backend.grid.nodes if .5 <= math.dist(origin[:2], backend.grid.point(n)[:2]) <= 3),
                   key=lambda n: (math.dist(origin[:2], backend.grid.point(n)[:2]), n))
    queries = 0
    for node in nodes[:12]:
        target = backend.grid.point(node); queries += 1
        path = backend.segment(origin, target)
        if (not path or not 2 <= len(path) <= 256 or any(len(p) != 3 or any(not math.isfinite(v) for v in p) for p in path)
                or math.dist(path[0], origin) > .02 or math.dist(path[-1], target) > .02):
            continue
        # Keep every original NavMesh corner and the actual endpoint legs.
        points = [list(origin), *[list(p) for p in path[1:-1]], list(target)]
        proof = check_candidate(backend.grid, backend.fair_gate.pending, rid, body, points, backend.positions, backend.now)
        if not proof['eligible']:
            continue
        # A NavMesh query is not permission to borrow a later owner or body.
        if (backend.owner_routes.get(handle) != rid or backend.routes.get(rid) is not job
                or backend.instances.get(handle, {}).get('traffic_instance_id') != body
                or backend.fair_gate.pending.get(rid) is not pending
                or (backend.now, pending['since'], pending['sequence'], pending['wait_since']) != stamp
                or agent.get_action_task_id() != sdk_id
                or math.dist(backend.to_public(agent.get_world_translation()), origin) > 1e-5):
            return None
        return {'geometry': proof, 'actual_navmesh_queries': queries,
                'original_native_idle_task_id': int(sdk_id), 'observed_sim_time': backend.now,
                'native_navmesh_path_m': [list(p) for p in path],
                'scope': 'Current NavMesh and full-claim/body candidate only. Existing Engine recovery permission/budget and atomic admission still required.'}
    return None


def start(backend, handle, rid, job, proposal, submit):
    """The Engine has already authorized this opt-in recovery attempt."""
    proof = proposal['geometry']; points = proof['path_m']; old_goal = list(job['goals'][-1])
    cells = set(map(tuple, proof['conservative_cells']))
    snapshot(backend, handle, rid, 'before_admission')
    if not backend.grid.reserve_polyline(handle, points, backend.positions, extra_cells=cells):
        return {'accepted': False, 'reason': 'admission_changed', 'original_target_m': old_goal}
    cells = set(backend.grid.claims[handle])
    saved = {key: copy.deepcopy(job.get(key)) for key in ['goals', 'goal_index', 'step', 'intent_points',
              'grid_visits', 'history_goal_index', 'segment_goal', 'guard_scope']}
    ticket = backend.fair_gate.pending[rid]
    fingerprint = {k: copy.deepcopy(ticket[k]) for k in ['since', 'sequence', 'wait_since', 'cells',
                   'goal_cells', 'drainers', 'occupant_token']}
    spec = {'action': 'move_to', 'target': list(points[-1]), 'gait': 'walk', 'speed_mps': 1.2}
    if len(points) > 2: spec['via'] = [list(p) for p in points[1:-1]]
    try:
        native = submit(spec)
    except Exception:
        backend.grid.release(handle)  # No accepted movement; no former own claim existed.
        raise
    data = {'saved_route': saved, 'ticket_fingerprint': fingerprint,
            'body_generation': proof['body_generation'], 'path_m': copy.deepcopy(points),
            'conservative_cells': sorted(cells), 'proposal': proposal, 'native_task_id': native,
            'started_sim_time': backend.now, 'deadline_sim_time': backend.now+8,
            'observed_native_start': False, 'applied': False, 'settled_since': None}
    job.update(local_yield=data, local_yield_attempted=True, goals=[list(points[-1])], goal_index=0,
               step=spec, intent_points=copy.deepcopy(points), segment_goal=list(points[-1]),
               native_task_id=native, status='running', phase='travel', blocked_since=None,
               continuous_active=True, continuous_next_goal_index=0, history_segment=False,
               corridor_candidate=None, retry_at=backend.now)
    job.pop('tail', None)
    backend.emit('traffic_recovery_requested', route_id=rid, agent=handle, attempt=job['recovery_attempts'],
                 strategy='bounded_local_yield_then_original_goal', target_m=old_goal, yield_target_m=points[-1],
                 preserved_priority_since_sim_time=ticket['since'], preserved_wait_since_sim_time=ticket['wait_since'])
    backend.emit('traffic_native_started', route_id=rid, agent=handle, native_task_id=native,
                 action='local_yield', points_m=points, original_target_m=old_goal,
                 body_instance_id=proof['body_generation'], reserved_cells=sorted(cells),
                 final_auto_brake=True, local_yield_deadline_sim_time=data['deadline_sim_time'])
    snapshot(backend, handle, rid, 'native_submitted')
    return {'accepted': True, 'strategy': 'bounded_local_yield_then_original_goal',
            'attempt': job['recovery_attempts'], 'original_target_m': old_goal,
            'temporary_target_m': list(points[-1]), 'deadline_sim_time': data['deadline_sim_time']}


def begin_brake(backend, handle, rid, job, reason, stop_sdk=None):
    data = job['local_yield']
    if job['phase'] != 'local_yield_braking':
        if stop_sdk is not None: stop_sdk()
        job.update(phase='local_yield_braking', status='blocked', native_task_id=None,
                   blocked_since=backend.now,
                   blocked_details={'reason': 'local_yield_braking', 'since_sim_time': backend.now,
                                    'blocker_ids': [], 'blocker_handles': []})
        data.update(brake_reason=reason, settled_since=None)
        backend.emit('traffic_local_yield_brake', route_id=rid, agent=handle, reason=reason,
                     original_target_m=data['saved_route']['goals'][-1])


def advance(backend, handle, rid, job, obs, native, stop_sdk):
    """True permits the ordinary route driver; False retains this phase."""
    data = job['local_yield']
    if (backend.owner_routes.get(handle) != rid
            or backend.instances.get(handle, {}).get('traffic_instance_id') != data['body_generation']):
        return False  # A stale route must neither stop nor release a later owner.
    position = obs.get('position_m'); speed = obs.get('speed_mps')
    finite_readback = (obs.get('ready') is True and isinstance(position,(list,tuple)) and len(position)==3
        and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in position)
        and isinstance(speed,(int,float)) and not isinstance(speed,bool) and math.isfinite(speed) and speed>=0)
    if job['phase'] == 'local_yield_braking':
        if not finite_readback or obs.get('action') != 'Idle' or speed >= .15:
            data['settled_since'] = None; return False
        if data['settled_since'] is None: data['settled_since'] = backend.now
        if backend.now-data['settled_since'] < .5-1e-7: return False
        backend.emit('traffic_local_yield_ended', route_id=rid, agent=handle, status='failed',
                     reason=data['brake_reason'], physical_stop_verified=True,
                     original_target_m=data['saved_route']['goals'][-1])
        backend.complete(rid, job, 'failed', {'code': 'LOCAL_YIELD_FAILED', 'stage': 'navigation',
                         'message': data['brake_reason'], 'details': {'physical_stop_verified': True,
                         'original_target_m': data['saved_route']['goals'][-1]}})
        return False
    ticket = backend.fair_gate.pending.get(rid)
    if (not ticket or ticket['state'] != 'waiting' or any(ticket.get(k) != v for k, v in data['ticket_fingerprint'].items())
            or backend.grid.claims.get(handle) != set(map(tuple, data['conservative_cells']))):
        begin_brake(backend, handle, rid, job, 'ownership_or_wait_scope_changed', stop_sdk); return False
    if backend.now > data['deadline_sim_time']+1e-7 or native == 'failed':
        begin_brake(backend, handle, rid, job, 'yield_deadline' if native != 'failed' else 'native_yield_failed', stop_sdk); return False
    if not finite_readback:
        begin_brake(backend, handle, rid, job, 'actual_readback_missing', stop_sdk); return False
    p = obs['position_m']; points = data['path_m']
    def distance(a, b):
        dx, dy = b[0]-a[0], b[1]-a[1]; length2 = dx*dx+dy*dy
        t = max(0., min(1., ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length2)) if length2 else 0
        return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)
    if (abs(p[2]-points[0][2]) > .1 or min(distance(a, b) for a, b in zip(points, points[1:])) > .35
            or not backend.grid.footprint(p) <= backend.grid.claims[handle]):
        begin_brake(backend, handle, rid, job, 'actual_body_left_owned_yield_path', stop_sdk); return False
    if native == 'running':
        current = backend.agent(handle).get_action_task_id()
        if current != data['native_task_id']:
            if (not data['observed_native_start'] and backend.now-data['started_sim_time'] <= 1
                    and current == data['proposal']['original_native_idle_task_id'] and obs['action'] == 'Idle'):
                return False
            begin_brake(backend, handle, rid, job, 'native_owner_changed', stop_sdk); return False
        data['observed_native_start'] = True
        if not data['applied'] and math.dist(p[:2], points[0][:2]) > .1:
            data['applied'] = True
            backend.emit('traffic_local_yield_motion_observed', route_id=rid, agent=handle,
                         strategy='bounded_local_yield_then_original_goal', attempt=job['recovery_attempts'],
                         original_target_m=data['saved_route']['goals'][-1], temporary_target_m=points[-1],
                         actual_position_m=p, native_task_id=data['native_task_id'], wait_age_preserved=True)
        return True
    if native == 'succeeded':
        actual_cells = backend.grid.footprint(p)
        cleared = all(not actual_cells & set(map(tuple, old['protected_cells']))
                      for old in data['proposal']['geometry']['drained_older_fences'])
        good = (math.dist(p[:2], points[-1][:2]) <= .3 and obs['speed_mps'] < .15
                and obs.get('action') == 'Idle' and cleared)
        if not good: data['settled_since'] = None; return False
        if data['settled_since'] is None: data['settled_since'] = backend.now
        return backend.now-data['settled_since'] >= .5-1e-7
    return False


def restore_original(backend, handle, rid, job):
    data = job['local_yield']; saved = data['saved_route']; ticket = backend.fair_gate.pending[rid]
    backend.emit('traffic_local_yield_ended', route_id=rid, agent=handle, status='succeeded',
                 original_target_m=saved['goals'][-1], temporary_target_m=data['path_m'][-1],
                 physical_stop_verified=True, original_wait_since_sim_time=ticket['wait_since'],
                 original_priority_since_sim_time=ticket['since'], actual_sdk_samples_required=True)
    job.update(saved)
    job.update(status='blocked', phase='travel', native_task_id=None, continuous_active=False,
               corridor_candidate=None, blocked_since=ticket['wait_since'],
               blocked_details={'reason': 'yield_complete_resume_original', 'since_sim_time': ticket['wait_since'],
                                'blocker_handles': [], 'blocker_ids': []})
    job['last_local_yield'] = {'started_sim_time': data['started_sim_time'], 'ended_sim_time': backend.now,
                             'original_target_m': saved['goals'][-1], 'temporary_target_m': data['path_m'][-1],
                             'applied': data['applied']}
    job.pop('local_yield')
    snapshot(backend, handle, rid, 'original_goal_restored')
