"""Explain reported native wait cycles without changing their original grades.

The live dependency graph is authoritative for edges. Candidate rejections and
fairness deferrals only corroborate possible causes; they are not a complete
snapshot of the chosen path, physical occupancy or fair-gate state.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


KINDS = {'traffic_route_started', 'traffic_route_ended', 'traffic_route_cancelled', 'traffic_candidate_rejected',
         'traffic_fairness_deferred', 'traffic_wait_dependencies', 'traffic_wait_cycle', 'task_wait_cycle'}
FENCES = ('session_id', 'episode_id', 'actor_id', 'actor_instance_id', 'control_epoch')


def explain(events, tasks, world):
    """Single journal pass; never borrow evidence from a former route or actor."""
    tasks = {task['task_id']: task for task in tasks}
    active, rejected, deferred = {}, {}, {}
    graph, graph_event = set(), None
    cycles, task_cycles, errors, unbound = [], [], [], []
    cursor, clock = -1, -math.inf

    def valid(e, handle, rid):
        task = tasks.get(e.get('task_id'))
        return (task is not None and active.get(handle) == rid and
                e.get('agent') == handle and e.get('route_id') == rid and
                all(e.get(key) == task.get(key) and e.get(key) is not None for key in FENCES))

    for e in events:
        if e['kind'] not in KINDS:
            continue
        if any(e.get(key) != world[key] for key in ('session_id', 'episode_id')):
            errors.append({'cursor': e['cursor'], 'reason': 'world_fence_mismatch'})
            continue
        if e['cursor'] <= cursor or not math.isfinite(e['sim_time']) or e['sim_time'] < clock-1e-7:
            raise ValueError('reordered or non-finite diagnostic journal')
        cursor, clock = e['cursor'], e['sim_time']
        kind, handle, rid = e['kind'], e.get('agent'), e.get('route_id')
        if kind == 'traffic_route_started':
            active[handle] = rid
        elif kind in {'traffic_route_ended', 'traffic_route_cancelled'}:
            if active.get(handle) == rid:
                del active[handle]
        elif kind in {'traffic_candidate_rejected', 'traffic_fairness_deferred'}:
            if not all(e.get(key) is not None for key in (*FENCES, 'task_id')):
                unbound.append({'cursor': e['cursor'], 'reason': 'task_envelope_absent',
                                'route_id': rid, 'agent': handle})
                continue
            if not valid(e, handle, rid):
                errors.append({'cursor': e['cursor'], 'reason': 'task_or_route_fence_mismatch'})
                continue
            (rejected if kind == 'traffic_candidate_rejected' else deferred)[rid] = e
        elif kind == 'traffic_wait_dependencies':
            graph, graph_event = set(map(tuple, e['edges'])), e
        elif kind == 'task_wait_cycle':
            task_cycles.append(e)
        elif kind == 'traffic_wait_cycle':
            members = e['members']
            bindings = {}
            for member in members:
                current = active.get(member)
                candidates = [x for x in (rejected.get(current), deferred.get(current))
                              if x is not None and valid(x, member, current)]
                if candidates:
                    bindings[member] = max(candidates, key=lambda x: x['cursor'])
            labels = {h: x['actor_id'] for h, x in bindings.items()}
            edges = []
            for source in members:
                for target in members:
                    if source not in labels or target not in labels or (labels[source], labels[target]) not in graph:
                        continue
                    current, other = active[source], active[target]
                    evidence = []
                    physical = rejected.get(current)
                    if physical and valid(physical, source, current):
                        for field, cause in [('body_conflicts', 'physical_body'), ('claim_conflicts', 'exclusive_claim')]:
                            conflicts = [c for c in physical.get(field, []) if c.get('owner') == target]
                            if conflicts:
                                evidence.append({'cause': cause, 'event_cursor': physical['cursor'],
                                    'age_sim_s': clock-physical['sim_time'], 'candidate_points_m': physical['points_m'],
                                    'conflicts': conflicts, 'meaning': 'latest rejected candidate, not a chosen-path snapshot'})
                    fair = deferred.get(current)
                    if fair and valid(fair, source, current) and other in fair['older_route_ids']:
                        evidence.append({'cause': 'fairness_fence', 'event_cursor': fair['cursor'],
                            'age_sim_s': clock-fair['sim_time'], 'older_route_id': other,
                            'blocked_details': fair['blocked_details'], 'candidate_points_m': fair['candidate_points_m'],
                            'meaning': 'last changed deferral for these still-active routes; not a new physical claim'})
                    edges.append({'source': labels[source], 'target': labels[target],
                                  'source_route': current, 'target_route': other, 'corroboration': evidence})
            names = set(labels.values())
            adjacency = {name: {edge['target'] for edge in edges if edge['source'] == name} for name in names}

            def reachable(start):
                found, pending = set(), [start]
                while pending:
                    node = pending.pop()
                    if node not in found:
                        found.add(node)
                        pending.extend(adjacency[node]-found)
                return found

            corroborated = (len(names) == len(members) and len(names) >= 2 and
                            all(reachable(name) == names for name in names))
            cycles.append({'reported_event': e, 'dependency_event': graph_event,
                'member_bindings': {h: {key: x[key] for key in (*FENCES, 'task_id', 'route_id')} for h, x in bindings.items()},
                'current_graph_cycle_corroborated': corroborated, 'edges': edges})
    return {'cycles': cycles, 'supervisor_task_cycle_events': task_cycles,
            'identity_errors': errors, 'unbound_candidate_events': unbound,
            'all_reported_traffic_cycles_corroborated': bool(cycles) and not errors and
                all(c['current_graph_cycle_corroborated'] for c in cycles),
            'release_gate_passed': False,
            'limits': ['Diagnostic corroboration only; no original run is regraded.',
                       'Traffic graph cycles are explained; supervisor task-cycle reports are retained separately and may describe the same actors.',
                       'Dependency edges are actual journal state; candidate/fairness evidence has explicit age and scope.',
                       'No counterfactual movement, reservation release or guarantee that a proposed escape is safe.']}


def audit(folder):
    folder = Path(folder)
    read = lambda name: json.loads((folder/name).read_text())
    if not read('completed.json')['harness_completed']:
        raise ValueError('native harness must close before diagnosis')
    cutoff = read('benchmark_done.json')['event_cursor']
    digest = hashlib.sha256()

    def events():
        needles = tuple(('"'+kind+'"').encode() for kind in KINDS)
        with (folder/'events.jsonl').open('rb') as stream:
            for line in stream:
                digest.update(line)
                if not any(needle in line[:140] for needle in needles):
                    continue
                row = json.loads(line)
                if row['cursor'] <= cutoff:
                    yield row

    result = explain(events(), read('tasks.json'), read('ready.json'))
    result.update(run_id=folder.name, journal_sha256=digest.hexdigest(), cutoff_event_cursor=cutoff,
                  original_harness_result=read('completed.json'))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    target = Path(args.output)
    if target.exists():
        raise FileExistsError('preserve prior diagnosis; choose a new output')
    result = audit(args.run)
    with target.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'run_id': result['run_id'], 'cycles': len(result['cycles']),
                     'supervisor_cycle_reports': len(result['supervisor_task_cycle_events']),
                     'all_reported_traffic_cycles_corroborated': result['all_reported_traffic_cycles_corroborated'],
                     'identity_errors': len(result['identity_errors']), 'release_gate_passed': False}))
    raise SystemExit(0 if result['all_reported_traffic_cycles_corroborated'] else 1)
