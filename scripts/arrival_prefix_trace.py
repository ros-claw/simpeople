"""Read-only Kit-thread instrumentation for an arrival-recovery prefix.

No world stepping, requests, Native commands or pose writes occur here.
"""
import copy
import json
from pathlib import Path


ROUTE_FIELDS = ('handle', 'status', 'phase', 'native_task_id', 'segment_goal', 'goals', 'goal_index',
    'requested_sim_time', 'retries', 'retry_at', 'recovery_attempts', 'step', 'blocked_since',
    'blocked_details', 'continuous_active', 'arrival_confirmation', 'arrival_identity',
    'arrival_stop_id', 'arrival_stop_window', 'arrival_segment_fallback')


def cached_graph_snapshot(grid):
    """Copy only graph data already evaluated by the actual search.

    Calling edges.get() would populate VerifiedLazyEdges and issue new NavMesh
    queries. Reading its cache deliberately leaves unexplored nodes unknown.
    """
    edges = grid.edges
    if type(edges) is dict:
        kind, cache = 'explicit_adjacency', edges
    elif type(edges).__name__ == 'VerifiedLazyEdges' and type(edges.cache) is dict:
        kind, cache = 'verified_lazy_cache', edges.cache
    else:
        raise ValueError('unsupported graph cache; never materialize lazy edges')
    return {'kind': kind, 'nodes': [list(n) for n in sorted(grid.nodes)],
            'adjacency': [{'node': list(n), 'neighbors': [list(v) for v in neighbors]}
                          for n, neighbors in sorted(cache.items())],
            'unqueried_nodes_are_unknown': kind == 'verified_lazy_cache',
            'additional_navmesh_queries': 0}


class ArrivalPrefixTrace:
    def __init__(self, backend, engine, directory):
        self.backend = backend; self.engine = engine; self.directory = Path(directory)
        self.stream = (self.directory/'arrival_recovery_frames.jsonl').open('w')
        self.events = (self.directory/'arrival_recovery_direct_events.jsonl').open('w')
        self.frames = 0; self.read_errors = 0
        self.original_sink = backend.on_event
        self.hook = self._on_backend_event
        backend.on_event = self.hook

    def _actor(self, aid, actor, obs):
        backend, engine = self.backend, self.engine
        handle = actor['handle']; rid = backend.owner_routes.get(handle); route = backend.routes.get(rid)
        errors = []
        def read(label, callback):
            try: return callback()
            except Exception as error:
                errors.append({'operation': label, 'error': str(error)})
                return None
        agent = read('get_agent', lambda: backend.agent(handle))
        current = read('current_sdk_id', lambda: int(agent.get_action_task_id()))
        binding = {'actor_instance_id': actor['actor_instance_id'], 'control_epoch': actor['control_epoch'],
            'task_id': actor['task_id'], 'native_actor_prim_path': handle,
            'traffic_body_instance_id': backend.instances[handle]['traffic_instance_id'],
            'sdk_enabled': read('enabled', lambda: bool(agent.is_enabled())),
            'actual_sdk_position_m': read('actual_sdk_root', lambda: backend.to_public(agent.get_world_translation())),
            'actual_sdk_task_id': current, 'actual_sdk_task_name': read('current_sdk_name', lambda: agent.get_task_name(current)),
            'observation_sim_time': obs.get('observation_sim_time'), 'observation_ready': obs.get('ready'), 'read_errors': errors}
        ids = {current}
        if route:
            ids.update([route.get('native_task_id'), route.get('arrival_stop_id')])
            if route.get('arrival_identity'): ids.add(route['arrival_identity'][3])
        statuses = {}; elapsed = {}
        for tid in sorted(t for t in ids if type(t) is int and t > 0):
            statuses[str(tid)] = read('sdk_status_'+str(tid), lambda tid=tid: backend.task_state(handle, tid))
            elapsed[str(tid)] = read('sdk_elapsed_'+str(tid), lambda tid=tid: float(agent.get_task_elapsed_time(tid)))
        task = engine.tasks.get(actor['task_id']); guard = backend.fair_gate.pending.get(rid)
        data = {'binding': binding, 'observation': obs, 'task': engine.public(task) if task else None,
            'seat': actor['seat'], 'route_id': rid,
            'route': {k: route.get(k) for k in ROUTE_FIELDS} if route else None,
            'native_status': statuses, 'native_elapsed_s': elapsed,
            'guard': {k: guard.get(k) for k in ['since', 'wait_since', 'state', 'scope', 'occupant_token']} if guard else None}
        self.read_errors += len(errors)
        return data

    def _on_backend_event(self, kind, **payload):
        critical = kind in {'traffic_arrival_shortfall', 'traffic_arrival_stop_requested',
                            'traffic_arrival_stop_unavailable', 'traffic_arrival_replan_ready',
                            'traffic_path_search_wait', 'traffic_path_search_diagnostic_unavailable'}
        critical = critical or kind == 'traffic_route_ended' and (payload.get('error') or {}).get('code') == 'NATIVE_ARRIVAL_MISMATCH'
        direct = None
        if critical:
            try:
                self.backend.assert_thread()
                handle = payload['agent']; aid, actor = next((aid, a) for aid, a in self.engine.actors.items() if a['handle'] == handle)
                # Read the existing cache, not observe(), so the event observer
                # cannot flush a deferred stop or change animation state.
                cached = self.backend.observations.get(handle)
                obs = cached[1] if cached else {}
                direct = copy.deepcopy({'kind': kind, 'payload': payload, 'actor_id': aid,
                    'sim_time': self.engine.sim_time, 'source_tick': self.engine.journal.frames,
                    'session_id': self.engine.session_id, 'episode_id': self.engine.episode_id,
                    'actor': self._actor(aid, actor, obs),
                    'claims': {owner: sorted(cells) for owner, cells in self.backend.grid.claims.items()}})
                if kind.startswith('traffic_path_search_'):
                    direct['planner_inputs'] = copy.deepcopy({
                        'positions_m': self.backend.positions,
                        'cell_m': self.backend.grid.cell, 'margin_m': self.backend.grid.margin})
                    if aid == 'person_020' and payload.get('planner_phase') == 'grid_path_unavailable':
                        direct['cached_grid_graph'] = cached_graph_snapshot(self.backend.grid)
            except Exception as error:
                self.read_errors += 1
                direct = {'kind': kind, 'capture_error': {'type': type(error).__name__, 'message': str(error)}}
        # Forward the original event unchanged, even if diagnostic reads failed.
        result = self.original_sink(kind, **payload) if self.original_sink else None
        if direct is not None:
            direct['event_cursor_after'] = self.engine.event_sequence
            self.events.write(json.dumps(direct, allow_nan=False)+'\n')
        return result

    def sample(self, identity):
        backend, engine = self.backend, self.engine
        backend.assert_thread()
        bindings = {}; selected = {}
        for aid, actor in engine.actors.items():
            handle = actor['handle']; obs = backend.observe(handle)
            rid = backend.owner_routes.get(handle); route = backend.routes.get(rid)
            data = self._actor(aid, actor, obs); bindings[aid] = data['binding']
            if aid in {'person_020', 'person_001'} or route and route.get('arrival_identity'):
                selected[aid] = data
        row = {'frame_identity': identity, 'sim_time': engine.sim_time,
               'session_id': engine.session_id, 'episode_id': engine.episode_id,
               'timeline_playing': backend.timeline.is_playing(),
               'arrival_recovery_enabled': getattr(backend, 'arrival_recovery_probe_enabled', False),
               'body_bindings': bindings, 'actors': selected,
               'claims': {owner: sorted(cells) for owner, cells in backend.grid.claims.items()} if backend.grid else {},
               'resources': engine.resources.snapshot(), 'queues': engine.queues.snapshot()}
        self.stream.write(json.dumps(copy.deepcopy(row), allow_nan=False)+'\n')
        self.frames += 1

    def close(self):
        if self.backend.on_event is self.hook:
            self.backend.on_event = self.original_sink
        self.stream.close()
        self.events.close()
        (self.directory/'arrival_trace_metrics.json').write_text(json.dumps({
            'frames': self.frames, 'read_errors': self.read_errors,
            'scope': 'Actual main-thread SDK reads and existing state only; no mutation or full-workload qualification.'}, indent=2)+'\n')
