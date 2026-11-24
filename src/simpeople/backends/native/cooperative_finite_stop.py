"""Experimental finite-cycle cleanup on the sole Native controller.

Active cycles finish naturally; a queued cycle can be cancelled before it starts.
A cancellation receipt never establishes a physical stop. No pose/world writes.
"""
import copy
import hashlib
import math
from pathlib import Path

from simpeople.core.errors import SimPeopleError
from .phase_end_stop import capture


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate(backend, handle, step):
    backend.assert_thread()
    entry = backend.custom_actions.get(step.get('target'), {})
    if (not getattr(backend, 'cooperative_finite_stop_probe_enabled', False)
            or step.get('action') != 'custom_action' or entry.get('cooperative_finite_cycle') is not True):
        return None
    from pxr import Usd, UsdGeom, UsdSkel
    from simpeople.core.asset_paths import resolve_asset_path
    duration = step.get('duration_s'); fps = entry.get('sample_rate'); frames = entry.get('frame_count')
    hold = entry.get('endpoint_hold_frames'); reference = entry.get('canonical_entry')
    instance = backend.instances.get(handle, {}); body = instance.get('traffic_instance_id')
    if (entry.get('playback_mode') != 'transition_then_hold' or fps != 30
            or type(frames) is not int or frames < 2 or type(hold) is not int or not 1 <= hold <= 30
            or not finite(duration) or duration <= 0
            or duration != entry.get('requested_native_duration_s')
            or not isinstance(reference, dict) or not reference or entry.get('entry_base_action') != 'Idle'
            or not isinstance(body, str) or not body):
        raise SimPeopleError('ACTION_UNSUPPORTED', 'finite cancellation requires its exact bounded one-shot contract')
    bound = (frames-1+hold)/fps + duration
    if not finite(bound) or bound > 13:
        raise SimPeopleError('ACTION_UNSUPPORTED', 'finite cycle leaves insufficient margin in the original 15-second stop budget')
    asset = next(a for a in backend.assets if a['asset_id'] == instance['asset_id'])
    if reference.get('source_asset_sha256') != asset['content_hash']:
        raise SimPeopleError('MOTION_ENTRY_NOT_READY', 'finite cycle belongs to another actor asset')
    path = Path(resolve_asset_path(entry['clip'], backend.root)); digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry.get('source_sha256', {}).get('clip'):
        raise SimPeopleError('MOTION_ASSET_INVALID', 'finite source bytes changed after registration')
    stage = Usd.Stage.Open(str(path)); animation = UsdSkel.Animation(stage.GetDefaultPrim())
    times = animation.GetRotationsAttr().GetTimeSamples()
    if (len(times) != frames or times != list(range(frames)) or stage.GetTimeCodesPerSecond() != 30
            or UsdGeom.GetStageUpAxis(stage) != 'Y' or abs(UsdGeom.GetStageMetersPerUnit(stage)-.01) > 1e-12):
        raise SimPeopleError('MOTION_ASSET_INVALID', 'finite source timing/units do not match the registered bound')
    return dict(clip=step['target'], body_generation=body, source_clip_sha256=digest,
                source_asset_sha256=asset['content_hash'], requested_native_duration_s=duration,
                conservative_authored_cycle_bound_s=bound, reference=copy.deepcopy(reference))


def register(backend, handle, tid, spec):
    backend.assert_thread()
    if spec is None:
        return
    if type(tid) is not int or tid <= 0:
        raise ValueError('finite cycle requires a positive Native task receipt')
    instance = backend.instances[handle]
    if instance.get('traffic_instance_id') != spec['body_generation']:
        raise RuntimeError('finite task body changed during Native submission')
    instance['owned_finite_cycle'] = dict(copy.deepcopy(spec), native_task_id=tid,
        submitted_sim_time=backend.timeline.get_current_time())
    # A same-thread SDK receipt changes ownership before the next world frame.
    # Preserve older position history, but never return the preceding task ID
    # from a cached observation stamped at this very submission time.
    cached = getattr(backend, 'observations', {}).get(handle)
    if (cached and cached[0] == instance['owned_finite_cycle']['submitted_sim_time']
            and cached[1].get('native_task_id') != tid):
        backend.observations.pop(handle, None)
        getattr(backend, 'observation_frame_ids', {}).pop(handle, None)


def request(backend, handle, current, name, agent):
    backend.assert_thread()
    instance = backend.instances.get(handle, {}); owned = instance.get('owned_finite_cycle')
    if not getattr(backend, 'cooperative_finite_stop_probe_enabled', False) or not owned:
        return False
    old = owned['native_task_id']; body = owned['body_generation']; now = backend.timeline.get_current_time()
    if (not finite(now) or not body or instance.get('traffic_instance_id') != body
            or old not in instance.get('engine_native_ids', [])
            or type(current) is not int or current != agent.get_action_task_id()
):
        return False
    previous = instance.get('custom_stop')
    if previous:
        return previous.get('cooperative_finite_stop') is True and previous.get('retired_native_task_id') == old and previous.get('body_generation') == body
    if backend.task_state(handle, old) != 'running':
        return False
    active = current == old and name == owned['clip']
    queued = current != old and name == 'Idle' and (current == 0 or current in instance.get('engine_native_ids', []))
    if not active and not queued:
        return False
    observation = backend.observe(handle)
    if (observation.get('ready') is not True or observation.get('observation_sim_time') != now
            or observation.get('native_task_id') != current):
        return False
    reference = owned['reference']; pose = capture(backend, handle, agent, reference['joint_paths'])
    from simpeople.motion.executed_quality import world_goal
    ref = dict(world_pose=reference['world_pose'], actual_observation=dict(facing_direction=reference['facing_direction']))
    neutral = world_goal(ref, ref, dict(world_pose=pose, actual_observation=observation)).tolist()
    record = dict(retired_native_task_id=old, clip=owned['clip'], body_generation=body,
                  requested_sim_time=now, cooperative_finite_stop=True, queued_cancelled=queued,
                  phase='awaiting_natural_finite_end', actual_idle_times=[], neutral_times=[],
                  idle_request_native_task_id=None, neutral_joint_paths=reference['joint_paths'],
                  neutral_target_world_pose=neutral, finite_cycle_spec=copy.deepcopy(owned))
    instance['custom_stop'] = record
    if queued:
        # The task was owned/submitted but never acquired the action slot.
        agent.cancel_task(old)
        record['phase'] = 'queued_native_cancelled'
        issue_idle(backend, handle, record, agent, now)
    if backend.on_event:
        backend.on_event('native_custom_stop_requested', agent=handle, **record)
    return True


def issue_idle(backend, handle, record, agent, now):
    if record.get('idle_request_native_task_id') is not None or record.get('idle_request_failed'):
        return
    record['idle_request_attempted_sim_time'] = now
    try:
        tid = agent.idle()
        if type(tid) is not int or tid <= 0 or tid == record['retired_native_task_id']:
            raise ValueError('finite cleanup requires a distinct positive owned Idle receipt')
    except Exception as error:
        record.update(idle_request_failed=True, phase='idle_request_failed', idle_request_error=str(error))
        return
    record.update(idle_request_native_task_id=tid, idle_requested_sim_time=now, phase='idle_requested')
    known = backend.instances[handle].setdefault('engine_native_ids', []); known.append(tid); del known[:-32]
    if backend.on_event:
        backend.on_event('native_custom_idle_requested', agent=handle,
            retired_native_task_id=record['retired_native_task_id'], idle_request_native_task_id=tid,
            requested_sim_time=record['requested_sim_time'], idle_requested_sim_time=now,
            body_generation=record['body_generation'], cooperative_finite_stop=True,
            queued_cancelled=record['queued_cancelled'])


def advance(backend, handle, record, observation, agent):
    backend.assert_thread()
    instance = backend.instances.get(handle, {}); now = backend.timeline.get_current_time()
    if (instance.get('traffic_instance_id') != record.get('body_generation') or not record.get('body_generation')
            or not finite(now) or not record['requested_sim_time'] < now <= record['requested_sim_time']+15+1e-7
            or observation.get('ready') is not True or observation.get('observation_sim_time') != now
            or agent is None or observation.get('native_task_id') != agent.get_action_task_id()):
        return False
    if record.get('idle_request_failed'):
        return False
    if record.get('idle_request_native_task_id') is not None:
        return True  # The caller still enforces actual owned Idle / 16 samples.
    retired = record['retired_native_task_id']; current = observation['native_task_id']
    known_idle = current in instance.get('engine_native_ids', []) and agent.get_task_name(current) == 'Idle'
    if current not in (0, retired) and not known_idle:
        return False
    if backend.task_state(handle, retired) != 'succeeded':
        record['neutral_times'].clear()
        return False  # Never force an unfinished/failed clip onto a guessed pose.
    import numpy as np
    from simpeople.motion.executed_quality import angles
    pose = np.asarray(capture(backend, handle, agent, record['neutral_joint_paths']))
    target = np.asarray(record['neutral_target_world_pose']); speed = observation.get('speed_mps')
    distance = float(np.linalg.norm(pose[:,:3]-target[:,:3], axis=-1).max())
    angle = float(angles(pose[:,3:],target[:,3:]).max()); times = record['neutral_times']
    record.update(neutral_position_error_m=distance, neutral_angle_error_deg=angle)
    if not (distance <= .02 and angle <= 2 and finite(speed) and 0 <= speed < .15):
        times.clear(); return False
    if times and (now < times[-1] or now-times[-1] > 1/30+1e-7): times.clear()
    if not times or now > times[-1]+1e-9: times.append(now)
    del times[:-4]
    if len(times) != 4 or times[-1]-times[0] < .1-1e-7:
        return False
    issue_idle(backend, handle, record, agent, now)
    return False  # The issuing frame is not a settled sample.
