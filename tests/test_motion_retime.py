import math

import numpy as np
import pytest

from simpeople.motion.retime import adaptive_retime
from simpeople.motion.rig import forward_kinematics


def fixture():
    poses = np.zeros((3, 3, 7));poses[:, :, 6] = 1
    poses[:, 1:, 0] = 1
    for i, degrees in enumerate([0, 12, 12]):
        poses[i, 1, 3:] = [0, 0, math.sin(math.radians(degrees / 2)), math.cos(math.radians(degrees / 2))]
    return poses


def test_only_fast_source_intervals_expand_and_every_original_pose_remains():
    source = fixture()
    result, proof = adaptive_retime(source, [-1, 0, 1], max_angle_deg=2, max_step_m=.1)
    assert proof['subdivisions'][0] >= 6 and proof['subdivisions'][1] == 1
    assert np.array_equal(result[proof['source_to_output_indices']], source)
    assert np.allclose(np.linalg.norm(result[:, 1:, :3], axis=-1), 1)
    assert proof['max_full_fk_angle_step_deg'] <= 2 + 1e-7


def test_local_slerp_keeps_long_bones_during_a_large_arm_turn():
    source = fixture()[:2]
    source[1, 1, 3:] = [0, 0, 1, 0]
    result, _ = adaptive_retime(source, [-1, 0, 1], max_angle_deg=5, max_step_m=.2)
    world = forward_kinematics(result, [-1, 0, 1])
    assert np.allclose(np.linalg.norm(world[:, 2, :3] - world[:, 1, :3], axis=-1), 1)


def test_antipodal_quaternion_signs_do_not_add_fake_motion():
    source = fixture()[:2];source[1] = source[0];source[1, :, 3:] *= -1
    result, proof = adaptive_retime(source, [-1, 0, 1])
    assert len(result) == 2 and proof['max_full_fk_angle_step_deg'] == 0


def test_translation_blending_cannot_hide_a_shortened_bone():
    source = fixture()[:2];source[1, 1, 0] = -1
    with pytest.raises(ValueError, match='shorten'):
        adaptive_retime(source, [-1, 0, 1], max_step_m=.1)


def test_offline_budget_is_finite_instead_of_subdividing_forever():
    with pytest.raises(ValueError, match='budget'):
        adaptive_retime(fixture(), [-1, 0, 1], max_angle_deg=.01, max_subdivisions=8)
