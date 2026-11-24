"""Read-only checks for an explicitly owned SDK stop diagnostic.

This is not the Engine task contract: diagnostic actors have no Engine task.
Settling and continuous motion are independent results, even for a matched entry.
"""
import math

from .executed_quality import angles
from .rig import validate_poses


IDENTITY = ('actor_id', 'actor_instance_id', 'session_id', 'episode_id',
            'control_epoch', 'native_actor_prim_path', 'traffic_body_instance_id')


def fixed_heading_error(world_pose, reference_pose):
    """Compare diagnostic actors with the same declared placement heading.

    World XY placement may differ. Animated root rotation is preserved in the
    comparison; it must not be silently removed using getFacingDirection().
    This helper performs no live correction and grants no canonical admission.
    """
    import numpy as np
    actual = validate_poses([world_pose], len(world_pose))[0]
    expected = validate_poses([reference_pose], len(world_pose))[0]
    distance = float(np.linalg.norm((actual[:, :3]-actual[0, :3])
                                    -(expected[:, :3]-expected[0, :3]), axis=-1).max())
    angle = float(angles(actual[:, 3:], expected[:, 3:]).max())
    height = float(abs(actual[0, 2]-expected[0, 2]))
    return {'max_joint_position_error_m': distance, 'max_joint_angle_error_deg': angle,
            'floor_reference_error_m': height,
            'passed': distance <= .02 and angle <= 2 and height <= .02}


def review_actor(rows, *, cancel_time, idle_requested_time, retired_id,
                 expected_idle_id, recovery_id=None, budget_s=15):
    import numpy as np
    if (not rows or any(type(v) not in (int, float) or not math.isfinite(v)
                        for v in (cancel_time, budget_s))
            or budget_s != 15
            or (idle_requested_time is None) != (expected_idle_id is None)
            or idle_requested_time is not None and (type(idle_requested_time) not in (int, float)
                or not math.isfinite(idle_requested_time) or idle_requested_time < cancel_time)
            or type(retired_id) is not int or retired_id <= 0
            or expected_idle_id is not None and (type(expected_idle_id) is not int
                or expected_idle_id <= 0 or expected_idle_id == retired_id)
            or recovery_id is not None and (type(recovery_id) is not int
                or recovery_id <= 0 or recovery_id in (retired_id, expected_idle_id))):
        raise ValueError('invalid owned SDK stop inputs')
    first = rows[0]
    identity = tuple(first.get(k) for k in IDENTITY)
    if any(v is None or v == '' for v in identity):
        raise ValueError('missing physical body or world identity')
    names = first['joint_paths']
    if not names or len(names) != len(set(names)):
        raise ValueError('invalid joint names')
    poses = validate_poses([r['world_pose'] for r in rows], len(names))
    stamps, idle = [], []
    for i, row in enumerate(rows):
        obs = row['actual_observation']; stamp = row['sim_time']
        frame = row['frame_identity']['source_tick']
        if (tuple(row.get(k) for k in IDENTITY) != identity
                or row['joint_paths'] != names or row.get('controller') != 'raw_sdk_probe_only'
                or type(frame) is not int or frame < 0
                or type(stamp) not in (int, float) or not math.isfinite(stamp)
                or obs.get('ready') is not True
                or obs.get('position_source') != 'BehaviorAgent.get_world_translation'
                or obs.get('observation_sim_time') != stamp):
            raise ValueError('SDK body, controller, sample clock or joint layout changed')
        if i and (frame != rows[i-1]['frame_identity']['source_tick']+1
                  or abs(stamp-stamps[-1]-1/30) > 1e-7):
            raise ValueError('missing or repeated actual frame')
        if row.get('retired_native_task_id') != retired_id:
            raise ValueError('retired SDK task differs')
        if recovery_id is not None and row.get('recovery_native_task_id') != recovery_id:
            # The first row was recorded just before the handoff command.
            if i or row.get('recovery_native_task_id') is not None:
                raise ValueError('recovery SDK task differs')
        stamps.append(stamp)
        speed = obs.get('speed_mps')
        okay = (idle_requested_time is not None and expected_idle_id is not None
                and stamp > idle_requested_time+1e-9
                and obs.get('action') == 'Idle' and obs.get('native_task_id') == expected_idle_id
                and row.get('expected_idle_native_id') == expected_idle_id
                and row.get('retired_native_state') in ('succeeded', 'failed', 'cancelled')
                and (recovery_id is None or row.get('recovery_native_state') in ('succeeded', 'failed', 'cancelled'))
                and type(speed) in (int, float) and math.isfinite(speed) and 0 <= speed < .15)
        if okay:
            idle.append(stamp)
        else:
            idle = []
    if len(rows) < 2 or abs(stamps[0]-cancel_time) > 1e-7:
        raise ValueError('actual pre-command cancellation boundary missing')
    distance = np.linalg.norm(np.diff(poses[:, :, :3], axis=0), axis=-1)
    angle = angles(poses[1:, :, 3:], poses[:-1, :, 3:])
    def worst(values):
        i, j = np.unravel_index(values.argmax(), values.shape)
        return {'value': float(values[i, j]), 'joint': names[j],
                'from_sim_time': stamps[i], 'to_sim_time': stamps[i+1],
                'to_source_tick': rows[i+1]['frame_identity']['source_tick']}
    duration = idle[-1]-idle[0] if idle else 0
    stopped = (len(idle) >= 16 and duration >= .5-1e-7
               and stamps[-1]-cancel_time <= budget_s+1e-7)
    continuous = bool(distance.max() <= .02 and angle.max() <= 2)
    return {'actor_id': first['actor_id'], 'actual_samples': len(rows),
            'all_actual_joints': len(names), 'actual_idle_samples': len(idle),
            'actual_idle_window_s': duration, 'actual_settlement_s': stamps[-1]-cancel_time,
            'owned_idle_request_observed': expected_idle_id is not None,
            'owned_idle_window_verified': stopped, 'world_continuity_passed': continuous,
            'worst_position_step_m': worst(distance), 'worst_angle_step_deg': worst(angle),
            'position_violating_pairs': int(np.count_nonzero(distance.max(axis=1) > .02)),
            'angle_violating_pairs': int(np.count_nonzero(angle.max(axis=1) > 2)),
            'sdk_stop_quality_verified': bool(stopped and continuous),
            'plugin_cancel_verified': False, 'generated_rig_qualified': False}
