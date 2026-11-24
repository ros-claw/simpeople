import copy
import math

import pytest

from simpeople.motion.recovery_quality import fixed_heading_error, review_actor


def sample(tick):
    return {'actor_id': 'a', 'actor_instance_id': 'body-a', 'session_id': 'session',
            'episode_id': 'episode', 'control_epoch': 0, 'native_actor_prim_path': '/a',
            'traffic_body_instance_id': 'traffic-a', 'controller': 'raw_sdk_probe_only',
            'sim_time': tick/30, 'frame_identity': {'source_tick': tick},
            'joint_paths': ['Root', 'Root/Hand'],
            'world_pose': [[0, 0, 0, 0, 0, 0, 1], [0, 0, 1, 0, 0, 0, 1]],
            'actual_observation': {'ready': True, 'observation_sim_time': tick/30,
                'position_source': 'BehaviorAgent.get_world_translation',
                'native_task_id': 3 if tick else 1, 'action': 'Idle' if tick else 'reach',
                'speed_mps': 0}, 'retired_native_task_id': 1,
            'retired_native_state': 'succeeded' if tick else 'running',
            'expected_idle_native_id': 3 if tick else None,
            'recovery_native_task_id': 2 if tick else None,
            'recovery_native_state': 'succeeded' if tick else None}


def review(rows, **kwargs):
    return review_actor(rows, cancel_time=0, idle_requested_time=0,
                        retired_id=1, expected_idle_id=3, recovery_id=2, **kwargs)


def test_actual_owned_idle_window_and_continuity_are_separate():
    rows = [sample(t) for t in range(17)]
    assert review(rows)['sdk_stop_quality_verified']
    rows[3]['world_pose'][1][0] = .03
    result = review(rows)
    assert result['owned_idle_window_verified']
    assert not result['sdk_stop_quality_verified']
    assert result['position_violating_pairs'] == 2
    assert not result['plugin_cancel_verified'] and not result['generated_rig_qualified']


def test_a_rotation_jump_alone_fails_quality():
    rows = [sample(t) for t in range(17)]
    rows[2]['world_pose'][1][3:] = [0, 0, math.sin(math.radians(3)/2), math.cos(math.radians(3)/2)]
    result = review(rows)
    assert not result['world_continuity_passed']
    assert result['angle_violating_pairs'] == 2


def test_fourteen_idle_reads_are_not_half_a_second():
    result = review([sample(t) for t in range(15)])
    assert result['world_continuity_passed'] and not result['owned_idle_window_verified']


@pytest.mark.parametrize('fault', ['instance', 'epoch', 'controller', 'clock', 'tick',
                                  'joints', 'retired', 'recovery', 'not_ready', 'nonfinite'])
def test_invalid_binding_or_observation_is_rejected(fault):
    rows = [sample(t) for t in range(17)]; row = rows[5]
    if fault == 'instance': row['traffic_body_instance_id'] = 'other'
    elif fault == 'epoch': row['control_epoch'] = 1
    elif fault == 'controller': row['controller'] = 'Engine'
    elif fault == 'clock': row['actual_observation']['observation_sim_time'] -= 1/30
    elif fault == 'tick': row['frame_identity']['source_tick'] += 1
    elif fault == 'joints': row['joint_paths'] = ['Root', 'Other']
    elif fault == 'retired': row['retired_native_task_id'] = 99
    elif fault == 'recovery': row['recovery_native_task_id'] = 99
    elif fault == 'not_ready': row['actual_observation']['ready'] = False
    elif fault == 'nonfinite': row['world_pose'][0][0] = math.nan
    with pytest.raises(ValueError): review(rows)


@pytest.mark.parametrize('fault', ['foreign_idle', 'old_running', 'recovery_running', 'fast', 'last_gap'])
def test_unsettled_exit_cannot_pass_even_with_a_true_external_flag(fault):
    rows = [sample(t) for t in range(17)]; row = rows[-1]
    if fault == 'foreign_idle': row['actual_observation']['native_task_id'] = 4
    elif fault == 'old_running': row['retired_native_state'] = 'running'
    elif fault == 'recovery_running': row['recovery_native_state'] = 'running'
    elif fault == 'fast': row['actual_observation']['speed_mps'] = .15
    elif fault == 'last_gap': row['actual_observation']['action'] = 'reach'
    assert not review(rows)['owned_idle_window_verified']


def test_original_fifteen_second_budget_is_not_extended():
    rows = [sample(t) for t in range(452)]
    assert not review(rows)['owned_idle_window_verified']
    with pytest.raises(ValueError): review(rows, budget_s=16)


def test_input_readback_is_never_repaired_or_mutated():
    rows = [sample(t) for t in range(17)]; original = copy.deepcopy(rows)
    review(rows)
    assert rows == original


def test_fixed_heading_comparison_allows_only_placement_translation():
    expected = sample(0)['world_pose']; actual = copy.deepcopy(expected)
    for p in actual: p[0] += 10; p[1] -= 5
    assert fixed_heading_error(actual, expected)['passed']
    for p in actual: p[2] += .021
    assert not fixed_heading_error(actual, expected)['passed']


def test_fixed_heading_does_not_normalize_away_an_animated_root_turn():
    expected = sample(0)['world_pose']; actual = copy.deepcopy(expected)
    q = [0, 0, math.sin(math.radians(4.5)/2), math.cos(math.radians(4.5)/2)]
    for p in actual: p[3:] = q
    result = fixed_heading_error(actual, expected)
    assert result['max_joint_angle_error_deg'] == pytest.approx(4.5)
    assert not result['passed']


def test_no_idle_request_is_measured_as_failure_without_inventing_a_receipt():
    rows = [sample(t) for t in range(17)]
    for row in rows[1:]:
        row['expected_idle_native_id'] = None
        row['actual_observation']['native_task_id'] = 0
    result = review_actor(rows, cancel_time=0, idle_requested_time=None,
                          retired_id=1, expected_idle_id=None, recovery_id=2)
    assert result['world_continuity_passed']
    assert not result['owned_idle_request_observed']
    assert result['actual_idle_samples'] == 0 and not result['sdk_stop_quality_verified']


@pytest.mark.parametrize('time,receipt', [(0, None), (None, 3)])
def test_partial_idle_request_metadata_is_invalid(time, receipt):
    with pytest.raises(ValueError):
        review_actor([sample(t) for t in range(17)], cancel_time=0,
                     idle_requested_time=time, retired_id=1, expected_idle_id=receipt, recovery_id=2)
