"""Actual executed pose windows and explicit conversion; no Kit dependencies."""
import copy
import math
from collections import deque
from simpeople.core.errors import SimPeopleError
from .contracts import digest
from .rig import validate_poses, validate_rig, project_to_model, decode_reference_pose, forward_kinematics

IDENTITY = ('session_id', 'episode_id', 'actor_id', 'actor_instance_id', 'control_epoch', 'task_id')


def reject(message):
    raise SimPeopleError('MOTION_CONTEXT_INVALID', message, stage='pose_bridge')


def identity(task):
    if not isinstance(task, dict):
        reject('actual task identity required')
    result = {}
    for key in IDENTITY:
        value = task.get(key)
        if key == 'control_epoch':
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                reject('invalid control epoch')
        elif not isinstance(value, str) or not value:
            reject('incomplete execution identity')
        result[key] = value
    return result


class ExecutedPoseHistory:
    """Bounded four-frame ring. Invalid samples invalidate the preceding window."""
    def __init__(self):
        self._rows = deque(maxlen=4)
        self.invalidations = 0

    def clear(self):
        self._rows.clear()
        self.invalidations += 1

    def record(self, row):
        try:
            if not isinstance(row, dict) or row.get('sample_source') != 'behavior_sdk':
                reject('only actual Behavior SDK readbacks are accepted')
            task = identity(row.get('task'))
            if row['task'].get('status') != 'running' or row['task'].get('cancel_requested') or not row.get('actual_observation', {}).get('ready'):
                reject('sample is not from a ready running task')
            if task['actor_id'] != row.get('actor_id') or task['actor_instance_id'] != row.get('actor_instance_id'):
                reject('sample and task actor identities differ')
            names = row.get('joint_paths')
            if not isinstance(names, list) or not names or any(not isinstance(n, str) or not n for n in names) or len(set(names)) != len(names):
                reject('complete unique joint paths required')
            validate_poses([row.get('world_pose')], len(names))
            t = row.get('sim_time')
            tick = row.get('source_tick')
            if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
                reject('finite simulation timestamp required')
            if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
                reject('actual source tick required')
            asset = row.get('source_asset_sha256')
            if not isinstance(asset, str) or len(asset) != 64 or any(c not in '0123456789abcdef' for c in asset):
                reject('actual source asset revision required')
            active=row.get('active_skeleton_sha256')
            if active is not None and (not isinstance(active,str) or len(active)!=64 or any(c not in '0123456789abcdef' for c in active)):
                reject('invalid actual skeleton revision')
            if self._rows:
                old = self._rows[-1]
                changed = identity(old['task']) != task or old['source_asset_sha256'] != asset or old['joint_paths'] != names or old.get('active_skeleton_sha256')!=active or old.get('sample_native_task_id')!=row.get('sample_native_task_id') or old.get('step_index')!=row.get('step_index')
                if changed:
                    self.clear()
                elif t <= old['sim_time'] or tick <= old['source_tick']:
                    reject('duplicate or backwards execution sample')
                elif abs(t - old['sim_time'] - 1 / 30) > 1e-6 or tick != old['source_tick'] + 1:
                    self.clear()
            self._rows.append(copy.deepcopy(row))
        except (ValueError, TypeError, KeyError, SimPeopleError) as error:
            self.clear()
            if isinstance(error, SimPeopleError):
                raise
            reject(str(error))

    def window(self, expected_binding, now_s):
        expected = identity(expected_binding)
        if len(self._rows) != 4:
            reject('four consecutive actual samples are not available')
        if any(identity(r['task']) != expected for r in self._rows):
            reject('history belongs to another execution identity')
        if isinstance(now_s, bool) or not isinstance(now_s, (int, float)) or not math.isfinite(now_s):
            reject('finite current simulation time required')
        age = now_s - self._rows[-1]['sim_time']
        if not -1e-7 <= age <= 1 / 30 + 1e-7:
            reject('actual context is stale or in the future')
        return copy.deepcopy(list(self._rows))


class PoseBridge:
    """Convert an observed window with an explicit, read-only native converter.

    A ModelContext is asset-generation input, never permission for live apply.
    Profile evidence describes a measured domain, not this window's seam quality.
    """
    def __init__(self, rig, converter):
        self.rig = copy.deepcopy(validate_rig(rig))
        self.converter = converter

    def to_model_context(self, executed_history, rig_profile, expected_binding, now_s):
        import numpy as np
        if not isinstance(executed_history, ExecutedPoseHistory):
            reject('bounded actual history required')
        rows = executed_history.window(expected_binding, now_s)
        profile = copy.deepcopy(rig_profile)
        required = ('source_asset_sha256', 'joint_paths_sha256', 'rig_sha256', 'mapping_revision')
        if not isinstance(profile, dict) or any(not isinstance(profile.get(k), str) or not profile[k] for k in required):
            reject('explicit rig profile revisions required')
        if profile['source_asset_sha256'] != rows[0]['source_asset_sha256'] or profile['joint_paths_sha256'] != digest(rows[0]['joint_paths']):
            reject('native rig profile does not match actual asset/joint layout')
        if profile['rig_sha256'] != self.rig.get('rig_sha256'):
            reject('model rig profile revision mismatch')
        if (rows[0].get('active_skeleton_sha256') is not None or profile.get('active_skeleton_sha256') is not None) and profile.get('active_skeleton_sha256')!=rows[0].get('active_skeleton_sha256'):
            reject('actual skeleton no longer matches the calibrated profile')
        # No callback executes before source identity and revisions are checked.
        converted, report = self.converter.convert_world_history(rows, profile)
        full = validate_poses(converted, len(self.rig['joint_names']))
        if len(full) != 4:
            reject('native conversion did not return four full SOMA samples')
        context = {'source': 'executed_history', 'sample_times_s': [r['sim_time'] for r in rows], 'local_poses': full.tolist()}
        binding = identity(expected_binding)
        binding['context_revision'] = digest(context)
        modeled = project_to_model(full, self.rig)
        reference = decode_reference_pose(modeled, self.rig)
        residual = np.linalg.norm(forward_kinematics(reference, self.rig['parents'])[:, :, :3] - forward_kinematics(full, self.rig['parents'])[:, :, :3], axis=-1)
        return {'context': context, 'binding': binding, 'rig_sha256': self.rig['rig_sha256'],
                'mapping_revision': profile['mapping_revision'], 'profile_sha256': digest(profile),
                'source_history_sha256': digest(rows), 'source_ticks': [r['source_tick'] for r in rows],
                'active_skeleton_sha256':rows[0].get('active_skeleton_sha256'),
                'reference_projection_max_joint_error_m': float(residual.max()),
                'projection_scope': 'Diagnostic reference-completion residual; full 77-joint context is retained for official endpoint correction.',
                'conversion': report, 'online_application_verified': False}
