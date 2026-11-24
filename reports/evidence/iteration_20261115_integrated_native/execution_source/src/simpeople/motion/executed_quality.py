"""Read-only continuous world-pose checks without an assumed native playhead."""
import math

from .rig import multiply, rotate, validate_poses


def angles(a, b):
    import numpy as np
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    return np.degrees(2 * np.arccos(np.clip(abs(np.sum(a * b, axis=-1)), 0, 1)))


def check_chain(rows):
    """Require the same owned task, native task and uninterrupted 30 Hz reads."""
    if not rows:
        raise ValueError('no actual native samples')
    def binding(row):
        task = row['task']
        values = [row['actor_id'], row['actor_instance_id'], task['session_id'], task['episode_id'],
                  task['control_epoch'], task['task_id'], row['step_index'],
                  row['actual_observation']['native_task_id']]
        if (any(v is None for v in values) or task['actor_instance_id'] != row['actor_instance_id']
                or task['actor_id'] != row['actor_id'] or row['activity_task_id'] != task['task_id']):
            raise ValueError('missing or inconsistent execution binding')
        return values
    identity = binding(rows[0])
    for i, row in enumerate(rows):
        if (row['joint_paths'] != rows[0]['joint_paths'] or len(set(row['joint_paths'])) != len(row['joint_paths'])
                or not isinstance(row['source_tick'], int) or isinstance(row['source_tick'], bool)
                or not isinstance(row['sim_time'], (int, float)) or isinstance(row['sim_time'], bool)
                or not math.isfinite(row['sim_time'])):
            raise ValueError('joint layout or actual sample clock is invalid')
        if binding(row) != identity:
            raise ValueError('execution binding changed inside clip samples')
        if i and (row['source_tick'] != rows[i - 1]['source_tick'] + 1
                  or abs(row['sim_time'] - rows[i - 1]['sim_time'] - 1 / 30) > 1e-7):
            raise ValueError('actual sample clock is not continuous 30 Hz')


def world_goal(reference_entry, reference_goal, actual_entry):
    """Anchor once at entry; never remove each later sample's root movement."""
    import numpy as np
    entry = validate_poses([reference_entry['world_pose']], len(actual_entry['world_pose']))[0]
    goal = validate_poses([reference_goal['world_pose']], len(entry))[0]
    actual = validate_poses([actual_entry['world_pose']], len(entry))[0]
    def yaw(row):
        facing = row['actual_observation']['facing_direction']
        if not np.isfinite(facing).all() or abs(math.hypot(*facing[:2]) - 1) > .001:
            raise ValueError('finite unit facing required')
        return math.atan2(facing[0], -facing[1])
    delta = yaw(actual_entry) - yaw(reference_entry)
    q = np.array([0, 0, math.sin(delta / 2), math.cos(delta / 2)])
    wanted = goal.copy()
    wanted[:, :3] = rotate(q, goal[:, :3] - entry[0, :3]) + actual[0, :3]
    wanted[:, 3:] = multiply(q, goal[:, 3:])
    return wanted


def continuous_world_goal(rows, wanted, minimum_s=2):
    import numpy as np
    check_chain(rows)
    if not math.isfinite(minimum_s) or minimum_s <= 0:
        raise ValueError('positive finite hold duration required')
    wanted = validate_poses([wanted], len(wanted))[0]
    actual = validate_poses([r['world_pose'] for r in rows], len(wanted))
    distance = np.linalg.norm(actual[:, :, :3] - wanted[:, :3], axis=-1).max(axis=-1)
    angle = angles(actual[:, :, 3:], wanted[:, 3:]).max(axis=-1)
    good = (distance <= .03) & (angle <= 5) & np.array([r['task']['status'] == 'running' for r in rows])
    edges = np.diff(np.r_[False, good, False].astype(int))
    intervals = []
    for lo, hi in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        duration = rows[hi - 1]['sim_time'] - rows[lo]['sim_time']
        intervals.append({'start_source_tick': rows[lo]['source_tick'], 'end_source_tick': rows[hi - 1]['source_tick'],
                          'start_sim_time': rows[lo]['sim_time'], 'duration_s': duration, 'samples': int(hi - lo),
                          'max_all_joint_position_error_m': float(distance[lo:hi].max()),
                          'max_all_joint_angle_error_deg': float(angle[lo:hi].max()),
                          'passed': bool(duration + 1e-7 >= minimum_s and hi - lo >= math.ceil(minimum_s * 30) + 1)})
    return {'passed': any(i['passed'] for i in intervals), 'minimum_hold_s': minimum_s,
            'all_actual_joints': len(wanted), 'actual_samples': len(rows), 'matching_intervals': intervals,
            'position_error_per_sample_m': distance.tolist(), 'angle_error_per_sample_deg': angle.tolist(),
            'scope': 'Continuous measured goal within one owned native task, fixed world anchor. No source-frame timing, nearest-pose fit or live root normalization.'}


def bounded_world_steps(rows):
    """Apply the existing seam limits to every consecutive actual clip frame."""
    import numpy as np
    check_chain(rows)
    poses = validate_poses([r['world_pose'] for r in rows], len(rows[0]['joint_paths']))
    if len(poses) < 2:
        return {'passed': False, 'reason': 'insufficient adjacent actual samples'}
    distance = np.linalg.norm(poses[1:, :, :3] - poses[:-1, :, :3], axis=-1)
    angle = angles(poses[1:, :, 3:], poses[:-1, :, 3:])
    def worst(values):
        i, j = np.unravel_index(values.argmax(), values.shape)
        return {'value': float(values[i, j]), 'joint': rows[0]['joint_paths'][j],
                'from_source_tick': rows[i]['source_tick'], 'to_source_tick': rows[i + 1]['source_tick']}
    return {'passed': bool(distance.max() <= .02 and angle.max() <= 2),
            'adjacent_pairs': len(poses) - 1, 'all_actual_joints': poses.shape[1],
            'worst_position': worst(distance), 'worst_angle': worst(angle)}
