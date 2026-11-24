"""Read-only diagnostic extraction; never query navigation or free occupancy."""
import math


ROUTE_FIELDS = ('handle', 'status', 'phase', 'native_task_id', 'step', 'goals',
                'goal_index', 'segment_goal', 'intent_points', 'blocked_details',
                'requested_sim_time', 'retry_at', 'retries', 'recovery_attempts',
                'grid_visits', 'drain_escape_points', 'guard_scope', 'local_yield',
                'last_local_yield', 'local_yield_attempted')
OBSERVATION_FIELDS = ('ready', 'position_m', 'speed_mps', 'facing_direction',
                      'action', 'native_task_id', 'observation_sim_time', 'sample_frame_id')


def capture_wait_snapshot(grid, fair_gate, routes, owner_routes, instances,
                          positions, observations, now, cycle, static_bounds, dynamic_bounds):
    """Detach actual in-memory state at a reported cycle, on the Kit thread.

    Observations came from tick start. Route state includes decisions made
    during that tick; it is not another SDK readback after those commands.
    """
    nonfinite, unsupported = [], []

    def safe(value, path):
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            if math.isfinite(value):
                return value
            nonfinite.append(path)
            return {'nonfinite': str(value)}
        if isinstance(value, dict):
            # A grid-visit dictionary can have tuple keys. Keep them as explicit
            # entries rather than silently converting them to actor/location IDs.
            if any(not isinstance(key, str) for key in value):
                return {'map_entries': [[safe(key, path+'.key'), safe(item, path+'.value')]
                                        for key, item in sorted(value.items(), key=lambda pair: repr(pair[0]))]}
            return {key: safe(item, path+'.'+key) for key, item in sorted(value.items())}
        if isinstance(value, (list, tuple, set)):
            ordered = sorted(value, key=repr) if isinstance(value, set) else value
            return [safe(item, path+'['+str(index)+']') for index, item in enumerate(ordered)]
        unsupported.append(path)
        return {'unsupported_type': type(value).__name__}

    tokens = set().union(*(row.get('drainers', set()) for row in fair_gate.pending.values()))
    bodies = {instance.get('traffic_instance_id'): handle for handle, instance in instances.items()
              if instance.get('traffic_instance_id') is not None}
    references = {}
    for token in tokens:
        if token in routes:
            references[token] = {'kind': 'registered_route', 'handle': routes[token]['handle'],
                                 'status': routes[token]['status']}
        elif token in bodies:
            references[token] = {'kind': 'current_traffic_body_generation', 'handle': bodies[token]}
        else:
            references[token] = {'kind': 'not_in_current_instance_or_registered_route_maps'}
    # Reading .cache or a plain dictionary must not call lazy edges.get(): doing
    # so would bake extra navigation edges and change the runtime being observed.
    cached = grid.edges if isinstance(grid.edges, dict) else getattr(grid.edges, 'cache', {})
    actors = {handle: {'actor_id': instance.get('actor_id'),
                       'traffic_body_instance_id': instance.get('traffic_instance_id'),
                       'cached_position_m': positions.get(handle),
                       'observation_at_tick_start': {key: observations.get(handle, {}).get(key)
                                                     for key in OBSERVATION_FIELDS},
                       'current_route_id': owner_routes.get(handle)}
              for handle, instance in instances.items()}
    result = safe({'schema_version': 'simpeople.wait-cycle-snapshot.v1',
        'sim_time': now, 'cycle': cycle, 'actors': actors,
        'grid': {'cell_m': grid.cell, 'margin_m': grid.margin, 'nodes': grid.nodes,
                 'claims': grid.claims, 'edges_already_cached': cached},
        'fair_gate': {'sequence': fair_gate.sequence, 'max_wait_sim_s': fair_gate.max_wait_sim_s,
                      'pending': fair_gate.pending, 'drainer_token_references': references},
        'active_owner_routes': owner_routes,
        'active_route_state': {rid: {key: routes[rid].get(key) for key in ROUTE_FIELDS}
                               for rid in set(owner_routes.values()) if rid in routes},
        'static_expanded_bounds_m': static_bounds, 'dynamic_expanded_bounds_m': dynamic_bounds,
        'scope': 'Read-only current memory. Native observations were taken before route commands in this tick. Traffic body IDs are backend generations, not Engine actor_instance_id. Cached edges are partial, not a newly queried NavMesh. No pose, reservation, age or task mutation.'}, 'snapshot')
    result['nonfinite_value_paths'] = nonfinite
    result['unsupported_value_paths'] = unsupported
    result['complete_serialization'] = not nonfinite and not unsupported
    return result
