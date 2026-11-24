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


def rebase_phased_metadata(entry, sequence, composition):
    """Move annotations with an offline bridge while preserving the old loop.

    The new prefix belongs to ActionStart and the suffix to ActionEnd. The
    Native loop duration stays unchanged; full source duration is separate.
    This edits metadata copies only, never certifies a Native playback cursor.
    """
    import copy
    import math
    from simpeople.core.clip_quality import phase_ranges

    def integer(value, minimum=0):
        return type(value) is int and value >= minimum

    frames = entry.get('frame_count'); fps = entry.get('sample_rate')
    span = composition.get('source_range_inclusive')
    output = composition.get('output_frames')
    if (not integer(frames, 2) or type(fps) is not int or fps != 30
            or entry.get('playback_mode') != 'out_and_back'
            or sequence.get('frame_count') != frames
            or composition.get('source_frames') != frames
            or composition.get('all_original_poses_preserved_exactly') is not True
            or not integer(output, frames) or not isinstance(span, list) or len(span) != 2
            or not all(integer(x) for x in span) or span[1]-span[0]+1 != frames
            or span[1] >= output):
        raise ValueError('exact complete-source composition metadata required')
    phases = phase_ranges('out_and_back', 0, frames-1,
                          ranges=entry.get('native_phase_ranges'))
    duration = entry.get('native_loop_duration_s')
    loop_duration = (phases['ActionLoop'][1]-phases['ActionLoop'][0])/fps
    if (type(duration) not in (int, float) or not math.isfinite(duration)
            or abs(duration-loop_duration) > 1e-8):
        raise ValueError('Native loop duration differs from its phase range')
    prefix = sequence.get('prefix_frames')
    if not integer(prefix) or prefix > frames:
        raise ValueError('source prefix annotation invalid')
    annotations = {}
    for name in ('outbound', 'target_hold', 'return', 'tail'):
        values = sequence.get(name)
        if (not isinstance(values, list) or len(values) != 2
                or not all(integer(x) for x in values)
                or not 0 <= values[0] <= values[1] < frames):
            raise ValueError('source sequence annotation invalid: '+name)
        annotations[name] = values
    if annotations['tail'][1] != frames-1:
        raise ValueError('source tail must include the source endpoint')
    offset = span[0]
    rebased = {key: [a+offset, b+offset] for key, (a, b) in phases.items()}
    rebased['ActionStart'][0] = 0
    rebased['ActionEnd'][1] = output-1
    phase_ranges('out_and_back', 0, output-1, ranges=rebased)
    new_entry = copy.deepcopy(entry); new_sequence = copy.deepcopy(sequence)
    new_entry.update(frame_count=output, native_phase_ranges=rebased,
                     nominal_source_duration_s=(output-1)/fps)
    new_sequence.update(frame_count=output, prefix_frames=prefix+offset)
    for name, values in annotations.items():
        new_sequence[name] = [v+offset for v in values]
    new_sequence['tail'][1] = output-1
    provenance = {
        'source_frames': frames, 'output_frames': output,
        'source_range_inclusive': list(span),
        'source_native_phase_ranges': phases,
        'native_loop_duration_s_unchanged': duration,
        'source_native_phase_duration_s': (frames-1)/fps,
        'nominal_output_source_duration_s': (output-1)/fps,
        'scope': 'Offline annotation rebasing only; Native cursor, entry, exit and deadlines need actual verification.',
    }
    new_entry['offline_phase_rebase'] = copy.deepcopy(provenance)
    new_sequence['offline_phase_rebase'] = copy.deepcopy(provenance)
    return new_entry, new_sequence
