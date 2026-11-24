"""Optional main-thread full-joint readback alongside the public Kit entrypoint."""
import json


class NativePoseAudit:
    def __init__(self, backend, directory):
        self.backend = backend
        self.stream = (directory / 'native_full_pose_audit.jsonl').open('w', buffering=1)
        self.layouts = {}

    def sample(self, engine, identity):
        from pxr import Usd, UsdSkel
        from simpeople.backends.native.phase_end_stop import capture
        self.backend.assert_thread()
        for aid, actor in engine.actors.items():
            handle = actor['handle']; observation = self.backend.observe(handle)
            if not observation.get('ready'):
                continue
            binding = (handle, actor['actor_instance_id'])
            if binding not in self.layouts:
                rig = next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(self.backend.stage.GetPrimAtPath(handle))
                           if p.IsA(UsdSkel.Skeleton))
                self.layouts[binding] = list(map(str, rig.GetJointsAttr().Get()))
            names = self.layouts[binding]
            task = engine.tasks.get(actor.get('task_id'))
            row = dict(schema_version='simpeople.public-native-pose-audit.v1',
                       frame_identity=dict(identity), sim_time=engine.sim_time,
                       actor_id=aid, actor_instance_id=actor['actor_instance_id'],
                       session_id=engine.session_id, episode_id=engine.episode_id,
                       control_epoch=actor['control_epoch'],
                       traffic_body_instance_id=self.backend.instances[handle].get('traffic_instance_id'),
                       native_actor_prim_path=handle,
                       actual_observation=observation, joint_paths=names,
                       world_pose=capture(self.backend, handle, self.backend.agent(handle), names),
                       task=engine.public(task) if task else None)
            self.stream.write(json.dumps(row, allow_nan=False) + '\n')

    def close(self):
        self.stream.close()
