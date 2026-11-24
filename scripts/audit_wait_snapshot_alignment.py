"""Independently align wait memory to SDK roots, Engine tasks and RGB clocks.

Does not import snapshot extraction, arbitration, navigation or Kit. A matched
snapshot diagnoses a cycle; it never qualifies traffic reliability or escape.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


FENCES = ('session_id', 'episode_id', 'actor_id', 'actor_instance_id', 'control_epoch', 'task_id')


def review(event, roots, video, spawns, tasks, bindings, report):
    snap = event['snapshot']; now = event['sim_time']; errors = []; body_unbound = []; actors = []
    def fail(reason):
        errors.append(reason)
    if (snap.get('schema_version') != 'simpeople.wait-cycle-snapshot.v1'
            or snap.get('complete_serialization') is not True
            or snap.get('nonfinite_value_paths') or snap.get('unsupported_value_paths')
            or abs(snap['sim_time']-now) > 1e-7):
        fail('snapshot schema, serialization or clock invalid')
    if report is None or report['cursor'] >= event['cursor'] or abs(report['sim_time']-now) > 1e-7 or any(
            snap['cycle'].get(k) != report.get(k) for k in ['members', 'since_sim_time', 'duration_sim_s']):
        fail('snapshot not attached to the actual same-tick cycle report')
    if video is None or abs(video['sim_time']-now) > 1e-7:
        fail('same-clock RGB frame identity missing')
    member_set = set(snap['cycle']['members']); mapping = snap['actors']; route_state = snap['active_route_state']
    tokens = [a.get('traffic_body_instance_id') for a in mapping.values()]
    if any(not isinstance(t, str) or not t for t in tokens) or len(set(tokens)) != len(tokens):
        fail('missing or duplicate traffic body generation')
    graph = {}
    for handle, row in mapping.items():
        aid = row['actor_id']; root = roots.get(aid); spawn = spawns.get(handle)
        if root is None or spawn is None:
            fail(handle+': independent actual root or spawn binding absent'); continue
        if (spawn['actor_id'] != aid or spawn['actor_instance_id'] != root.get('actor_instance_id')
                or not root.get('ready') or root.get('position_source') != 'BehaviorAgent.get_world_translation'
                or any(root.get(k) != event.get(k) for k in ['session_id', 'episode_id'])
                or abs(root['sim_time']-now) > 1e-7):
            fail(handle+': world/actor/spawn/readback mismatch')
        obs = row['observation_at_tick_start']
        numeric = [*root.get('position_m', []), *root.get('facing_direction', []), root.get('speed_mps'),
                   root.get('sim_time'), *obs.get('position_m', []), *obs.get('facing_direction', []),
                   obs.get('speed_mps'), *row.get('cached_position_m', [])]
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in numeric):
            fail(handle+': non-finite or nonnumeric independent observation'); continue
        if (obs.get('ready') is not True or not isinstance(obs.get('observation_sim_time'), (int, float))
                or not math.isfinite(obs['observation_sim_time']) or abs(obs['observation_sim_time']-now) > 1e-7
                or not all(math.isfinite(v) for v in obs['position_m'])
                or math.dist(obs['position_m'], root['position_m']) > 1e-5
                or math.dist(row['cached_position_m'], root['position_m']) > 1e-5
                or obs['native_task_id'] != root['native_task_id'] or obs['action'] != root['action']
                or abs(obs['speed_mps']-root['speed_mps']) > 1e-5
                or math.dist(obs['facing_direction'], root['facing_direction']) > 1e-5
                or obs.get('sample_frame_id') != root.get('sample_frame_id')):
            fail(handle+': tick-start observation differs from actual same-tick SDK row')
        if video is not None and root.get('frame_identity') != video.get('frame_identity'):
            fail(handle+': SDK/RGB frame identity differs')
        if 'traffic_body_instance_id' not in root or 'native_actor_prim_path' not in root:
            body_unbound.append(aid)
        elif root['traffic_body_instance_id'] != row['traffic_body_instance_id'] or root['native_actor_prim_path'] != handle:
            fail(handle+': body generation or native prim path differs across streams')
        if root.get('task_id') is not None:
            task = tasks.get(root['task_id'])
            if not task or any(task.get(k) != root.get(k) for k in FENCES):
                fail(handle+': actual row not bound to its Engine task')
        rid = row['current_route_id']
        if rid != snap['active_owner_routes'].get(handle):
            fail(handle+': snapshot owner route mismatch')
        route = route_state.get(rid)
        if rid is not None and (not route or route['handle'] != handle):
            fail(handle+': current route state missing or wrong owner')
        if handle in member_set:
            bound = bindings.get(rid)
            if not bound or any(bound.get(k) != root.get(k) for k in FENCES):
                fail(handle+': cycle route lacks same-generation task binding')
        if route and route['status'] == 'blocked':
            graph[handle] = set((route.get('blocked_details') or {}).get('blocker_handles', []))
        actors.append({'actor_id': aid, 'native_prim_path': handle, 'engine_actor_instance_id': root['actor_instance_id'],
            'traffic_body_instance_id': row['traffic_body_instance_id'], 'task_id': root.get('task_id'),
            'control_epoch': root['control_epoch'], 'route_id': rid,
            'observed_native_task_id_at_tick_start': obs['native_task_id'],
            'route_native_task_id_after_decisions': route.get('native_task_id') if route else None,
            'position_m': root['position_m']})
    if set(roots) != {r['actor_id'] for r in mapping.values()}:
        fail('snapshot actor set differs from all actual roots at this clock')
    def reachable(start):
        found = set(); todo = [start]
        while todo:
            node = todo.pop()
            if node in found: continue
            found.add(node); todo.extend((graph.get(node, set()) & member_set)-found)
        return found
    if len(member_set) < 2 or not member_set <= set(mapping) or any(reachable(h) != member_set for h in member_set):
        fail('snapshot blocked-route graph does not contain reported directed cycle')
    pending = snap['fair_gate']['pending']; sequences = []; ages = []
    for key, p in pending.items():
        actor = mapping.get(p['actor'])
        if (p['key'] != key or actor is None or p.get('occupant_token') != actor['traffic_body_instance_id']
                or not isinstance(p['since'], (int, float)) or not math.isfinite(p['since']) or p['since'] > now
                or (p['wait_since'] is not None and (not math.isfinite(p['wait_since']) or p['wait_since'] > now))):
            fail(key+': invalid pending age or occupant generation')
        sequences.append(p['sequence'])
        ages.append({'route_id': key, 'actor': p['actor'], 'priority_age_s': now-p['since'],
                     'waiting_age_s': None if p['wait_since'] is None else now-p['wait_since'],
                     'scope': p['scope'], 'state': p['state'], 'drainers': p['drainers'],
                     'origin_cells': p['origin_cells'], 'goal_cells': p['goal_cells']})
    if len(set(sequences)) != len(sequences): fail('duplicate fair-gate arrival sequence')
    refs = snap['fair_gate']['drainer_token_references']
    if set(refs) != {t for p in pending.values() for t in p['drainers']}:
        fail('drainer reference set incomplete')
    body_map = {a['traffic_body_instance_id']: h for h, a in mapping.items()}
    for token, ref in refs.items():
        if ref['kind'] == 'current_traffic_body_generation' and body_map.get(token) != ref.get('handle'):
            fail('drainer body reference rebound to wrong handle')
    return {'snapshot_cursor': event['cursor'], 'sim_time': now,
        'cycle_actor_ids': [mapping[h]['actor_id'] for h in sorted(member_set) if h in mapping],
        'errors': errors, 'actual_observations_and_engine_identity_aligned': not errors,
        'independent_body_generation_fields_missing': body_unbound,
        'snapshot_alignment_verified': not errors and not body_unbound,
        'actual_rgb_frame': video, 'actors': actors, 'pending_age_and_generation': ages,
        'scope': 'Read-only memory aligned with actual tick-start SDK observations. Post-decision route native IDs may differ intentionally. No new NavMesh edges or complete native solver restoration.'}


def audit(folder):
    folder = Path(folder); read = lambda n: json.loads((folder/n).read_text())
    if not read('completed.json')['harness_completed']: raise ValueError('native run must close')
    cutoff = read('benchmark_done.json')['event_cursor']; snapshots = []; spawns = {}; bindings = {}; report = None; absent = []
    world = read('ready.json'); source_errors = []
    for name, digest in read('source_manifest.json').items():
        rel = Path(name); path = folder/'source_snapshot'/rel
        if rel.is_absolute() or '..' in rel.parts or not path.is_file() or not path.resolve().is_relative_to((folder/'source_snapshot').resolve()):
            source_errors.append('invalid frozen source path: '+name)
        elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            source_errors.append('frozen source changed: '+name)
    digest = hashlib.sha256(); cursor = -1; clock = -math.inf
    for raw in (folder/'events.jsonl').open('rb'):
        digest.update(raw); e = json.loads(raw)
        if e['cursor'] > cutoff: continue
        if e['cursor'] <= cursor or not math.isfinite(e['sim_time']) or e['sim_time'] < clock-1e-7:
            raise ValueError('reordered native journal')
        cursor, clock = e['cursor'], e['sim_time']
        if any(e.get(k) != world[k] for k in ['session_id', 'episode_id']):
            raise ValueError('native journal world mismatch')
        if e['kind'] == 'tool_result' and e.get('method') == 'spawn' and 'error' not in e['result']:
            s = e['result']; spawns[s['prim_path']] = s
        elif e['kind'] == 'native_task_bound' and isinstance(e.get('backend_task_id'), str):
            bindings[e['backend_task_id']] = {k: e.get(k) for k in FENCES}
        elif e['kind'] == 'traffic_wait_cycle': report = e
        elif e['kind'] == 'traffic_wait_cycle_snapshot_unavailable': absent.append(e)
        elif e['kind'] == 'traffic_wait_cycle_snapshot':
            snapshots.append((e, dict(spawns), dict(bindings), report))
    times = {round(e['sim_time'], 7) for e, *_ in snapshots}; roots = {t: {} for t in times}; videos = {}; duplicates = []
    # Large trajectory streams are read once, retaining only the cycle clocks.
    for line in (folder/'trajectories.jsonl').open():
        row = json.loads(line); time = round(row['sim_time'], 7)
        if time in roots:
            if row['actor_id'] in roots[time]: duplicates.append([time, row['actor_id']])
            roots[time][row['actor_id']] = row
    for line in (folder/'video_timestamps.jsonl').open():
        row = json.loads(line); time = round(row['sim_time'], 7)
        if time in times:
            if time in videos: duplicates.append(['video', time])
            videos[time] = row
    tasks = {t['task_id']: t for t in read('tasks.json')}
    reviews = [review(e, roots[round(e['sim_time'], 7)], videos.get(round(e['sim_time'], 7)), s, tasks, b, r)
               for e, s, b, r in snapshots]
    passed = bool(reviews) and not absent and not source_errors and not duplicates and all(r['snapshot_alignment_verified'] for r in reviews)
    return {'run_id': folder.name, 'snapshot_alignment_verified': passed,
        'actual_observations_and_engine_identity_aligned': bool(reviews) and not absent and not source_errors and not duplicates
            and all(r['actual_observations_and_engine_identity_aligned'] for r in reviews),
        'snapshots': reviews, 'snapshot_unavailable': absent, 'source_errors': source_errors,
        'duplicate_clock_samples': duplicates, 'journal_sha256': digest.hexdigest(), 'cutoff_event_cursor': cutoff,
        'full_release_passed': False, 'original_harness_result': read('completed.json'),
        'limits': ['No cycle means not reproduced, never a verified snapshot.',
                   'Older roots lacking separate body-generation/prim-path fields cannot fully verify cross-stream body identity.',
                   'RGB timestamp alignment is not image segmentation, exact mesh collision or native solver-state restoration.',
                   'No claims, ages, poses, routes or previous grades are changed.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('run'); p.add_argument('--output', required=True); a = p.parse_args()
    target = Path(a.output)
    if target.exists(): raise FileExistsError('preserve prior review')
    result = audit(a.run); target.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: result[k] for k in ['run_id', 'snapshot_alignment_verified', 'actual_observations_and_engine_identity_aligned', 'full_release_passed']}))
    raise SystemExit(0 if result['snapshot_alignment_verified'] else 1)
