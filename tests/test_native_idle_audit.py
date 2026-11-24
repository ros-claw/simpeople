"""Reject incomplete/tampered wait evidence; fixtures are not native acceptance."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'idle_auditor', Path(__file__).parents[1] / 'scripts/audit_native_idle.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

JOINTS = ['Root', 'Root/Hips']
TASK = {'actor_id': 'operator', 'actor_instance_id': 'instance-one',
        'task_id': 'owned-wait', 'status': 'succeeded'}


def samples():
    return [{'phase': 'idle_context', 'actor_id': 'operator',
             'actor_instance_id': 'instance-one', 'activity_task_id': 'owned-wait',
             'source_tick': i + 100, 'sim_time': 10 + i / 30,
             'joint_paths': list(JOINTS),
             'world_pose': [[0, 0, 0, 0, 0, 0, 1], [0, 0, 1, 0, 0, 0, 1]],
             'actual_observation': {'position_m': [0, 0, 0],
                                    'position_source': 'BehaviorAgent.get_world_translation',
                                    'planar_speed_mps': .01, 'action': 'Idle',
                                    'native_task_id': 17}}
            for i in range(61)]


def fixture(directory):
    directory.mkdir()
    files = {'completed.json': {}, 'probe_config.json': {}, 'source_manifest.json': {},
             'generated_native_acceptance.json': {
                 'passed': True, 'joint_layouts': {'operator': JOINTS},
                 'phases': [{'name': 'idle_context', 'tasks': [TASK]}]}}
    for name, value in files.items():
        (directory / name).write_text(json.dumps(value))
    events = [{'kind': 'task_accepted', 'task': TASK, 'cursor': 1, 'sim_time': 10},
              {'kind': 'task_ended', 'task': TASK, 'cursor': 5, 'sim_time': 12}]
    (directory / 'events.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
    (directory / 'native_pose_history.jsonl').write_text(
        ''.join(json.dumps(row) + '\n' for row in samples()))
    return directory


def test_exact_owned_continuous_wait_retains_all_actual_joints():
    result = audit.evaluate(samples(), TASK, JOINTS, 2)
    assert result['passed'] and result['samples'] == 61
    assert result['all_actual_joints'] == 2 and result['observed_duration_s'] == 2


@pytest.mark.parametrize('mutation,reason', [
    ('time', 'noncontinuous_simulation_samples'),
    ('tick', 'noncontinuous_source_ticks'),
    ('instance', 'actor_instance_changed'),
    ('layout', 'actual_joint_layout_changed_or_truncated'),
    ('pose', 'nonfinite_or_malformed_joint_pose'),
    ('source', 'not_actual_sdk_roots'),
    ('action', 'non_idle_action_in_wait'),
    ('task', 'different_task_inside_measurement_window'),
])
def test_tampered_native_readback_does_not_pass(mutation, reason):
    rows = samples()
    if mutation == 'time': rows[30]['sim_time'] += .01
    elif mutation == 'tick': rows[30]['source_tick'] += 1
    elif mutation == 'instance': rows[30]['actor_instance_id'] = 'another-instance'
    elif mutation == 'layout': rows[30]['world_pose'].pop()
    elif mutation == 'pose': rows[30]['world_pose'][0][0] = float('nan')
    elif mutation == 'source': rows[30]['actual_observation']['position_source'] = 'USD_static_Xform'
    elif mutation == 'action': rows[30]['actual_observation']['action'] = 'Move'
    elif mutation == 'task': rows[30]['activity_task_id'] = 'another-wait'
    result = audit.evaluate(rows, TASK, JOINTS, 2)
    assert not result['passed'] and reason in result['errors']


def test_short_or_failed_or_empty_evidence_never_qualifies():
    assert not audit.evaluate([], TASK, JOINTS, 2)['passed']
    assert not audit.evaluate(samples()[:30], TASK, JOINTS, 2)['passed']
    assert not audit.evaluate(samples(), dict(TASK, status='failed'), JOINTS, 2)['passed']
    rows = samples()
    for row in rows:
        row['joint_paths'] = []; row['world_pose'] = []
    assert not audit.evaluate(rows, TASK, [], 2)['passed']


@pytest.mark.parametrize('kind', ['drift', 'speed'])
def test_valid_measurement_can_still_fail_root_screen(kind):
    rows = samples()
    rows[30]['actual_observation']['position_m'][0] = .151 if kind == 'drift' else 0
    rows[30]['actual_observation']['planar_speed_mps'] = .15 if kind == 'speed' else .01
    result = audit.evaluate(rows, TASK, JOINTS, 2)
    assert result['valid_measurement'] and not result['passed']
    assert result['worst_' + ('displacement' if kind == 'drift' else 'speed') + '_sample']['source_tick'] == 130


def test_closed_guard_and_no_request_counterfactual_are_required(tmp_path):
    assert not audit.audit(tmp_path)['measurement_closed']
    directory = fixture(tmp_path / 'run')
    assert audit.audit(directory)['passed']
    event = {'kind': 'tool_call', 'method': 'move_to', 'params': {'actor_id': 'operator'},
             'cursor': 3, 'sim_time': 11}
    with (directory / 'events.jsonl').open('a') as f:
        f.write(json.dumps(event) + '\n')
    result = audit.audit(directory)
    assert not result['passed'] and result['new_control_requests_during_measured_wait']


def test_completed_but_failed_native_lifecycle_is_not_overall_pass(tmp_path):
    directory = fixture(tmp_path / 'run')
    path = directory / 'generated_native_acceptance.json'
    value = json.loads(path.read_text()); value['passed'] = False
    path.write_text(json.dumps(value))
    result = audit.audit(directory)
    assert result['actors']['operator']['passed']
    assert not result['passed'] and not result['native_lifecycle_passed']


@pytest.mark.parametrize('method,params', [
    ('cancel', {'task_id': 'owned-wait'}),
    ('move_prop', {'prop_id': 'box'}),
    ('signal_event', {'event': 'call_person'}),
    ('control_session', {'action': 'takeover'}),
    ('pause', {}),
])
def test_indirect_control_or_environment_changes_are_not_no_command_evidence(tmp_path, method, params):
    directory = fixture(tmp_path / 'run')
    event = {'kind': 'tool_call', 'method': method, 'params': params,
             'cursor': 3, 'sim_time': 11}
    with (directory / 'events.jsonl').open('a') as f:
        f.write(json.dumps(event) + '\n')
    result = audit.audit(directory)
    assert not result['passed']
    assert result['new_control_requests_during_measured_wait'][0]['method'] == method


@pytest.mark.parametrize('cursor,allowed', [(3, False), (6, True)])
def test_same_simulation_timestamp_uses_actual_event_order(tmp_path, cursor, allowed):
    directory = fixture(tmp_path / 'run')
    event = {'kind': 'tool_call', 'method': 'run_activity',
             'params': {'actor_id': 'operator'}, 'cursor': cursor, 'sim_time': 12}
    with (directory / 'events.jsonl').open('a') as f:
        f.write(json.dumps(event) + '\n')
    assert audit.audit(directory)['passed'] is allowed


def test_missing_event_fence_never_silently_qualifies(tmp_path):
    directory = fixture(tmp_path / 'run')
    (directory / 'events.jsonl').write_text('')
    result = audit.audit(directory)
    assert not result['passed'] and result['wait_event_fence_errors']
