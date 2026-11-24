"""Observe an owned generated goal and its return, without driving any pose.

Experimental diagnostic gate only. A ready receipt is not native completion.
"""
import copy
import math

from .executed_quality import angles, check_chain, world_goal
from .rig import validate_poses


class ReturnObserver:
    def __init__(self, reference_entry, reference_goal, actual_entry, clip):
        import numpy as np
        self.entry = validate_poses([actual_entry['world_pose']], len(actual_entry['joint_paths']))[0].copy()
        self.goal = world_goal(reference_entry, reference_goal, actual_entry)
        self.names = list(actual_entry['joint_paths'])
        self.anchor_identity = (actual_entry['actor_id'], actual_entry['actor_instance_id'],
                                actual_entry['task']['session_id'], actual_entry['task']['episode_id'])
        if any(value is None for value in self.anchor_identity):
            raise ValueError('world/actor-bound entry required')
        self.clip = clip
        if not isinstance(clip, str) or not clip:
            raise ValueError('explicit native clip required')
        if (np.linalg.norm(self.goal[:, :3]-self.entry[:, :3], axis=-1).max() <= .03
                and angles(self.goal[:, 3:], self.entry[:, 3:]).max() <= 5):
            raise ValueError('goal indistinguishable from return pose')
        self.previous = None
        self.goal_since = self.goal_end = self.return_since = None
        self.receipt = None
        self.failed = False

    def update(self, row):
        """Permanently reject loss of ownership, clock gaps or bad readback."""
        import numpy as np
        if self.failed:
            raise ValueError('observer invalidated; construct a fresh owned attempt')
        if self.receipt is not None:
            self.failed = True
            raise ValueError('one-shot return receipt already consumed')
        try:
            check_chain([self.previous, row] if self.previous else [row])
            obs = row['actual_observation']
            identity = (row['actor_id'], row['actor_instance_id'], row['task']['session_id'], row['task']['episode_id'])
            if (identity != self.anchor_identity or row['joint_paths'] != self.names or row['task']['status'] != 'running'
                    or obs.get('ready') is not True or obs['action'] != self.clip
                    or not isinstance(obs.get('observation_sim_time'), (int, float))
                    or isinstance(obs['observation_sim_time'], bool) or not math.isfinite(obs['observation_sim_time'])
                    or abs(obs['observation_sim_time']-row['sim_time']) > 1e-7
                    or not isinstance(obs.get('speed_mps'), (int, float))
                    or isinstance(obs['speed_mps'], bool) or not math.isfinite(obs['speed_mps']) or obs['speed_mps'] < 0):
                raise ValueError('not an actual same-clock owned running clip')
            pose = validate_poses([row['world_pose']], len(self.names))[0]
        except (ValueError, TypeError, KeyError):
            self.failed = True
            raise
        self.previous = copy.deepcopy(row)
        now = row['sim_time']
        gp = float(np.linalg.norm(pose[:, :3]-self.goal[:, :3], axis=-1).max())
        ga = float(angles(pose[:, 3:], self.goal[:, 3:]).max())
        ep = float(np.linalg.norm(pose[:, :3]-self.entry[:, :3], axis=-1).max())
        ea = float(angles(pose[:, 3:], self.entry[:, 3:]).max())
        if self.goal_end is None:
            if gp <= .03 and ga <= 5:
                if self.goal_since is None:
                    self.goal_since = now
                if now-self.goal_since+1e-7 >= 2:
                    self.goal_end = now
            else:
                self.goal_since = None
        if self.goal_end is not None and now > self.goal_end and ep <= .02 and ea <= 2 and obs['speed_mps'] < .15:
            if self.return_since is None:
                self.return_since = now
            if now-self.return_since+1e-7 >= .3 and self.receipt is None:
                self.receipt = {'goal_start_sim_time': self.goal_since,
                    'goal_end_sim_time': self.goal_end, 'return_start_sim_time': self.return_since,
                    'ready_sim_time': now, 'pose_stream_source_tick': row['source_tick'],
                    'all_actual_joints': len(self.names), 'return_position_error_m': ep,
                    'return_angle_error_deg': ea, 'task': copy.deepcopy(row['task']),
                    'native_task_id': obs['native_task_id'], 'clip': self.clip,
                    'scope': 'Actual fixed-world goal >=2s followed by actual fixed-world return >=0.3s. Read-only diagnostic; not task completion or a playback cursor.'}
        else:
            self.return_since = None
        return copy.deepcopy(self.receipt)
