"""Audit a failed search's closed reachable component without NavMesh queries.

The frontier lists contributors to blocked cells. It does not establish that
removing a particular person would make the target reachable or physically safe.
"""
import argparse
import json
import math
from pathlib import Path

from audit_path_search_prefix import audit as base_audit, arrival, load


def pairs(values):
    if not isinstance(values, list):
        raise ValueError('node list missing')
    result = []
    for value in values:
        if not isinstance(value, list) or len(value) != 2 or any(type(v) is not int for v in value):
            raise ValueError('noninteger graph node')
        result.append(tuple(value))
    if len(set(result)) != len(result):
        raise ValueError('duplicate graph node')
    return result


def verify_cut(event, traffic, dynamic):
    if dynamic:
        raise ValueError('dynamic edge receipt not captured; static cache cannot prove this search')
    payload = event['payload']
    if payload['planner_phase'] != 'grid_path_unavailable':
        raise ValueError('cut audit requires an actual grid search failure')
    graph = event['cached_grid_graph']
    kind = graph['kind']
    if (kind not in {'explicit_adjacency', 'verified_lazy_cache'}
            or graph['unqueried_nodes_are_unknown'] is not (kind == 'verified_lazy_cache')
            or type(graph['additional_navmesh_queries']) is not int or graph['additional_navmesh_queries'] != 0):
        raise ValueError('graph receipt overstates cached data')
    nodes = set(pairs(graph['nodes']))
    if len(nodes) != payload['node_count']:
        raise ValueError('graph node denominator differs')
    adjacency = {}
    for row in graph['adjacency']:
        node = pairs([row['node']])[0]
        neighbors = pairs(row['neighbors'])
        if node in adjacency or node not in nodes or any(n not in nodes for n in neighbors):
            raise ValueError('graph has a foreign or repeated node')
        if kind == 'verified_lazy_cache' and any(abs(node[0]-n[0])+abs(node[1]-n[1]) != 1 for n in neighbors):
            raise ValueError('lazy graph is not the actual four-neighbor grid')
        adjacency[node] = neighbors
    start, goal = pairs([payload['selected_start'], payload['selected_goal']])
    inputs = event['planner_inputs']; actor = payload['agent']
    grid = traffic.ReservationGrid(nodes, {}, cell_m=inputs['cell_m'], margin_m=inputs['margin_m'])
    grid.claims = {h: set(pairs(cells)) for h, cells in event['claims'].items()}
    positions = inputs['positions_m']; blocked = grid.blocked(actor, positions)
    if len(blocked) != payload['blocked_cell_count'] or start in blocked or goal in blocked:
        raise ValueError('blocked set or accepted endpoints differ')
    if start not in nodes or goal not in nodes:
        raise ValueError('accepted endpoint absent from graph')
    pending = [start]; reachable = {start}; frontier = set()
    while pending:
        node = pending.pop()
        if node == goal:
            raise ValueError('recorded graph has a free path despite search failure')
        if node not in adjacency:
            if kind == 'verified_lazy_cache':
                raise ValueError('reachable node was not queried; cut cannot be verified')
            neighbors = []  # A missing explicit dict key returns [], unlike a lazy cache.
        else:
            neighbors = adjacency[node]
        for other in neighbors:
            if other in blocked:
                frontier.add((node, other))
            elif other not in reachable:
                reachable.add(other); pending.append(other)
    owners = []
    for cell in sorted({other for _, other in frontier}):
        body = sorted(h for h, pos in positions.items() if h != actor and cell in grid.footprint(pos)
                      and math.dist(grid.point(cell)[:2], pos[:2]) < .9)
        claims = sorted(h for h, cells in grid.claims.items() if h != actor and cell in cells)
        if not body and not claims:
            raise ValueError('blocked frontier cell has no actual contributor')
        owners.append({'cell': list(cell), 'body_owners': body, 'reservation_owners': claims})
    return {'actor_id': event['actor_id'], 'source_tick': event['source_tick'], 'sim_time': event['sim_time'],
            'reachable_component_verified': True, 'reachable_node_count': len(reachable),
            'reachable_nodes': [list(n) for n in sorted(reachable)],
            'blocked_frontier': [{'from': list(a), 'to': list(b)} for a, b in sorted(frontier)],
            'frontier_contributors': owners, 'additional_navmesh_queries': 0,
            'individual_causal_blocker_verified': False, 'physical_feasibility_verified': False}


def audit(run, source, case, probe, trace, shared):
    result = base_audit(run, source, case, probe, trace, shared)
    checked = []; errors = []
    if result['measurement_verified'] and result['planner_diagnostics_verified']:
        try:
            folder = Path(run); snap = folder/'source_snapshot'
            traffic = load(snap/'src/simpeople/core/traffic.py', 'cut_actual_traffic')
            policy = load(snap/'src/simpeople/core/runtime_policy.py', 'cut_actual_policy').DEFAULT_POLICY
            config = json.loads((snap/'configs/runtime_policy.json').read_text())
            dynamic = config.get('dynamic_edges_enabled', policy['dynamic_edges_enabled'])
            for event in arrival.lines(folder/'arrival_recovery_direct_events.jsonl'):
                if (event['kind'] == 'traffic_path_search_wait' and event['actor_id'] == 'person_020'
                        and event['payload']['planner_phase'] == 'grid_path_unavailable'):
                    checked.append(verify_cut(event, traffic, dynamic))
        except (ValueError, KeyError, TypeError, IndexError, OSError, AttributeError) as error:
            errors.append(type(error).__name__+': '+str(error))
    result.update(cached_search_cuts=checked, cached_search_cut_errors=errors,
                  cached_search_cut_verified=bool(checked and not errors and result['measurement_verified']),
                  individual_causal_blocker_verified=False, additional_navmesh_queries=0)
    result['scope'] += ' Cached cut contributors are not single-actor causal proof.'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    for name in ['source', 'case', 'probe', 'trace', 'shared', 'output']:
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    result = audit(args.run, args.source, args.case, args.probe, args.trace, args.shared)
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: result[k] for k in ['measurement_verified', 'cached_search_cut_verified', 'cached_search_cut_errors']}))
    raise SystemExit(0 if result['cached_search_cut_verified'] else 2)
