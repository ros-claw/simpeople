"""Offline auditor fixtures only; synthetic rows are never native evidence."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
import audit_diagonal_tail as module
from simpeople.core.tail_release import conservative_swept_cells
from simpeople.core.traffic import ReservationGrid


def test_independent_boundary_intervals_find_the_recorded_sampling_hole():
    grid = ReservationGrid(set(), {}, 1.25)
    points = [[3.7578768730163574, -16.25226593017578, 0], [15.64140286443632, -14.58439003312952, 0]]
    required = module.required_footprints(points, 1.25, .45)
    assert (10, -13) in required and (10, -13) not in grid.sweep(*points)
    assert required <= conservative_swept_cells(grid, points)


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    # Isolate the additional auditor; the original generic audit is tested in
    # its own fixtures and must pass too in real use. No SDK is imported here.
    monkeypatch.setattr(module, 'base_audit', lambda path: {
        'execution_and_checks_passed': True, 'limits': ['offline base fixture']})
    points = [[0, 0, 0], [12, 3, 0]]
    claims = sorted(conservative_swept_cells(ReservationGrid(set(), {}, 1.25), points))
    agent = '/World/SimPeople/Actors/lead/Instance_offline/Character/SkelRoot'
    events = [{'kind': 'traffic_grid_ready', 'cursor': 1, 'cell_m': 1.25, 'footprint_margin_m': .45},
              {'kind': 'traffic_tail_tracking', 'cursor': 2, 'route_id': 'r', 'native_task_id': 7,
               'eligible': True, 'diagonal_straight_enabled': True, 'points_m': points, 'original_cells': claims},
              {'kind': 'traffic_tail_released', 'cursor': 3, 'route_id': 'r', 'native_task_id': 7,
               'sim_time': 5, 'agent': agent, 'trail_m': 2., 'removed_cells': claims[:1],
               'remaining_cells': claims[1:], 'episode_id': 'offline_episode', 'session_id': 'offline_session',
               'control_epoch': 1, 'actor_instance_id': 'offline_instance', 'body_instance_id': 'offline_body'}]
    (tmp_path/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    (tmp_path/'trajectories.jsonl').write_text(json.dumps({'actor_id': 'lead', 'sim_time': 5, 'native_task_id': 7,
        'episode_id': 'offline_episode', 'session_id': 'offline_session', 'control_epoch': 1,
        'actor_instance_id': 'offline_instance'})+'\n')
    for name, data in {'benchmark_done.json': {'event_cursor': 100},
                       'runtime_contract.json': {'runtime_policy': {'tail_release_enabled': True, 'diagonal_tail_release_enabled': True}},
                       'completed.json': {'functional_expected_matched': True}}.items():
        (tmp_path/name).write_text(json.dumps(data))
    return tmp_path, events


def test_actual_sdk_task_cannot_be_replaced_by_the_supervisor_id(synthetic):
    folder, events = synthetic
    assert module.audit(folder, 'lead')['qualification_passed']
    path = folder/'trajectories.jsonl'
    row = json.loads(path.read_text())
    row['native_task_id'] = 6
    path.write_text(json.dumps(row)+'\n')
    result = module.audit(folder, 'lead')
    assert not result['qualification_passed']
    assert any(e['reason'] == 'actual_sdk_task_or_world_fence_mismatch' for e in result['additional_errors'])


def test_initial_missing_coverage_and_release_after_freeze_are_rejected(synthetic):
    folder, events = synthetic
    events[1]['original_cells'] = []
    (folder/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    result = module.audit(folder)
    assert not result['qualification_passed']
    assert any(e['reason'] == 'incomplete_initial_sweep' for e in result['additional_errors'])
    events[1]['original_cells'] = events[2]['removed_cells']+events[2]['remaining_cells']
    events.append({'kind': 'traffic_tail_tracking_frozen', 'cursor': 4, 'route_id': 'r', 'native_task_id': 7})
    events.append({**events[2], 'cursor': 5})
    (folder/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    result = module.audit(folder)
    assert not result['qualification_passed']
    assert any(e['reason'] == 'release_after_tracking_frozen' for e in result['additional_errors'])


def test_freeze_retains_real_body_and_same_ownership_without_another_release(synthetic):
    folder, events = synthetic
    root = [6, 1.5, 0]
    frozen = {**events[2], 'kind': 'traffic_tail_tracking_frozen', 'cursor': 4,
              'sim_time': 6, 'position_m': root}
    events.append(frozen)
    (folder/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    row = {'actor_id': 'lead', 'sim_time': 6, 'native_task_id': 7, 'position_m': root,
           'episode_id': 'offline_episode', 'session_id': 'offline_session', 'control_epoch': 1,
           'actor_instance_id': 'offline_instance'}
    with (folder/'trajectories.jsonl').open('a') as stream:
        stream.write(json.dumps(row)+'\n')
    assert module.audit(folder, 'lead')['qualification_passed']
    frozen['remaining_cells'] = [[100, 100]]
    (folder/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    result = module.audit(folder, 'lead')
    assert not result['qualification_passed']
    assert any(e['reason'] == 'frozen_body_or_claims_not_retained' for e in result['additional_errors'])
