"""Independent checks for newly enabled diagonal-tail executions.

Uses cell-boundary transition times to audit full swept ownership, rather than
the implementation's line/box intersection algorithm. Existing root/native-ID,
whole-cell trailing-plane and monotonic-removal checks remain mandatory.
"""
import argparse
import json
import math
from pathlib import Path

from audit_tail_release import audit as base_audit, actor_id


def required_footprints(points, cell, margin):
    """Enumerate all intervals on which the grid footprint is constant."""
    covered = set()
    for a, b in zip(points, points[1:]):
        changes = {0., 1.}
        for axis in [0, 1]:
            delta = b[axis] - a[axis]
            if abs(delta) < 1e-12:
                continue
            lo, hi = sorted([a[axis], b[axis]])
            for index in range(math.floor((lo-margin)/cell)-2, math.ceil((hi+margin)/cell)+3):
                boundary = (index+.5)*cell
                for offset in [-margin, margin]:
                    time = (boundary-offset-a[axis])/delta
                    if 0 < time < 1:
                        changes.add(time)
        ordered = sorted(changes)
        times = ordered + [(one+two)/2 for one, two in zip(ordered, ordered[1:])]
        for time in times:
            p = [a[i]+(b[i]-a[i])*time for i in [0, 1]]
            covered.update((x, y) for x in range(math.floor((p[0]-margin)/cell+.5), math.floor((p[0]+margin)/cell+.5)+1)
                           for y in range(math.floor((p[1]-margin)/cell+.5), math.floor((p[1]+margin)/cell+.5)+1))
    return covered


def audit(directory, expected_actor=None):
    folder = Path(directory)
    read = lambda name: json.loads((folder/name).read_text())
    base = base_audit(folder)
    cutoff = read('benchmark_done.json')['event_cursor']
    events = []
    for line in (folder/'events.jsonl').open():
        e = json.loads(line)
        if e['cursor'] <= cutoff:
            events.append(e)
    grid = next(e for e in events if e['kind'] == 'traffic_grid_ready')
    cell, margin = grid['cell_m'], grid['footprint_margin_m']
    policy = read('runtime_contract.json')['runtime_policy']
    enabled = policy.get('tail_release_enabled') is True and policy.get('diagonal_tail_release_enabled') is True
    if enabled:
        base['limits'] = [value for value in base['limits'] if not value.startswith('only same-generation')]
        base['limits'].append('Generic whole-cell/root checks reused for diagonals; initial swept coverage is additionally checked by this wrapper.')
    errors, tracks, releases = [], {}, []
    for e in events:
        if e['kind'] != 'traffic_tail_tracking' or not e['eligible']:
            continue
        points = e['points_m']
        a, b = points[0], points[-1]
        if not all(round(a[i]/cell) != round(b[i]/cell) for i in [0, 1]):
            continue
        key = e['route_id'], e['native_task_id']
        if key in tracks:
            errors.append({'cursor': e['cursor'], 'reason': 'duplicate_native_tracking'})
        tracks[key] = e
        owned = set(map(tuple, e.get('original_cells', [])))
        if e.get('diagonal_straight_enabled') is not True or not owned:
            errors.append({'cursor': e['cursor'], 'reason': 'diagonal_mode_or_initial_ownership_missing'})
        required = required_footprints(points, cell, margin)
        if not required <= owned:
            errors.append({'cursor': e['cursor'], 'reason': 'incomplete_initial_sweep', 'missing': sorted(required-owned)})
        length = math.dist(a[:2], b[:2])
        if length < 4:
            errors.append({'cursor': e['cursor'], 'reason': 'short_diagonal'})
            continue
        ux, uy = (b[0]-a[0])/length, (b[1]-a[1])/length
        previous = -math.inf
        for p in points:
            progress = (p[0]-a[0])*ux+(p[1]-a[1])*uy
            lateral = abs((p[0]-a[0])*uy-(p[1]-a[1])*ux)
            if lateral > .05 or abs(p[2]-a[2]) > .03 or progress < previous-1e-6:
                errors.append({'cursor': e['cursor'], 'reason': 'nonstraight_or_reversing_path'})
            previous = progress
    initial_seen = set()
    frozen = {(e['route_id'], e['native_task_id']): e for e in events if e['kind'] == 'traffic_tail_tracking_frozen'}
    frozen_wanted = {}
    for key, e in frozen.items():
        if key not in tracks:
            continue
        owned = set(map(tuple, e.get('remaining_cells', [])))
        root = e.get('position_m')
        if root is None or not owned:
            errors.append({'cursor': e['cursor'], 'reason': 'frozen_ownership_missing'})
            continue
        footprint = {(x, y) for x in range(math.floor((root[0]-margin)/cell+.5), math.floor((root[0]+margin)/cell+.5)+1)
                     for y in range(math.floor((root[1]-margin)/cell+.5), math.floor((root[1]+margin)/cell+.5)+1)}
        prior = [r for r in events if r['kind'] == 'traffic_tail_released'
                 and (r['route_id'], r['native_task_id']) == key and r['cursor'] < e['cursor']]
        expected = set(map(tuple, prior[-1]['remaining_cells'] if prior else tracks[key]['original_cells']))
        if not footprint <= owned or owned != expected:
            errors.append({'cursor': e['cursor'], 'reason': 'frozen_body_or_claims_not_retained'})
        if prior and e.get('body_instance_id') != prior[-1].get('body_instance_id'):
            errors.append({'cursor': e['cursor'], 'reason': 'frozen_body_generation_changed'})
        frozen_wanted[(round(e['sim_time'], 7), actor_id(e['agent']))] = e
    wanted = {}
    for e in events:
        if e['kind'] != 'traffic_tail_released':
            continue
        key = e['route_id'], e['native_task_id']
        if key not in tracks:
            continue
        if key in frozen and e['cursor'] > frozen[key]['cursor']:
            errors.append({'cursor': e['cursor'], 'reason': 'release_after_tracking_frozen'})
        if abs(e['trail_m']-2) > 1e-6:
            errors.append({'cursor': e['cursor'], 'reason': 'trailing_budget_changed'})
        if key not in initial_seen:
            initial_seen.add(key)
            claims = set(map(tuple, e['removed_cells']+e['remaining_cells']))
            if claims != set(map(tuple, tracks[key].get('original_cells', []))):
                errors.append({'cursor': e['cursor'], 'reason': 'initial_tracking_claim_mismatch'})
        releases.append(e)
        wanted[(round(e['sim_time'], 7), actor_id(e['agent']))] = e
    # The original auditor checks the supervisor's native ID. Also bind the
    # actual SDK current-action ID, session and episode at the release sample.
    matched = set()
    for line in (folder/'trajectories.jsonl').open():
        row = json.loads(line)
        key = round(row['sim_time'], 7), row['actor_id']
        if key not in wanted and key not in frozen_wanted:
            continue
        e = wanted.get(key, frozen_wanted.get(key))
        matched.add(key)
        fences = ['session_id', 'episode_id', 'control_epoch', 'actor_instance_id']
        if any(e.get(k) is None for k in fences) or str(row.get('native_task_id')) != str(e['native_task_id']) or any(row.get(k) != e.get(k) for k in fences):
            errors.append({'cursor': e['cursor'], 'reason': 'actual_sdk_task_or_world_fence_mismatch'})
        if key in frozen_wanted and (row.get('actor_instance_id') != e.get('actor_instance_id') or math.dist(row['position_m'], e['position_m']) > 1e-5):
            errors.append({'cursor': e['cursor'], 'reason': 'frozen_actual_root_or_actor_mismatch'})
    if (set(wanted)|set(frozen_wanted))-matched:
        errors.append({'reason': 'diagonal_actual_samples_missing'})
    observed = [e for e in releases if expected_actor is None or actor_id(e['agent']) == expected_actor]
    checks = enabled and base['execution_and_checks_passed'] and bool(observed) and not errors
    return {'run_id': folder.name, 'enabled': enabled, 'diagonal_tracks': len(tracks),
            'expected_actor': expected_actor, 'diagonal_release_events': len(releases),
            'frozen_native_segments': len(frozen),
            'expected_actor_release_events': len(observed), 'base_root_and_cell_audit': base,
            'additional_errors': errors, 'execution_and_checks_passed': checks,
            'functional_expected_matched': read('completed.json')['functional_expected_matched'],
            'qualification_passed': checks and read('completed.json')['functional_expected_matched'],
            'limits': ['New diagonal source/config scope only; original failed runs are not regraded.',
                       'A control with no diagonal release is unverified, not a diagonal execution pass.',
                       'Whole-cell geometry, actual SDK roots and task ownership only; no contact-force or exact mesh certification.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('directory')
    p.add_argument('--expected-actor')
    p.add_argument('--output', required=True)
    args = p.parse_args()
    target = Path(args.output)
    assert not target.exists(), 'do not overwrite a prior grade'
    result = audit(args.directory, args.expected_actor)
    target.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'base_root_and_cell_audit'}, indent=2))
    raise SystemExit(0 if result['qualification_passed'] else 1)
