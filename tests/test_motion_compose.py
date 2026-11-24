import math

import numpy as np
import pytest

from simpeople.motion.compose import calibrate_entry_vectors, compose_preloaded_transition
from simpeople.motion.executed_quality import angles
from simpeople.motion.rig import forward_kinematics


def data():
    poses = np.zeros((4, 3, 7));poses[:, :, 6] = 1
    poses[:, 1:, 0] = 1
    poses[1:3, 1, 3:] = [0, 0, math.sin(.1), math.cos(.1)]
    entry = poses[:1].copy()
    entry[0, 1, 3:] = [0, 0, math.sin(-.025), math.cos(-.025)]
    return poses, entry


def test_bridges_preserve_source_and_long_bones_with_independent_fk_bounds():
    source, entry = data();parents = [-1, 0, 1]
    result, proof = compose_preloaded_transition(source, parents, entry)
    lo, hi = proof['source_range_inclusive']
    assert np.array_equal(result[lo:hi+1], source)
    assert np.array_equal(result[0], entry[0]) and np.array_equal(result[-1], entry[0])
    assert np.array_equal(result[:, 1:, :3], np.broadcast_to(source[0, 1:, :3], (len(result), 2, 3)))
    world = forward_kinematics(result, parents)
    # The middle source is untouched even if it needs its own retiming.
    for a in [world[:lo+1], world[hi:]]:
        assert angles(a[1:, :, 3:], a[:-1, :, 3:]).max() <= .75 + 1e-7
        assert np.linalg.norm(a[1:, :, :3]-a[:-1, :, :3], axis=-1).max() <= .005 + 1e-10
    assert np.allclose(np.linalg.norm(world[:, 2, :3]-world[:, 1, :3], axis=-1), 1)


def test_distinct_exit_and_root_translation_do_not_modify_inputs():
    source, entry = data();before = source.copy();exit_ = entry.copy();exit_[0, 0, 0] = .02
    result, _ = compose_preloaded_transition(source, [-1, 0, 1], entry, exit_)
    assert np.array_equal(source, before)
    assert np.array_equal(result[-1], exit_[0])


@pytest.mark.parametrize('where', ['entry', 'source'])
def test_rejects_different_bone_vectors_even_when_lengths_match(where):
    source, entry = data()
    target = entry if where == 'entry' else source
    target[-1, 1, :3] = [-1, 0, 0]
    with pytest.raises(ValueError, match='bone vectors'):
        compose_preloaded_transition(source, [-1, 0, 1], entry)


@pytest.mark.parametrize('kw', [{'hold_frames': True}, {'hold_frames': 181},
    {'max_transition_frames': 601}, {'max_transition_frames': 2.5}])
def test_bounded_offline_budgets(kw):
    source, entry = data()
    with pytest.raises(ValueError, match='bounded integer'):
        compose_preloaded_transition(source, [-1, 0, 1], entry, **kw)


def test_transition_that_exceeds_budget_is_refused():
    source, entry = data();entry[0, 1, 3:] = [0, 0, 1, 0]
    with pytest.raises(ValueError, match='budget'):
        compose_preloaded_transition(source, [-1, 0, 1], entry, max_transition_frames=2)


@pytest.mark.parametrize('parents', [[True, 0, 1], [-1, True, 1], [-1, 2, 1]])
def test_invalid_hierarchy_cannot_change_the_kinematic_chain(parents):
    source, entry = data()
    with pytest.raises(ValueError, match='skeleton'):
        compose_preloaded_transition(source, parents, entry)


def test_requires_single_entry_pose_and_finite_rotations():
    source, entry = data()
    with pytest.raises(ValueError, match='one entry'):
        compose_preloaded_transition(source, [-1, 0, 1], np.repeat(entry, 2, axis=0))
    entry[0, 0, 3] = float('nan')
    with pytest.raises(ValueError, match='finite'):
        compose_preloaded_transition(source, [-1, 0, 1], entry)


def test_existing_middle_source_translations_remain_exact_and_are_not_interpolated():
    source, entry = data();source[1, 1, 0] += .00002
    result, proof = compose_preloaded_transition(source, [-1, 0, 1], entry)
    a, b = proof['source_range_inclusive']
    assert np.array_equal(result[a:b+1], source)


def test_explicit_small_sdk_vector_calibration_preserves_rotations_and_root():
    source, entry = data();entry[0, 2, 0] += .00012;before = entry.copy()
    result, proof = calibrate_entry_vectors(entry, source[:1], [-1, 0, 1])
    assert np.array_equal(entry, before)
    assert np.array_equal(result[:, :, 3:], entry[:, :, 3:])
    assert np.array_equal(result[:, 0], entry[:, 0])
    assert proof['max_full_fk_position_change_m'] < .00013
    assert np.array_equal(result[:, 1:, :3], source[:1, 1:, :3])


@pytest.mark.parametrize('local_delta,length', [(.00026, 1), (.00012, .01)])
def test_calibration_refuses_large_absolute_or_relative_vector_change(local_delta, length):
    source, entry = data();source[:, 2, 0] = length;entry[:, 2, 0] = length + local_delta
    with pytest.raises(ValueError, match='fixed skeleton bounds'):
        calibrate_entry_vectors(entry, source[:1], [-1, 0, 1])


def test_small_local_errors_cannot_accumulate_into_large_world_adjustment():
    source, entry = data();entry[0, 1:, 0] += .0002
    # Add segments, so individually allowed errors add up to >1mm.
    source = np.concatenate([source, np.repeat(source[:, -1:], 4, axis=1)], axis=1)
    entry = np.concatenate([entry, np.repeat(entry[:, -1:], 4, axis=1)], axis=1)
    with pytest.raises(ValueError, match='world displacement'):
        calibrate_entry_vectors(entry, source[:1], [-1, 0, 1, 2, 3, 4, 5])
