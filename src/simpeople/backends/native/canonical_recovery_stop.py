"""Opt-in preloaded stop experiment; only Behavior writes the live skeleton.

Entries are measured against the actual SDK body. A neutral target is anchored
once at cancellation, never refitted to later frames. This does not generate or
register clips during Play and is not a general cancellation capability claim.
"""
import math


def capture(backend, handle, agent, names):
    import carb
    from pxr import Usd, UsdSkel
    skeleton = next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(backend.stage.GetPrimAtPath(handle))
                    if p.IsA(UsdSkel.Skeleton))
    if list(map(str, skeleton.GetJointsAttr().Get())) != names:
        raise ValueError('recovery joint layout differs from actual body')
    pose = []
    for index in range(len(names)):
        point = carb.Float3(0, 0, 0); rotation = carb.Float4(0, 0, 0, 1)
        if not agent.get_joint_world_transform(index, point, rotation):
            raise ValueError('recovery joint readback unavailable')
        pose.append([*backend.to_public(point), rotation.x, rotation.y, rotation.z, rotation.w])
    return pose


def request(backend, handle, entry, current, name, agent):
    backend.assert_thread()
    if not getattr(backend, 'canonical_recovery_stop_probe_enabled', False):
        return False
    instance = backend.instances[handle]; generation = instance.get('traffic_instance_id')
    if (not entry.get('canonical_entry') or entry.get('entry_base_action') != 'Idle'
            or type(current) is not int or current <= 0
            or current not in instance.get('engine_native_ids', [])
            or agent.get_action_task_id() != current or agent.get_task_name(current) != name
            or not isinstance(generation, str) or not generation):
        return False
    if instance.get('custom_stop'):
        return True
    asset = next(a for a in backend.assets if a['asset_id'] == instance['asset_id'])
    candidates = [(n, e) for n, e in backend.custom_actions.items()
                  if e.get('internal_stop_recovery') is True and e.get('source_goal_clip') == name
                  and e.get('stop_source_asset_sha256') == asset['content_hash']
                  and e.get('status') != 'unsupported']
    if not candidates:
        return False
    from simpeople.motion.recovery_quality import fixed_heading_error
    from simpeople.motion.executed_quality import world_goal
    pose = capture(backend, handle, agent, candidates[0][1]['stop_joint_paths'])
    choices = []
    for recovery_name, recovery in candidates:
        if recovery['stop_joint_paths'] != candidates[0][1]['stop_joint_paths']:
            continue
        error = fixed_heading_error(pose, recovery['stop_entry_world_pose'])
        if error['passed']:
            choices.append((error['max_joint_position_error_m'], error['max_joint_angle_error_deg'],
                            recovery_name, recovery, error))
    if not choices:
        return False  # Unmatched phases retain the existing, honestly unqualified stop.
    _, _, recovery_name, recovery, error = min(choices, key=lambda row: row[:3])
    observation = backend.observe(handle)
    if (not observation.get('ready') or observation.get('observation_sim_time') != backend.timeline.get_current_time()
            or observation.get('native_task_id') != current):
        return False
    target = world_goal(recovery['stop_entry_reference'], recovery['stop_neutral_reference'],
                        dict(world_pose=pose, actual_observation=observation)).tolist()
    record = dict(retired_native_task_id=current, clip=name,
                  requested_sim_time=backend.timeline.get_current_time(), actual_idle_times=[],
                  canonical_recovery_stop=True, body_generation=generation,
                  idle_request_native_task_id=None, recovery_name=recovery_name,
                  recovery_joint_paths=recovery['stop_joint_paths'], recovery_target_world_pose=target,
                  recovery_neutral_times=[], entry_error=error, phase='recovery_requested')
    instance['custom_stop'] = record
    # Replacement is one SDK action command. Cancelling the old clip first
    # would insert an unrelated Idle before the measured recovery entry.
    receipt = agent.custom_action(recovery_name, duration=14.)
    if type(receipt) is not int or receipt <= 0 or receipt == current:
        raise ValueError('recovery task requires a distinct positive SDK receipt')
    record['recovery_native_task_id'] = receipt
    known = instance.setdefault('engine_native_ids', []); known.append(receipt); del known[:-32]
    if backend.on_event:
        backend.on_event('native_custom_stop_requested', agent=handle, **record)
    return True


def advance(backend, handle, record, observation, agent):
    backend.assert_thread()
    instance = backend.instances.get(handle, {})
    now = backend.timeline.get_current_time(); requested = record['requested_sim_time']
    if (not record.get('body_generation') or instance.get('traffic_instance_id') != record['body_generation']
            or type(now) not in (int, float) or not math.isfinite(now)
            or not requested+1e-9 < now <= requested+15+1e-7
            or observation.get('observation_sim_time') != now or not observation.get('ready')
            or agent is None or observation.get('native_task_id') != agent.get_action_task_id()):
        return False
    recovery_id = record.get('recovery_native_task_id')
    if type(recovery_id) is not int or recovery_id <= 0:
        return False
    expected = record.get('idle_request_native_task_id')
    if expected is not None:
        return backend.task_state(handle, recovery_id) != 'running'
    if record.get('idle_request_failed'):
        return False
    current = observation['native_task_id']
    if current != recovery_id and not (current == 0 and backend.task_state(handle, recovery_id) != 'running'):
        return False  # Never commandeer a later SDK owner.
    if backend.task_state(handle, record['retired_native_task_id']) == 'running':
        return False
    import numpy as np
    from simpeople.motion.executed_quality import angles
    pose = np.asarray(capture(backend, handle, agent, record['recovery_joint_paths']))
    target = np.asarray(record['recovery_target_world_pose'])
    distance = float(np.linalg.norm(pose[:, :3]-target[:, :3], axis=-1).max())
    angle = float(angles(pose[:, 3:], target[:, 3:]).max())
    times = record['recovery_neutral_times']; speed = observation.get('speed_mps')
    quiet = type(speed) in (int, float) and math.isfinite(speed) and 0 <= speed < .15
    if distance <= .01 and angle <= 1 and quiet:
        if times and (now < times[-1] or now-times[-1] > 1/30+1e-7): times.clear()
        if not times or now > times[-1]+1e-9: times.append(now)
        del times[:-4]
    else:
        times.clear()
    natural = len(times) == 4 and times[-1]-times[0] >= .1-1e-7
    if not natural and now-requested < 14-1e-7:
        return False
    record.update(forced_idle_request=not natural, idle_request_attempted_sim_time=now,
                  neutral_position_error_m=distance, neutral_angle_error_deg=angle)
    try:
        if backend.task_state(handle, recovery_id) == 'running': agent.cancel_task(recovery_id)
        receipt = agent.idle()
        if type(receipt) is not int or receipt <= 0 or receipt in (recovery_id, record['retired_native_task_id']):
            raise ValueError('owned recovery Idle receipt is invalid')
    except Exception as error:
        record.update(idle_request_failed=True, phase='idle_request_failed', idle_request_error=str(error))
        return False
    record.update(idle_request_native_task_id=receipt, idle_requested_sim_time=now, phase='idle_requested')
    known = instance.setdefault('engine_native_ids', []); known.append(receipt); del known[:-32]
    if backend.on_event:
        backend.on_event('native_custom_idle_requested', agent=handle, retired_native_task_id=record['retired_native_task_id'],
                        recovery_native_task_id=recovery_id, idle_request_native_task_id=receipt,
                        requested_sim_time=requested, idle_requested_sim_time=now, body_generation=record['body_generation'],
                        forced_idle_request=not natural, neutral_position_error_m=distance, neutral_angle_error_deg=angle)
    return False
