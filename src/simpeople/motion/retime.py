"""Offline adaptive local-rotation retiming, preserving every source pose."""
import math

from .executed_quality import angles
from .rig import forward_kinematics, validate_poses


def interpolate_local(first, last, fractions):
    import numpy as np
    first = np.asarray(first);last = np.asarray(last)
    qa = first[:, 3:] / np.linalg.norm(first[:, 3:], axis=-1, keepdims=True)
    qb = last[:, 3:] / np.linalg.norm(last[:, 3:], axis=-1, keepdims=True)
    dot = np.sum(qa * qb, axis=-1)
    qb = np.where((dot < 0)[:, None], -qb, qb)
    theta = np.arccos(np.clip(abs(dot), 0, 1))
    small = theta < 1e-7
    denominator = np.where(small, 1, np.sin(theta))
    result = []
    for t in fractions:
        value = first * (1 - t) + last * t
        q = (np.sin((1 - t) * theta)[:, None] * qa + np.sin(t * theta)[:, None] * qb) / denominator[:, None]
        q[small] = (1 - t) * qa[small] + t * qb[small]
        value[:, 3:] = q / np.linalg.norm(q, axis=-1, keepdims=True)
        result.append(value)
    return np.array(result)


def adaptive_retime(poses, parents, max_angle_deg=.75, max_step_m=.005,
                    max_subdivisions=256, max_output_frames=2000):
    """Insert local SLERP samples; no filtering, dropped bones or live writes.

    Bounds are checked again in full FK, including helper and finger joints.
    The length check refuses source translations whose linear interpolation
    would shorten a bone, rather than treating XYZ blending as a pose solver.
    """
    import numpy as np
    if (not parents or parents[0] != -1 or any(not isinstance(p, int) or not 0 <= p < i for i, p in enumerate(parents[1:], 1))
            or not math.isfinite(max_angle_deg) or max_angle_deg <= 0
            or not math.isfinite(max_step_m) or max_step_m <= 0):
        raise ValueError('valid hierarchy and positive finite retiming bounds required')
    source = validate_poses(poses, len(parents))
    if len(source) < 2:
        raise ValueError('at least two source poses required')
    output = [source[0].copy()];mapping = [0];subdivisions = []
    for first, last in zip(source, source[1:]):
        local_angles = angles(first[:, 3:], last[:, 3:]);chain_angles = local_angles.copy()
        for i, parent in enumerate(parents[1:], 1):chain_angles[i] += chain_angles[parent]
        world = forward_kinematics(np.array([first, last]), parents)
        distance = float(np.linalg.norm(world[1, :, :3] - world[0, :, :3], axis=-1).max())
        count = max(1, math.ceil(float(chain_angles.max()) / max_angle_deg), math.ceil(distance / max_step_m))
        while True:
            if count > max_subdivisions or len(output) + count > max_output_frames:
                raise ValueError('retiming exceeds the frozen offline subdivision/frame budget')
            segment = interpolate_local(first, last, np.linspace(0, 1, count + 1))
            segment[0] = first;segment[-1] = last
            lengths = np.linalg.norm(segment[:, 1:, :3], axis=-1)
            expected_lengths = ((1 - np.linspace(0, 1, count + 1)[:, None]) * np.linalg.norm(first[1:, :3], axis=-1)
                                + np.linspace(0, 1, count + 1)[:, None] * np.linalg.norm(last[1:, :3], axis=-1))
            if np.any(abs(lengths - expected_lengths) > np.maximum(1e-6, expected_lengths * .001)):
                raise ValueError('local translation interpolation would shorten a bone')
            fk = forward_kinematics(segment, parents)
            position_step = np.linalg.norm(fk[1:, :, :3] - fk[:-1, :, :3], axis=-1).max()
            angular_step = angles(fk[1:, :, 3:], fk[:-1, :, 3:]).max()
            if position_step <= max_step_m + 1e-10 and angular_step <= max_angle_deg + 1e-7:
                break
            count *= 2
        output.extend(segment[1:]);mapping.append(len(output) - 1);subdivisions.append(count)
    result = validate_poses(np.array(output), len(parents))
    assert np.array_equal(result[mapping], source)
    fk = forward_kinematics(result, parents)
    return result, {'source_frames': len(source), 'retimed_frames': len(result), 'all_joints': len(parents),
                    'requested_max_full_fk_angle_step_deg': max_angle_deg, 'requested_max_full_fk_position_step_m': max_step_m,
                    'source_to_output_indices': mapping, 'subdivisions': subdivisions,
                    'all_original_poses_preserved_exactly': True,
                    'max_full_fk_position_step_m': float(np.linalg.norm(fk[1:, :, :3] - fk[:-1, :, :3], axis=-1).max()),
                    'max_full_fk_angle_step_deg': float(angles(fk[1:, :, 3:], fk[:-1, :, 3:]).max()),
                    'scope': 'Offline source animation retiming only. No video interpolation, native acceptance, live pose writes, endpoint correction or foot-contact certificate.'}
