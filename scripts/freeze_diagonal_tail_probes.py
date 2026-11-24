"""Freeze small native diagonal-tail/fault fixtures; inputs are not acceptance."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from simpeople.core.runtime_policy import load_policy
from simpeople.core.workloads import validate_case


def cases(semantics):
    scene = {'id': 'industrial', 'revision': hashlib.sha256(json.dumps(semantics, sort_keys=True).encode()).hexdigest()}
    diagonal_end = [15.64140286443632, -14.58439003312952, 0]
    def move(point, budget):
        return {'action': 'move_to', 'target': point, 'timeout_s': budget}
    base = {'schema_version': 'simpeople.benchmark.v1', 'case_id': 'diag_tail2_v1', 'category': 'traffic',
        'scene': scene, 'submission_mode': 'open_arrival', 'busy_policy': 'reject', 'max_pending_per_actor': 2,
        'duration_s': 60, 'finite': True, 'capture_profile': 'full', 'stop_when_complete': True,
        'actors': [{'actor_id': 'lead', 'asset_id': 'default', 'spawn_anchor': [-1.25, -16.25, 0]},
                   {'actor_id': 'follower', 'asset_id': 'default', 'spawn_anchor': [-3.75, -17.5, 0]}],
        'requests': [{'request_case_id': 'lead', 'actor_id': 'lead', 'at_s': 0, 'deadline_s': 60,
                      'expected_outcome': 'succeeded', 'on_blocked': 'report',
                      'steps': [move([3.75, -16.25, 0], 20), move(diagonal_end, 30), move([20, -13.1, 0], 20)]},
                     {'request_case_id': 'follower', 'actor_id': 'follower', 'at_s': .3, 'deadline_s': 60,
                      'expected_outcome': 'succeeded', 'on_blocked': 'report',
                      'steps': [move([1.25, -16.25, 0], 30), move(diagonal_end, 35)]}]}
    result = [base]
    for name in ['cancel', 'obstacle']:
        case = copy.deepcopy(base)
        case['case_id'] = 'diag_tail_' + name + '3_v1'
        case['actors'].append({'actor_id': 'witness', 'asset_id': 'default', 'spawn_anchor': [18, 16, 0]})
        case['requests'].append({'request_case_id': 'witness', 'actor_id': 'witness', 'at_s': 0, 'deadline_s': 60,
            'expected_outcome': 'succeeded', 'on_blocked': 'report',
            'steps': [move(point, 15) for _ in range(4) for point in [[18, 18, 0], [18, 16, 0]]]})
        if name == 'cancel':
            case['category'] = 'cancellation'
            case['requests'][0].update(expected_outcome='cancelled', expected_error_code='CANCELLED', expected_physical_stop=True)
            case['events'] = [{'event_id': 'cancel_lead_after_proposed_release', 'at_s': 12,
                               'method': 'cancel', 'params': {'actor_id': 'lead'}}]
        else:
            case['requests'][0]['on_blocked'] = 'replan_or_report'
            case['events'] = [{'event_id': 'box_enters', 'at_s': 12, 'method': 'move_prop',
                               'params': {'prop_id': 'movable_box', 'position_m': [14.3, -14.77, .65]}},
                              {'event_id': 'box_clears', 'at_s': 20, 'method': 'move_prop',
                               'params': {'prop_id': 'movable_box', 'position_m': [-4, 10, .65]}}]
        result.append(case)
    for case in result:
        validate_case(case)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--semantics', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    out = Path(args.output)
    result = cases(json.loads(Path(args.semantics).read_text()))
    out.mkdir(parents=True, exist_ok=False)
    for case in result:
        (out/(case['case_id']+'.json')).write_text(json.dumps(case, indent=2)+'\n')
    policy = load_policy(ROOT/'configs')
    policy.update(tail_release_enabled=True, diagonal_tail_release_enabled=False, seat_egress_selection_enabled=False)
    (out/'axis_policy.json').write_text(json.dumps(policy, indent=2)+'\n')
    policy['diagonal_tail_release_enabled'] = True
    (out/'diagonal_policy.json').write_text(json.dumps(policy, indent=2)+'\n')
    (out/'inputs_manifest.json').write_text(json.dumps({
        'files_sha256': {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(out.glob('*.json'))},
        'scope': 'Three unexecuted small diagnostic inputs and two policies differing ONLY in diagonal_tail_release_enabled. Fixed fault times require actual release-before-fault verification. Not the600s release matrix.'}, indent=2)+'\n')


if __name__ == '__main__':
    main()
