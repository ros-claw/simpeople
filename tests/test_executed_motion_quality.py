import copy
import json
import math

import numpy as np
import pytest

from simpeople.motion.executed_quality import bounded_world_steps, continuous_world_goal, world_goal
from simpeople.motion.rig import multiply, rotate


def pose(joints=3):
    result = np.zeros((joints, 7))
    result[:, 6] = 1
    result[:, 2] = np.arange(joints) * .2
    return result


def rows(count=61, joints=3):
    result = []
    for i in range(count):
        result.append({'actor_id': 'a', 'actor_instance_id': 'instance', 'activity_task_id': 'task',
                       'source_tick': i, 'sim_time': i / 30, 'step_index': 0,
                       'joint_paths': ['joint' + str(j) for j in range(joints)], 'world_pose': pose(joints).tolist(),
                       'actual_observation': {'native_task_id': 5, 'facing_direction': [0, -1, 0]},
                       'task': {'actor_id': 'a', 'actor_instance_id': 'instance', 'task_id': 'task',
                                'control_epoch': 1, 'session_id': 'session', 'episode_id': 'episode', 'status': 'running'}})
    return result


def test_sixty_samples_are_short_of_two_seconds_but_sixty_one_are_enough():
    assert not continuous_world_goal(rows(60), pose())['passed']
    result = continuous_world_goal(rows(61), pose())
    assert result['passed']
    json.dumps(result, allow_nan=False)


def test_world_goal_uses_one_entry_anchor_at_a_different_position_and_heading():
    entry = rows(1)[0]
    goal = copy.deepcopy(entry)
    goal['world_pose'][2][0] = .2
    actual = copy.deepcopy(entry)
    actual['world_pose'][0][:3] = [3, 4, 0]
    actual['actual_observation']['facing_direction'] = [1, 0, 0]
    wanted = world_goal(entry, goal, actual)
    q = np.array([0, 0, math.sqrt(.5), math.sqrt(.5)])
    assert np.allclose(wanted[:, :3], rotate(q, np.array(goal['world_pose'])[:, :3]) + [3, 4, 0])


def test_a_body_turn_does_not_disappear_by_normalizing_each_live_facing():
    history = rows()
    q = np.array([0, 0, math.sqrt(.5), math.sqrt(.5)])
    for row in history:
        value = np.array(row['world_pose'])
        value[:, :3] = rotate(q, value[:, :3])
        value[:, 3:] = multiply(q, value[:, 3:])
        row['world_pose'] = value.tolist()
        row['actual_observation']['facing_direction'] = [1, 0, 0]
    assert not continuous_world_goal(history, pose())['passed']


@pytest.mark.parametrize('tamper', ['gap', 'task', 'native_task', 'instance', 'layout', 'nonfinite'])
def test_sample_gaps_and_changed_execution_bindings_are_not_a_hold(tamper):
    history = rows()
    if tamper == 'gap': history[30]['source_tick'] += 1
    if tamper == 'task': history[30]['task']['task_id'] = 'other'
    if tamper == 'native_task': history[30]['actual_observation']['native_task_id'] = 6
    if tamper == 'instance': history[30]['actor_instance_id'] = 'other'
    if tamper == 'layout': history[30]['joint_paths'].reverse()
    if tamper == 'nonfinite': history[30]['sim_time'] = float('nan')
    with pytest.raises(ValueError): continuous_world_goal(history, pose())


def test_a_late_goal_after_owned_task_end_cannot_supply_the_missing_hold_time():
    history = rows()
    for row in history[40:]: row['task']['status'] = 'succeeded'
    assert not continuous_world_goal(history, pose())['passed']


def test_an_extra_helper_joint_cannot_be_dropped_from_a_continuous_hold():
    history = rows(121, 101)
    history[60]['world_pose'][100][0] += .04
    result = continuous_world_goal(history, pose(101))
    assert result['all_actual_joints'] == 101 and not result['passed']


def test_a_leaf_rotation_jump_fails_even_when_root_and_all_positions_are_constant():
    history = rows(2)
    history[1]['world_pose'][-1][3:] = [0, 0, math.sin(math.radians(6)), math.cos(math.radians(6))]
    result = bounded_world_steps(history)
    assert not result['passed'] and result['worst_angle']['joint'] == 'joint2'


def test_quaternion_sign_changes_are_the_same_physical_rotation():
    history = rows(2)
    for p in history[1]['world_pose']: p[6] = -1
    assert bounded_world_steps(history)['passed']
