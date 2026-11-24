"""Independent actual-SDK review of an isolated opt-in local drainage screen.

Never imports the proposal/controller and never certifies the report-only matrix.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

FENCES = ('session_id', 'episode_id', 'actor_id', 'actor_instance_id', 'control_epoch', 'task_id')
KINDS = {'traffic_native_started', 'traffic_route_started', 'native_task_bound', 'step_started', 'step_ended',
         'recovery_attempt', 'traffic_local_yield_motion_observed', 'traffic_local_yield_ended',
         'traffic_local_yield_snapshot', 'traffic_local_yield_snapshot_unavailable', 'traffic_local_yield_brake',
         'traffic_wait_budget_exceeded'}


def footprint(p, cell, margin):
    return {(x, y) for x in range(math.floor((p[0]-margin)/cell+.5), math.floor((p[0]+margin)/cell+.5)+1)
                   for y in range(math.floor((p[1]-margin)/cell+.5), math.floor((p[1]+margin)/cell+.5)+1)}


def swept_cells(points, cell, margin):
    """Closed line/expanded-box intersections, independent of controller code."""
    result = set(); extent = cell/2+margin
    for a, b in zip(points, points[1:]):
        for x in range(math.floor((min(a[0], b[0])-extent)/cell), math.ceil((max(a[0], b[0])+extent)/cell)+1):
            for y in range(math.floor((min(a[1], b[1])-extent)/cell), math.ceil((max(a[1], b[1])+extent)/cell)+1):
                lo, hi = 0., 1.
                for i, n in enumerate([x, y]):
                    d = b[i]-a[i]; low = n*cell-extent; high = n*cell+extent
                    if abs(d) < 1e-12:
                        if not low <= a[i] <= high: lo = 2.; break
                    else:
                        first, last = sorted([(low-a[i])/d, (high-a[i])/d])
                        lo, hi = max(lo, first), min(hi, last)
                if lo <= hi: result.add((x, y))
    return result


def segment_distance(p, a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]; length2 = dx*dx+dy*dy
    t = max(0., min(1., ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length2)) if length2 else 0
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy), t


def actual_window(rows, start, end, fences):
    """The same original actor/task/epoch, every actual sample, no replacement."""
    chosen = [r for r in rows if start-1e-7 <= r['sim_time'] <= end+1e-7]
    valid = (all(fences.get(k) is not None for k in FENCES) and bool(chosen)
             and abs(chosen[0]['sim_time']-start) < 1e-6 and abs(chosen[-1]['sim_time']-end) < 1e-6
             and all(r.get('ready') is True and all(r.get(k) == fences.get(k) for k in FENCES) for r in chosen)
             and all(abs(b['sim_time']-a['sim_time']-1/30) < 1e-6 for a, b in zip(chosen, chosen[1:])))
    return chosen, valid


def review_admission(start, phases, roots_at, task, spec):
    errors = []; rid = start['route_id']; handle = start['agent']; now = start['sim_time']
    if spec.get('on_blocked', 'report') != 'replan_or_report': errors.append('repair not explicitly authorized')
    if any(start.get(k) != task.get(k) or start.get(k) is None for k in FENCES): errors.append('start task identity mismatch')
    if not {'before_admission', 'native_submitted'} <= set(phases) <= {'before_admission', 'native_submitted', 'original_goal_restored'}:
        return {'errors': [*errors, 'complete repair admission snapshots absent']}
    before, submitted = [phases[k]['snapshot'] for k in ['before_admission', 'native_submitted']]
    restored = phases.get('original_goal_restored', {}).get('snapshot')
    for phase, e in phases.items():
        s = e['snapshot']
        if (s.get('schema_version') != 'simpeople.route-repair-snapshot.v1' or s.get('complete_serialization') is not True
                or s.get('nonfinite_value_paths') or s.get('unsupported_value_paths')
                or s['repair_context'] != {'agent': handle, 'route_id': rid, 'phase': phase}
                or any(e.get(k) != start.get(k) for k in FENCES) or abs(s['sim_time']-e['sim_time']) > 1e-7):
            errors.append(phase+': snapshot schema/identity invalid')
        actual = roots_at.get(round(e['sim_time'], 7), {})
        for h, a in s['actors'].items():
            r = actual.get(a['actor_id']); o = a['observation_at_tick_start']
            if (r is None or not r.get('ready') or r.get('position_source') != 'BehaviorAgent.get_world_translation'
                    or r.get('native_actor_prim_path') != h or r.get('traffic_body_instance_id') != a['traffic_body_instance_id']
                    or any(r.get(k) != start.get(k) for k in ['session_id', 'episode_id'])
                    or r.get('native_task_id') != o['native_task_id'] or r.get('action') != o['action']
                    or math.dist(r['position_m'], o['position_m']) > 1e-5
                    or math.dist(r['position_m'], a['cached_position_m']) > 1e-5
                    or abs(o['observation_sim_time']-e['sim_time']) > 1e-7):
                errors.append(phase+': actual SDK/body binding absent: '+a['actor_id'])
    original = before['active_route_state'][rid]; pending = before['fair_gate']['pending'][rid]
    body = before['actors'][handle]['traffic_body_instance_id']; data = submitted['active_route_state'][rid]['local_yield']
    points = start['points_m']; goal = original['goals'][-1]; target = points[-1]
    if body != start['body_instance_id'] or body != pending['occupant_token'] or data['body_generation'] != body:
        errors.append('body generation reused')
    if (not .5 <= math.dist(points[0][:2], target[:2]) <= 3
            or sum(math.dist(a, b) for a, b in zip(points, points[1:])) > 4
            or len(points) > 256 or data['path_m'] != points
            or abs(data['deadline_sim_time']-now-8) > 1e-6): errors.append('unbounded or mismatched yield path')
    if abs(phases['before_admission']['sim_time']-now) > 1e-7 or abs(phases['native_submitted']['sim_time']-now) > 1e-7:
        errors.append('admission snapshots not from command clock')
    keys = ['key', 'actor', 'since', 'sequence', 'wait_since', 'cells', 'goal_cells', 'drainers',
            'occupant_token', 'origin_cells', 'scope', 'state', 'conflicting_bypasses']
    for name, s in [('submitted', submitted), ('restored', restored)]:
        if s is None: continue
        p = s['fair_gate']['pending'].get(rid, {})
        if any(p.get(k) != pending.get(k) for k in keys): errors.append(name+': original priority/wait/fence changed')
    if (pending['state'] != 'waiting' or pending['wait_since'] is None or now-pending['wait_since'] < 8-1e-7
            or pending['conflicting_bypasses'] != 0): errors.append('recovery age or bypass budget invalid')
    if restored is not None and (restored['active_route_state'][rid]['goals'] != original['goals'] or restored['active_route_state'][rid]['step'] != original['step']):
        errors.append('original navigation request not restored')
    cell = before['grid']['cell_m']; margin = before['grid']['margin_m']; swept = swept_cells(points, cell, margin)
    cells = set(map(tuple, submitted['grid']['claims'].get(handle, [])))
    if before['grid']['claims'].get(handle) or not swept <= cells or cells != set(map(tuple, start['reserved_cells'])):
        errors.append('whole conservative claim absent or former claim silently released')
    foreign = set().union(*(set(map(tuple, v)) for h, v in before['grid']['claims'].items() if h != handle))
    if cells & foreign: errors.append('foreign exclusive claim bypassed')
    order = lambda p: (p['since'], p['sequence'], p['actor'])
    drained = []
    for old_id, old in before['fair_gate']['pending'].items():
        old_cells = set(map(tuple, old['cells']))
        if old_id == rid or order(old) >= order(pending) or not old_cells & cells: continue
        if (body not in old['drainers'] or not footprint(points[0], cell, margin) & old_cells
                or footprint(target, cell, margin) & old_cells): errors.append('not a preexisting body leaving ALL older fences')
        drained.append(old_id)
    if not drained: errors.append('no older fence drained')
    for h, a in before['actors'].items():
        if h == handle: continue
        p = a['cached_position_m']
        for first, last in zip(points, points[1:]):
            distance, t = segment_distance(p, first, last)
            if distance < .9 and (t > 1e-6 or math.dist(p[:2], last[:2]) <= math.dist(p[:2], first[:2])+.05):
                errors.append('ordinary .9m planning clearance bypassed'); break
    return dict(errors=errors, rid=rid, handle=handle, now=now, body=body, points=points, goal=goal, target=target,
                cell=cell, margin=margin, cells=cells, drained=drained, original=original)


def review(start, phases, motion, end, rows, roots_at, events, task, spec):
    if set(phases) != {'before_admission', 'native_submitted', 'original_goal_restored'}:
        return {'route_id': start['route_id'], 'verified': False, 'errors': ['complete repair snapshots absent']}
    admission = review_admission(start, phases, roots_at, task, spec)
    errors = admission['errors']; rid = admission['rid']; handle = admission['handle']; now = admission['now']
    body = admission['body']; points = admission['points']; goal = admission['goal']; target = admission['target']
    cells = admission['cells']; cell = admission['cell']; margin = admission['margin']; drained = admission['drained']
    original = admission['original']
    if end is None or end['status'] != 'succeeded' or not motion:
        return {'route_id': rid, 'verified': False, 'errors': [*errors, 'actual yield success/motion not observed']}
    if any(e['kind'] == 'traffic_wait_budget_exceeded' and e.get('route_id') == rid for e in events):
        errors.append('original route waiting budget exceeded')
    stop = end['sim_time']; window, bound = actual_window(rows, now, stop, start)
    if not bound: errors.append('original task/world/actor epoch or continuous 30Hz reads lost')
    if any(end.get(k) != start.get(k) for k in FENCES) or end.get('agent') != handle:
        errors.append('yield end bound to another task or actor')
    for e in motion:
        at = next((r for r in window if abs(r['sim_time']-e['sim_time']) < 1e-7), None)
        if (at is None or any(e.get(k) != start.get(k) for k in FENCES)
                or e.get('native_task_id') != start['native_task_id'] or e.get('agent') != handle
                or math.dist(at['position_m'], e['actual_position_m']) > 1e-5
                or at['native_task_id'] != start['native_task_id']):
            errors.append('motion event not bound to actual same-SDK/body readback')
    native_rows = [r for r in window if r['native_task_id'] == start['native_task_id']]
    if not native_rows or max((math.dist(points[0][:2], r['position_m'][:2]) for r in native_rows), default=0) <= .1:
        errors.append('native subtask label lacks measured motion')
    for r in window:
        p = r['position_m']
        if r.get('traffic_body_instance_id') != body or r.get('native_actor_prim_path') != handle:
            errors.append('body generation changed during yield'); break
        if (not footprint(p, cell, margin) <= cells or abs(p[2]-points[0][2]) > .1
                or min(segment_distance(p, a, b)[0] for a, b in zip(points, points[1:])) > .35):
            errors.append('actual root left protected path'); break
        if r.get('requested_step', {}).get('target') != original['step']['target']:
            errors.append('logical requested target changed during temporary navigation'); break
    settled, full = actual_window(rows, stop-.5, stop, start)
    speeds = [math.dist(a['position_m'][:2], b['position_m'][:2])/(b['sim_time']-a['sim_time']) for a, b in zip(settled, settled[1:])]
    if (not full or len(settled) != 16 or max(speeds, default=999) >= .15
            or any(r.get('action') != 'Idle' or math.dist(r['position_m'][:2], target[:2]) > .3 for r in settled)):
        errors.append('yield claim release lacks actual half-second settlement')
    before = phases['before_admission']['snapshot']
    if any(footprint(r['position_m'], cell, margin) & set(map(tuple, before['fair_gate']['pending'][old]['cells']))
           for r in settled for old in drained):
        errors.append('actual settled body has not left every older protected fence')
    attempts = [e for e in events if e['kind'] == 'recovery_attempt' and e.get('task_id') == start['task_id']
                and abs(e['sim_time']-now) < 1e-7]
    step_starts = [e for e in events if e['kind'] == 'step_started' and e.get('task_id') == start['task_id'] and e['sim_time'] <= now]
    step = max(step_starts, key=lambda e: e['cursor']) if step_starts else None
    if len(attempts) != 1 or step is None:
        errors.append('Engine opt-in recovery authorization not found'); deadline = None
    else:
        deadline = step['sim_time']+step['step'].get('timeout_s', 120)
        if (abs(attempts[0]['recovery']['deadline_sim_time']-deadline) > 1e-6 or len(task['recovery_attempts']) > 2
                or attempts[0]['recovery']['result'].get('strategy') != 'bounded_local_yield_then_original_goal'):
            errors.append('Engine original deadline/recovery budget changed')
    goals = [e for e in events if e['kind'] == 'step_ended' and e.get('task_id') == start['task_id']
             and step is not None and e['index'] == step['index'] and e['sim_time'] > stop]
    completed = goals[0] if goals else None
    if completed:
        at = next((r for r in rows if abs(r['sim_time']-completed['sim_time']) < 1e-7), None)
        if (at is None or any(at.get(k) != start.get(k) for k in FENCES)
                or math.dist(at['position_m'][:2], goal[:2]) > .3 or at['speed_mps'] >= .15
                or completed['sim_time'] > deadline): errors.append('original goal completion not bound to actual root/deadline')
    else: errors.append('original move goal not completed after restoring it')
    return {'route_id': rid, 'actor_id': start['actor_id'], 'task_id': start['task_id'], 'verified': not errors,
            'errors': errors, 'started_sim_time': now, 'yield_settled_sim_time': stop,
            'temporary_target_m': target, 'original_goal_m': goal,
            'original_goal_completed_sim_time': completed['sim_time'] if completed else None,
            'original_step_deadline_sim_time': deadline, 'drained_older_fences': drained,
            'actual_native_motion_samples': len(native_rows), 'actual_settlement_samples': len(settled)}


def audit(folder):
    folder = Path(folder); read = lambda n: json.loads((folder/n).read_text()); errors = []
    if not read('completed.json')['harness_completed']: raise ValueError('native harness must close')
    cutoff = read('benchmark_done.json')['event_cursor']; digest = hashlib.sha256(); events = []
    for name, expected in read('source_manifest.json').items():
        rel = Path(name); f = folder/'source_snapshot'/rel
        if rel.is_absolute() or '..' in rel.parts or not f.is_file() or not f.resolve().is_relative_to((folder/'source_snapshot').resolve()) or hashlib.sha256(f.read_bytes()).hexdigest() != expected:
            errors.append('frozen source mismatch: '+name)
    for raw in (folder/'events.jsonl').open('rb'):
        digest.update(raw)
        if not any(('"'+k+'"').encode() in raw[:140] for k in KINDS): continue
        e = json.loads(raw)
        if e['cursor'] <= cutoff: events.append(e)
    starts = [e for e in events if e['kind'] == 'traffic_native_started' and e.get('action') == 'local_yield']
    snapshots = [e for e in events if e['kind'] == 'traffic_local_yield_snapshot']; times = {round(e['sim_time'], 7) for e in snapshots}
    actors = {e['actor_id'] for e in starts}; roots_at = {t: {} for t in times}; rows = {a: [] for a in actors}
    if starts:
        for line in (folder/'trajectories.jsonl').open():
            r = json.loads(line); time = round(r['sim_time'], 7)
            if time in roots_at: roots_at[time][r['actor_id']] = r
            if r['actor_id'] in rows: rows[r['actor_id']].append(r)
    tasks = {t['task_id']: t for t in read('tasks.json')}; case = read('workload.json')
    specs = {r['task_id']: next(s for s in case['requests'] if s['request_case_id'] == r['request_case_id'])
             for r in read('outcomes.json')['requests'] if r.get('task_id')}
    results = []
    for start in starts:
        rid = start['route_id']; phases = {e['phase']: e for e in snapshots if e['route_id'] == rid}
        motion = [e for e in events if e['kind'] == 'traffic_local_yield_motion_observed' and e['route_id'] == rid]
        ended = [e for e in events if e['kind'] == 'traffic_local_yield_ended' and e['route_id'] == rid]
        results.append(review(start, phases, motion, ended[0] if ended else None, rows[start['actor_id']], roots_at,
                              events, tasks[start['task_id']], specs[start['task_id']]))
    if any(e['kind'] == 'traffic_local_yield_snapshot_unavailable' for e in events): errors.append('repair snapshot unavailable')
    if any(len(t.get('recovery_attempts', [])) > 2 for t in tasks.values()): errors.append('logical recovery budget exceeded')
    geometry = read('acceptance_summary.json')['trajectory_proxies']
    if geometry['sustained_overlap_segments'] or geometry['root_discontinuities']: errors.append('actual root geometry regression')
    recording = read('recording_metrics.json'); completed = read('completed.json')
    if (recording['frames_written'] != completed['frames'] or recording['empty_rgb_frames'] or recording['dropped_frames']
            or not (folder/'raw_video.mp4').is_file()): errors.append('continuous actual RGB capture incomplete')
    config = read('source_snapshot/configs/runtime_policy.json'); enabled = config.get('cycle_drainage_enabled', False)
    if starts and not enabled: errors.append('local yield executed with default-OFF policy')
    return {'run_id': folder.name, 'method_version': 'simpeople.local-yield-native-screen.v3',
            'execution_observed': bool(starts), 'isolated_optin_yield_screen_passed': bool(results) and not errors and all(r['verified'] for r in results),
            'disabled_control_contract_passed': not enabled and not starts and not errors,
            'errors': errors, 'yields': results, 'journal_sha256': digest.hexdigest(), 'cutoff_event_cursor': cutoff,
            'full_release_passed': False, 'production_source_installed': False,
            'scope': 'Explicit opt-in recovery ONLY, actual original move goal, same task/epoch/body, whole initial claim/root path and old ticket/budget/stop checks. No report-only matrix, all activity cycles, exact mesh/contact or performance qualification.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('run'); p.add_argument('--output', required=True); a = p.parse_args(); target = Path(a.output)
    if target.exists(): raise FileExistsError('preserve prior grade')
    result = audit(a.run); target.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: result[k] for k in ['run_id', 'execution_observed', 'isolated_optin_yield_screen_passed', 'disabled_control_contract_passed', 'errors']}))
    raise SystemExit(0 if result['isolated_optin_yield_screen_passed'] or result['disabled_control_contract_passed'] else 1)
