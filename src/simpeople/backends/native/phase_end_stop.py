"""Cancel one named action and wait for its measured end phase to settle."""
import math


def capture(backend, handle, agent, names):
    import carb
    from pxr import Usd, UsdSkel
    rig = next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(backend.stage.GetPrimAtPath(handle))
               if p.IsA(UsdSkel.Skeleton))
    if list(map(str, rig.GetJointsAttr().Get())) != names:
        raise ValueError('end-phase pose readback uses a different skeleton')
    result = []
    for i in range(len(names)):
        point = carb.Float3(0, 0, 0); q = carb.Float4(0, 0, 0, 1)
        if not agent.get_joint_world_transform(i, point, q):
            raise ValueError('end-phase actual joint unavailable')
        result.append([*backend.to_public(point), q.x, q.y, q.z, q.w])
    return result


def request(backend, handle, entry, current, name, agent):
    backend.assert_thread()
    if not getattr(backend, 'phase_end_stop_probe_enabled', False) or not entry.get('experimental_phase_sources'):
        return False
    instance = backend.instances[handle]; generation = instance.get('traffic_instance_id')
    reference = entry.get('canonical_entry')
    if (not isinstance(reference, dict) or not reference or entry.get('entry_base_action') != 'Idle'
            or type(current) is not int or current <= 0 or current not in instance.get('engine_native_ids', [])
            or not isinstance(generation, str) or not generation
            or agent.get_action_task_id() != current or agent.get_task_name(current) != name):
        return False
    if instance.get('custom_stop'):
        return True
    asset = next(a for a in backend.assets if a['asset_id'] == instance['asset_id'])
    if reference['source_asset_sha256'] != asset['content_hash']:
        raise ValueError('end phase belongs to another actor asset')
    observation = backend.observe(handle); now = backend.timeline.get_current_time()
    if not observation.get('ready') or observation.get('observation_sim_time') != now or observation.get('native_task_id') != current:
        return False
    pose = capture(backend, handle, agent, reference['joint_paths'])
    from simpeople.motion.executed_quality import world_goal
    ref = dict(world_pose=reference['world_pose'], actual_observation=dict(facing_direction=reference['facing_direction']))
    target = world_goal(ref, ref, dict(world_pose=pose, actual_observation=observation)).tolist()
    record = dict(retired_native_task_id=current, clip=name, body_generation=generation,
                  requested_sim_time=now, phase_end_stop=True, phase='native_cancel_requested',
                  idle_request_native_task_id=None, actual_idle_times=[], neutral_times=[],
                  neutral_target_world_pose=target, neutral_joint_paths=reference['joint_paths'])
    instance['custom_stop'] = record
    agent.cancel_task(current)  # No replacement custom_action or live pose write.
    if backend.on_event:
        backend.on_event('native_custom_stop_requested', agent=handle, **record)
    return True


def advance(backend, handle, record, observation, agent):
    backend.assert_thread()
    instance = backend.instances.get(handle, {}); now = backend.timeline.get_current_time()
    requested = record['requested_sim_time']; retired = record['retired_native_task_id']
    if (not record.get('body_generation') or instance.get('traffic_instance_id') != record['body_generation']
            or type(now) not in (int, float) or not math.isfinite(now)
            or not requested+1e-9 < now <= requested+15+1e-7
            or not observation.get('ready') or observation.get('observation_sim_time') != now
            or agent is None or type(agent.get_action_task_id()) is not int
            or observation.get('native_task_id') != agent.get_action_task_id()):
        return False
    if record.get('idle_request_native_task_id') is not None:
        return True
    if record.get('idle_request_failed'):
        return False
    current = observation['native_task_id']
    known_idle = current in instance.get('engine_native_ids', []) and agent.get_task_name(current) == 'Idle'
    if current not in (0, retired) and not known_idle:
        return False
    import numpy as np
    from simpeople.motion.executed_quality import angles
    pose = np.asarray(capture(backend, handle, agent, record['neutral_joint_paths']))
    target = np.asarray(record['neutral_target_world_pose'])
    distance = float(np.linalg.norm(pose[:, :3]-target[:, :3], axis=-1).max())
    angle = float(angles(pose[:, 3:], target[:, 3:]).max())
    times = record['neutral_times']; speed = observation.get('speed_mps')
    quiet = type(speed) in (int, float) and math.isfinite(speed) and 0 <= speed < .15
    if distance <= .02 and angle <= 2 and quiet:
        if times and (now < times[-1] or now-times[-1] > 1/30+1e-7): times.clear()
        if not times or now > times[-1]+1e-9: times.append(now)
        del times[:-4]
    else:
        times.clear()
    ended = backend.task_state(handle, retired) != 'running'
    natural = (ended and observation.get('action') in ('Idle', '') and len(times) == 4
               and times[-1]-times[0] >= .1-1e-7)
    if not natural and now-requested < 14-1e-7:
        return False
    record.update(forced_idle_request=not natural, neutral_position_error_m=distance,
                  neutral_angle_error_deg=angle, idle_request_attempted_sim_time=now)
    try:
        receipt = agent.idle()
        if type(receipt) is not int or receipt <= 0 or receipt == retired:
            raise ValueError('end phase requires a distinct positive Idle receipt')
    except Exception as error:
        record.update(idle_request_failed=True, phase='idle_request_failed', idle_request_error=str(error))
        return False
    record.update(idle_request_native_task_id=receipt, idle_requested_sim_time=now, phase='idle_requested')
    known = instance.setdefault('engine_native_ids', []); known.append(receipt); del known[:-32]
    if backend.on_event:
        backend.on_event('native_custom_idle_requested', agent=handle, retired_native_task_id=retired,
                        idle_request_native_task_id=receipt, requested_sim_time=requested,
                        idle_requested_sim_time=now, body_generation=record['body_generation'],
                        forced_idle_request=not natural, neutral_position_error_m=distance, neutral_angle_error_deg=angle)
    return False
