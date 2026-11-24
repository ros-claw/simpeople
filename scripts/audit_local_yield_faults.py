"""Independent admission, actual SDK stop and held-claim audit of local-yield faults.

No Kit or controller imports. A censored crowd screen is never a release gate.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from audit_local_yield import FENCES, actual_window, footprint, review_admission, segment_distance

KINDS = {'traffic_native_started', 'traffic_local_yield_snapshot', 'traffic_local_yield_snapshot_unavailable',
         'traffic_local_yield_motion_observed', 'traffic_local_yield_ended', 'traffic_local_yield_brake',
         'traffic_route_cancelled', 'traffic_route_ended', 'recovery_attempt', 'step_started', 'step_ended',
         'cancel_requested', 'benchmark_fault_applied', 'prop_moved', 'traffic_obstacle_brake',
         'traffic_cancelled_yield_claim_retained', 'traffic_cancelled_yield_claim_released',
         'traffic_cancelled_yield_settlement_stale', 'traffic_wait_budget_exceeded'}


def forward_point(points, root, forward, margin, z):
    """Independent closest arc projection, preserving every corner."""
    arcs = []; length = 0.
    for a, b in zip(points, points[1:]):
        size = math.dist(a[:2], b[:2])
        if size <= 1e-9: continue
        distance, ratio = segment_distance(root, a, b)
        arcs.append((a, b, size, length, distance, ratio)); length += size
    if not arcs: raise ValueError('no actual path segment')
    nearest = min(arcs, key=lambda a: a[4]); progress = nearest[3]+nearest[2]*nearest[5]
    target = min(progress+forward, length-margin)
    if nearest[4] > .35 or not 0 <= progress < target <= length:
        raise ValueError('no valid forward point on the actual path')
    a, b, size, start, _, _ = next(a for a in arcs if a[3]+a[2] >= target)
    return [a[i]+(b[i]-a[i])*(target-start)/size for i in [0, 1]]+[z]


def stop_window(rows, end, fences):
    window, bound = actual_window(rows, end-.5, end, fences)
    if not bound or len(window) != 16 or any(r.get('action') != 'Idle' for r in window):return window, False
    return window, all(math.dist(a['position_m'][:2], b['position_m'][:2])/(b['sim_time']-a['sim_time']) < .15
                       for a, b in zip(window, window[1:]))


def gate_results(results, safety_errors, waiting_errors):
    safe = bool(results) and not safety_errors and all(r['verified'] for r in results)
    return {'qualification_passed': safe and not waiting_errors,
            'local_fault_safety_verified': safe, 'waiting_budget_verified': not waiting_errors}


def review_fault(start, phases, motions, fault, events, rows, roots_at, tasks, spec, expected):
    task = tasks[start['task_id']]; errors = []
    admission = review_admission(start, phases, roots_at, task, spec)
    errors.extend(admission['errors'])
    if 'cells' not in admission:return {'verified': False, 'errors': errors}
    rid = start['route_id']; body = admission['body']; cells = admission['cells']; points = start['points_m']
    proof = fault.get('trigger_evidence') or {}; first = motions[0] if motions else None
    current = proof.get('current', {}); fences = proof.get('release', {}).get('fences', {})
    if (first is None or proof.get('kind') != 'native_local_yield_motion'
            or first['cursor'] >= fault['cursor'] or not -1e-7 <= fault['sim_time']-first['sim_time'] <= 1/30+1e-6
            or abs(proof.get('release', {}).get('observed_sim_time', -1)-first['sim_time']) > 1e-7
            or any(current.get(k) != start.get(k) or fences.get(k) != start.get(k) for k in FENCES)
            or proof.get('release', {}).get('route_id') != rid
            or proof.get('release', {}).get('native_task_id') != start['native_task_id']
            or proof.get('release', {}).get('points_m') != points):errors.append('fault is not the first same-owned actual yield motion')
    local = current.get('local_yield', {})
    if (current.get('current_route_id') != rid or current.get('sdk_task_id') != start['native_task_id']
            or current.get('route_native_task_id') != start['native_task_id']
            or current.get('body_instance_id') != body or current.get('agent') != start['agent']
            or local.get('path_m') != points or local.get('body_generation') != body
            or local.get('native_task_id') != start['native_task_id']
            or abs(local.get('deadline_sim_time', -1)-start['sim_time']-8) > 1e-6
            or current.get('task_status') not in {'running', 'blocked'} or current.get('cancel_requested') is not False):
        errors.append('actual fault no longer owns the original live yield')
    at = next((r for r in rows if abs(r['sim_time']-fault['sim_time']) < 1e-7), None)
    if (at is None or any(at.get(k) != start.get(k) for k in FENCES)
            or at.get('native_task_id') != start['native_task_id'] or at.get('traffic_body_instance_id') != body
            or math.dist(at['position_m'], current.get('position_m', [999]*3)) > 1e-5):
        errors.append('fault lacks the same-tick original actual SDK/body sample')
    if first is not None:
        sample = next((r for r in rows if abs(r['sim_time']-first['sim_time']) < 1e-7), None)
        if (sample is None or sample.get('native_task_id') != start['native_task_id']
                or any(first.get(k) != start.get(k) for k in FENCES)
                or math.dist(sample['position_m'], first['actual_position_m']) > 1e-5
                or math.dist(points[0][:2], sample['position_m'][:2]) <= .1):
            errors.append('motion event lacks measured actual native motion')
    attempts = [e for e in events if e['kind'] == 'recovery_attempt' and e.get('task_id') == start['task_id'] and abs(e['sim_time']-start['sim_time']) < 1e-7]
    steps = [e for e in events if e['kind'] == 'step_started' and e.get('task_id') == start['task_id'] and e['sim_time'] <= start['sim_time']]
    if len(attempts) != 1 or not steps or len(task.get('recovery_attempts', [])) > 2:
        errors.append('original Engine recovery authorization/budget absent')
    else:
        step = max(steps, key=lambda e: e['cursor']); deadline = step['sim_time']+step['step'].get('timeout_s', 120)
        if abs(attempts[0]['recovery']['deadline_sim_time']-deadline) > 1e-6:errors.append('original step deadline changed')
    if any(e['kind'] == 'traffic_local_yield_snapshot' and e.get('route_id') == rid
           and e.get('phase') == 'original_goal_restored' and e['cursor'] > fault['cursor'] for e in events):
        errors.append('cancelled or failed yield restored its old goal')
    if any(e['kind'] == 'traffic_native_started' and e.get('route_id') == rid and e['cursor'] > fault['cursor'] for e in events):
        errors.append('retired route submitted another native movement')
    if fault.get('method') != expected['method']:errors.append('fault operation changed')
    release = None; stop_fences = dict(start)
    if expected['method'] == 'cancel':
        cancels = [e for e in events if e['kind'] == 'cancel_requested' and e.get('task_id') == start['task_id']
                   and abs(e['sim_time']-fault['sim_time']) < 1e-7
                   and e.get('control_epoch') == start['control_epoch']+1
                   and all(e.get(k) == start.get(k) for k in ['session_id', 'episode_id', 'actor_instance_id'])]
        stop_fences['control_epoch'] = start['control_epoch']+1
        if (len(cancels) != 1 or task.get('status') != 'cancelled' or task.get('physical_stop_verified') is not True
                or fault.get('resolved_params') != {'actor_id': start['actor_id']}):errors.append('cancel generation or physical task settlement absent')
        retained = [e for e in events if e['kind'] == 'traffic_cancelled_yield_claim_retained' and e.get('route_id') == rid]
        releases = [e for e in events if e['kind'] == 'traffic_cancelled_yield_claim_released' and e.get('route_id') == rid]
        if (len(retained) != 1 or len(releases) != 1 or abs(retained[0]['sim_time']-fault['sim_time']) > 1e-7
                or any(e.get('body_instance_id') != body or set(map(tuple, e.get('cells', []))) != cells for e in retained+releases)):
            errors.append('cancelled yield lacks exact held-claim retention/release evidence')
        else:release = releases[0]
        task_stop, valid = stop_window(rows, task.get('finished_sim_time', -1), stop_fences)
        if not valid:errors.append('cancelled task lacks actual half-second stop under the new actor epoch')
        later = [r for r in rows if r['sim_time'] >= task.get('finished_sim_time', float('inf'))
                 and all(r.get(k) == stop_fences.get(k) for k in FENCES)]
        if (not later or any(r.get('action') != 'Idle' for r in later)
                or max(math.dist(later[0]['position_m'][:2], r['position_m'][:2]) for r in later) > .15):
            errors.append('cancelled logical task resumed actual movement after settlement')
    else:
        p = expected['trigger']['placement']; point = forward_point(points, current['position_m'], p['forward_m'], p['end_margin_m'], p['z_m'])
        moved = [e for e in events if e['kind'] == 'prop_moved' and e.get('prop_id') == expected['params']['prop_id']
                 and abs(e['sim_time']-fault['sim_time']) < 1e-7 and math.dist(e['position_m'], point) < 1e-6]
        if not moved or math.dist(fault['resolved_params'].get('position_m', [999]*3), point) > 1e-6:
            errors.append('box was not placed once on the committed current polyline')
        brakes = [e for e in events if e['kind'] == 'traffic_local_yield_brake' and e.get('route_id') == rid
                  and e.get('reason') == 'dynamic_obstacle' and fault['sim_time'] <= e['sim_time'] <= fault['sim_time']+1/30+1e-6]
        ends = [e for e in events if e['kind'] == 'traffic_local_yield_ended' and e.get('route_id') == rid and e.get('status') == 'failed']
        releases = [e for e in events if e['kind'] == 'traffic_route_ended' and e.get('route_id') == rid and e.get('status') == 'failed']
        if not brakes or len(ends) != 1 or len(releases) != 1 or task.get('status') != 'failed' or task.get('error', {}).get('code') != 'BACKEND_TASK_FAILED':
            errors.append('dynamic obstacle did not produce a settled explicit yield failure')
        else:release = releases[0]
    stop_count = 0
    if release is not None:
        if release['sim_time'] <= fault['sim_time']:errors.append('claim released immediately at the moving fault')
        settled, valid = stop_window(rows, release['sim_time'], stop_fences); stop_count = len(settled)
        if not valid:errors.append('claim release lacks sixteen actual stopped SDK samples')
        all_rows = [r for r in rows if start['sim_time']-1e-7 <= r['sim_time'] <= release['sim_time']+1e-7]
        if not all_rows or any(abs(b['sim_time']-a['sim_time']-1/30) > 1e-6 for a, b in zip(all_rows, all_rows[1:])):
            errors.append('claim observation stream is discontinuous')
        for r in all_rows:
            expected_epoch = start['control_epoch'] if r['sim_time'] <= fault['sim_time']+1e-7 else stop_fences['control_epoch']
            if (any(r.get(k) != start.get(k) for k in FENCES if k != 'control_epoch') or r.get('control_epoch') != expected_epoch
                    or r.get('traffic_body_instance_id') != body or r.get('native_actor_prim_path') != start['agent']):
                errors.append('held claim stream borrowed another body/task/epoch');break
            if r['sim_time'] < release['sim_time']-1e-7 and set(map(tuple, r.get('traffic_claim_cells', []))) != cells:
                errors.append('whole yield claim not observed held until physical stop');break
            if not footprint(r['position_m'], admission['cell'], admission['margin']) <= cells:
                errors.append('actual stopping body left its held claim');break
        release_row = next((r for r in rows if abs(r['sim_time']-release['sim_time']) < 1e-7), None)
        if release_row is None or 'traffic_claim_cells' not in release_row or release_row['traffic_claim_cells']:
            errors.append('held yield claim not observed released at the measured stop')
    if any(e['kind'] == 'traffic_cancelled_yield_settlement_stale' and e.get('route_id') == rid for e in events):
        errors.append('cancel settlement ownership became stale')
    return {'actor_id': start['actor_id'], 'route_id': rid, 'task_id': start['task_id'], 'verified': not errors,
            'errors': errors, 'fault_sim_time': fault['sim_time'], 'claim_released_sim_time': release['sim_time'] if release else None,
            'actual_stop_samples': stop_count, 'actual_stop_control_epoch': stop_fences['control_epoch']}


def audit(folder):
    folder = Path(folder); read = lambda n: json.loads((folder/n).read_text()); errors = []
    completed = read('completed.json'); cutoff = read('benchmark_done.json')['event_cursor']
    if not completed['harness_completed']:raise ValueError('native run did not close')
    if not read('bootstrap.json').get('diagnostic_native_release_triggers'):errors.append('explicit diagnostic driver missing')
    for n, h in read('source_manifest.json').items():
        p = folder/'source_snapshot'/n
        if not p.resolve().is_relative_to((folder/'source_snapshot').resolve()) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != h:
            errors.append('source snapshot mismatch: '+n)
    events = []; digest = hashlib.sha256()
    for raw in (folder/'events.jsonl').open('rb'):
        digest.update(raw)
        if not any(('"'+k+'"').encode() in raw[:140] for k in KINDS):continue
        e = json.loads(raw)
        if e['cursor'] <= cutoff:events.append(e)
    case = read('workload.json'); tasks = {t['task_id']:t for t in read('tasks.json')}
    specs = {o['task_id']: next(s for s in case['requests'] if s['request_case_id'] == o['request_case_id'])
             for o in read('outcomes.json')['requests'] if o.get('task_id')}
    faults = [e for e in events if e['kind'] == 'benchmark_fault_applied']; actual = {e['event_id']: e for e in faults}
    if len(faults) != len(case['events']) or set(actual) != {e['event_id'] for e in case['events']}:errors.append('missing or duplicate actual fault: unexercised scope')
    starts = [e for e in events if e['kind'] == 'traffic_native_started' and e.get('action') == 'local_yield']
    snaps = [e for e in events if e['kind'] == 'traffic_local_yield_snapshot']; times = {round(e['sim_time'], 7) for e in snaps}
    roots_at = {t:{} for t in times}; involved = {e['actor_id'] for e in starts}
    for s in case['events']:
        if s['trigger']['kind'] == 'native_local_yield_motion':involved.add(s['trigger']['witness_actor_id'])
    rows = {a:[] for a in involved}
    for line in (folder/'trajectories.jsonl').open():
        r = json.loads(line); time = round(r['sim_time'], 7)
        if time in roots_at:roots_at[time][r['actor_id']] = r
        if r['actor_id'] in rows:rows[r['actor_id']].append(r)
    results = []
    for expected in case['events']:
        f = actual.get(expected['event_id'])
        if not f:continue
        trigger = expected['trigger']
        if trigger['kind'] == 'event_applied':
            prior = actual.get(trigger['event_id'])
            if prior is None or not trigger['delay_s']-1e-6 <= f['sim_time']-prior['sim_time'] <= trigger['delay_s']+1/30+1e-6:
                errors.append('prop clear not relative to actual entry')
            if f['resolved_params'] != expected['params'] or not any(e['kind'] == 'prop_moved' and e.get('prop_id') == expected['params']['prop_id'] and abs(e['sim_time']-f['sim_time']) < 1e-7 and e['position_m'] == expected['params']['position_m'] for e in events):errors.append('actual prop clear absent')
            continue
        selected = [e for e in starts if e['actor_id'] == trigger['actor_id'] and e['sim_time'] <= f['sim_time']]
        if len(selected) != 1:errors.append('fault not bound to exactly one original yield');continue
        start = selected[0]; rid = start['route_id']
        phases = {e['phase']:e for e in snaps if e['route_id'] == rid}
        motions = [e for e in events if e['kind'] == 'traffic_local_yield_motion_observed' and e['route_id'] == rid]
        result = review_fault(start, phases, motions, f, events, rows[start['actor_id']], roots_at, tasks, specs[start['task_id']], expected)
        w = f.get('trigger_evidence', {}).get('current', {}).get('witness', {}); task = tasks.get(w.get('task_id'), {})
        wr = [r for r in rows[trigger['witness_actor_id']] if f['sim_time']-1e-7 <= r['sim_time'] <= task.get('finished_sim_time', -1)+1e-7 and all(r.get(k) == task.get(k) for k in FENCES)]
        active = (task.get('status') == 'succeeded' and task['started_sim_time'] <= f['sim_time'] < task['finished_sim_time']
                  and w.get('status') in {'running', 'blocked'} and all(w.get(k) == task.get(k) for k in ['actor_id', 'actor_instance_id', 'task_id', 'control_epoch'])
                  and bool(wr) and abs(wr[0]['sim_time']-f['sim_time']) < 1e-6
                  and max(math.dist(wr[0]['position_m'], r['position_m']) for r in wr) > .3)
        if not active:result['errors'].append('independent witness not active, moving and successful');result['verified'] = False
        result['witness_verified'] = active;results.append(result)
    geometry = read('acceptance_summary.json')['trajectory_proxies']; runtime = read('runtime_audit.json')
    if geometry['sustained_overlap_segments'] or geometry['root_discontinuities']:errors.append('root geometry proxy regression')
    waiting_errors = ['fair waiting budget violation'] if runtime['wait_budget_violations'] else []
    if any(e['method'] == 'move_prop' and e['trigger']['kind'] == 'native_local_yield_motion' for e in case['events']):
        if not (runtime.get('dynamic_box_geometry_proxy') or {}).get('passed'):errors.append('box root/AABB guard not verified')
    recording = read('recording_metrics.json')
    if recording['frames_written'] != completed['frames'] or recording['empty_rgb_frames'] or recording['dropped_frames'] or not (folder/'raw_video.mp4').is_file():errors.append('actual continuous RGB incomplete')
    if any(e['kind'] == 'traffic_local_yield_snapshot_unavailable' for e in events):errors.append('repair snapshots incomplete')
    return {'run_id':folder.name, 'method_version':'simpeople.local-yield-fault-audit.v2',
            **gate_results(results, errors, waiting_errors),
            'errors':errors+waiting_errors, 'safety_errors':errors,
            'waiting_budget_violations':runtime['wait_budget_violations'],
            'faults':results, 'journal_sha256':digest.hexdigest(), 'cutoff_event_cursor':cutoff,
            'full_release_passed':False, 'production_source_installed':False,
            'scope':'Explicit opt-in censored local-yield fault screen, same actual body/SDK/task, retained whole claim and measured stop plus independent witness. No report-only crowd or generated-motion qualification.'}


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);a=p.parse_args();target=Path(a.output)
    if target.exists():raise FileExistsError('preserve prior grade')
    result=audit(a.run);target.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['qualification_passed'] else 1)
