import numpy as np
import pytest
from simpeople.motion.goals import standing_upper_body_goal
from simpeople.motion.rig import forward_kinematics, world_to_local

PARENTS = [-1, 0, 1, 2, 0, 4, 0, 6, 0]
TAGS = {'LeftShoulder': 1, 'Neck1': 4, 'Head': 5, 'LeftFoot': 6, 'RightFoot': 8}


def poses():
    local = np.zeros((1, 9, 7));local[:, :, 6] = 1;local[:, :, 1] = .2;local[:, 0, :3] = [4, 2, 1]
    measured = local.copy();measured[:, 0, :3] = [-3, -5, 1.1];measured[:, 6:, :3] *= 2
    measured[:, 2, 3:] = [0, 0, np.sqrt(.5), np.sqrt(.5)]
    return forward_kinematics(local, PARENTS), forward_kinematics(measured, PARENTS)


def test_measured_goal_cannot_drag_current_feet_or_change_bone_lengths():
    source, measured = poses()
    goal, report = standing_upper_body_goal(source, measured, PARENTS, TAGS, 'left_arm')
    np.testing.assert_allclose(goal[:, [0, 6, 7, 8]], source[:, [0, 6, 7, 8]], atol=1e-10)
    np.testing.assert_allclose(world_to_local(goal, PARENTS)[:, :, :3], world_to_local(source, PARENTS)[:, :, :3], atol=1e-10)
    assert np.linalg.norm(goal[:, 3, :3] - source[:, 3, :3]) > .1
    assert report['kind'] == 'authored_standing_upper_body_goal'
    assert report['support_position_change_m'] < 1e-10


def test_bad_tag_mapping_cannot_turn_a_standing_goal_into_leg_motion():
    source, measured = poses()
    with pytest.raises(ValueError, match='supporting leg'):
        standing_upper_body_goal(source, measured, PARENTS, {**TAGS, 'LeftShoulder': 6, 'LeftLeg': 6}, 'left_arm')
    with pytest.raises(ValueError, match='required semantic'):
        standing_upper_body_goal(source, measured, PARENTS, TAGS, 'right_arm')


def test_idle_goal_retains_the_actual_pose():
    source, measured = poses()
    goal, _ = standing_upper_body_goal(source, measured, PARENTS, TAGS, 'idle')
    np.testing.assert_allclose(goal, source, atol=1e-10)
