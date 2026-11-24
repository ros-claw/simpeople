import numpy as np
import pytest
from simpeople.motion.entry import entry_error
from simpeople.motion.rig import multiply, rotate

REFERENCE = {'world_pose': [[2, 3, 0, 0, 0, 0, 1], [2.4, 3, 1, 0, 0, 0, 1]], 'facing_direction': [0, -1, 0]}


def test_canonical_entry_follows_actor_xy_and_heading_without_hiding_pose_changes():
    pose = np.array(REFERENCE['world_pose'], dtype=float)
    q = [0, 0, np.sqrt(.5), np.sqrt(.5)]
    pose[:, :3] = rotate(q, pose[:, :3]) + [10, 5, 0]
    pose[:, 3:] = multiply(q, pose[:, 3:])
    assert entry_error(pose, [1, 0, 0], REFERENCE)['passed']
    pose[1, 2] += .04
    result = entry_error(pose, [1, 0, 0], REFERENCE)
    assert not result['passed'] and result['max_joint_position_error_m'] == pytest.approx(.04)


def test_world_height_is_not_normalized_away_for_flat_floor_profile():
    pose = np.array(REFERENCE['world_pose'], dtype=float);pose[:, 2] += .1
    result = entry_error(pose, [0, -1, 0], REFERENCE)
    assert not result['passed']
    assert result['floor_reference_error_m'] == pytest.approx(.1)


def test_invalid_facing_or_joint_rotation_cannot_pass_entry_gate():
    with pytest.raises(ValueError):entry_error(REFERENCE['world_pose'], [0, -10, 0], REFERENCE)
    pose = np.array(REFERENCE['world_pose'], dtype=float);pose[1, 3:] = 0
    with pytest.raises(ValueError):entry_error(pose, [0, -1, 0], REFERENCE)
