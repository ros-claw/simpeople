"""Offline entry/exit bridges for preloaded clips; never writes a live actor."""
from .rig import validate_poses
from .retime import adaptive_retime


def _validate_hierarchy(parents):
    if (not parents or parents[0] != -1 or isinstance(parents[0], bool)
        or any(isinstance(p, bool) or not isinstance(p, int) or not 0 <= p < i
               for i, p in enumerate(parents[1:], 1))):
        raise ValueError('one ordered skeleton required')


def calibrate_entry_vectors(pose, reference, parents):
    """Explicit offline submillimetre SDK calibration onto a fixed skeleton.

    Rotations and root translation remain exact. Refuse changes above 0.25mm
    per local vector, 0.5% of its length, or 1mm in any resulting FK position.
    The receipt must accompany the derivative; it is not an observed pose.
    """
    import numpy as np
    from .rig import forward_kinematics
    _validate_hierarchy(parents)
    source = validate_poses(pose, len(parents))
    target = validate_poses(reference, len(parents))
    if len(source) != 1 or len(target) != 1:
        raise ValueError('one measured and one reference pose required')
    change = np.linalg.norm(source[0, 1:, :3] - target[0, 1:, :3], axis=-1)
    relative = change / np.maximum(np.linalg.norm(target[0, 1:, :3], axis=-1), 1e-9)
    if change.max(initial=0) > .00025 or relative.max(initial=0) > .005:
        raise ValueError('entry vector calibration exceeds fixed skeleton bounds')
    calibrated = source.copy();calibrated[:, 1:, :3] = target[:, 1:, :3]
    world = forward_kinematics(np.concatenate([source, calibrated]), parents)
    maximum = float(np.linalg.norm(world[1, :, :3] - world[0, :, :3], axis=-1).max())
    if maximum > .001:
        raise ValueError('entry vector calibration exceeds world displacement bound')
    return calibrated, {
        'max_local_vector_change_m': float(change.max(initial=0)),
        'max_relative_vector_change': float(relative.max(initial=0)),
        'max_full_fk_position_change_m': maximum,
        'rotations_and_root_translation_unchanged': True,
        'scope': 'Offline fixed-skeleton derivative only, never an actual readback or live correction.',
    }


def compose_preloaded_transition(poses, parents, entry_pose, exit_pose=None,
                                 hold_frames=60, max_transition_frames=300):
    """Keep the complete source and bridge from/to separately measured poses.

    Bridge endpoint bone vectors must already match the source endpoints.
    Only root translation and local rotations can interpolate. The returned
    provenance describes authored data, not native playback or contact quality.
    """
    import numpy as np
    for name, value, lower, upper in [
        ('hold_frames', hold_frames, 4, 180),
        ('max_transition_frames', max_transition_frames, 2, 600),
    ]:
        if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
            raise ValueError('bounded integer required: ' + name)
    _validate_hierarchy(parents)
    source = validate_poses(poses, len(parents))
    if len(source) < 2:
        raise ValueError('a complete source clip is required')
    entry = validate_poses(entry_pose, len(parents))
    exit_ = validate_poses(entry_pose if exit_pose is None else exit_pose, len(parents))
    if len(entry) != 1 or len(exit_) != 1:
        raise ValueError('one entry and one exit pose required')
    if any(not np.allclose(a[0, 1:, :3], b[0, 1:, :3], atol=1e-6, rtol=0)
           for a, b in [(entry, source[:1]), (exit_, source[-1:])]):
        raise ValueError('local bone vectors differ; explicit rig calibration required')
    # Do not blend two positions in world space or normalize altered bone lengths.
    # Roundoff within the checked bound is retained; the original clip is exact.
    incoming, incoming_proof = adaptive_retime(
        np.concatenate([entry, source[:1]]), parents,
        max_output_frames=max_transition_frames)
    outgoing, outgoing_proof = adaptive_retime(
        np.concatenate([source[-1:], exit_]), parents,
        max_output_frames=max_transition_frames)
    start = hold_frames + len(incoming) - 1
    result = np.concatenate([
        np.repeat(entry, hold_frames, axis=0), incoming[:-1], source,
        outgoing[1:], np.repeat(exit_, hold_frames, axis=0),
    ])
    assert np.array_equal(result[start:start + len(source)], source)
    return result, {
        'method_version': 'simpeople.offline-preloaded-boundary-bridges.v1',
        'source_frames': len(source), 'output_frames': len(result),
        'source_range_inclusive': [start, start + len(source) - 1],
        'hold_frames': hold_frames,
        'incoming': incoming_proof, 'outgoing': outgoing_proof,
        'all_original_poses_preserved_exactly': True,
        'scope': 'Offline authored bridges only. Actual entry/exit, all-frame world '
                 'steps, target hold and feet still require independent Native verification.',
    }
