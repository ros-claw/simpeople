"""Isolated official MotionBricks engine adapter; never imported into Kit."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time

PIN='54fc563aeaaf819a753d72cc9fdc6713989cdd43'
MODEL_SHA='856419dc72aeb14e591eebf4dd0ea05734a2506ddb00bcd39dd6dac2ad60f4fb'


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for value in iter(lambda:stream.read(1024*1024),b''):h.update(value)
    return h.hexdigest()


class SomaBackend:
    def __init__(self,upstream,rig_file,device='cuda:3',cache_dir=None):
        began=time.monotonic();upstream=Path(upstream).resolve();sys.path.insert(0,str(upstream))
        actual=subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()
        if actual!=PIN:raise ValueError('upstream commit differs from qualified pin')
        import numpy as np
        import warp as wp
        from motionbricks.io.usd import load_skeleton_from_usd
        from motionbricks.io.bvh import load_bvh
        from motionbricks.model.soma.engine import MotionBricksSOMAEngine
        from motionbricks.inference.builder import TensorRTBuildOptions
        from simpeople.motion.rig import validate_rig,rig_digest
        wp.init();wp.set_device(device)
        self.wp=wp;self.np=np;self.rig=json.loads(Path(rig_file).read_text());validate_rig(self.rig)
        if rig_digest(self.rig)!=self.rig['rig_sha256']:raise ValueError('rig manifest changed')
        model=upstream/'motionbricks/assets/onnx/soma/mmm_v6_soma_fp32.onnx'
        if sha256(model)!=MODEL_SHA:raise ValueError('FP32 model hash mismatch')
        if sha256(self.rig['source_usd'])!=self.rig['source_sha256']:raise ValueError('SOMA source skeleton changed')
        self.skeleton=load_skeleton_from_usd(self.rig['source_usd'],self.rig['skeleton_prim_path'])
        if self.skeleton.joint_names!=self.rig['joint_names']:raise ValueError('full skeleton order mismatch')
        reference_motion=upstream/'assets/motions/soma/locomotion/idle/idle_loop_001__A268.bvh'
        self.clip=load_bvh(str(reference_motion),self.skeleton)
        basis=self.rig['model_to_runtime_xyzw'];self.to_runtime=wp.transform(wp.vec3(0,0,0),wp.quat(*basis))
        class AuditedEngine(MotionBricksSOMAEngine):
            def _post_process_generated_poses(engine,context,target,output):
                engine.synchronize()
                frames=int(engine._generated_frame_count.numpy()[0])
                engine.raw_decoded=output.poses[:frames].numpy().copy()
                engine.raw_contacts=output.foot_contacts[:frames].numpy().copy()
                super()._post_process_generated_poses(context,target,output)
        self.engine=AuditedEngine(model,model_to_runtime=self.to_runtime,cache_dir=cache_dir or str(upstream/'.trt-cache'),
            build_options=TensorRTBuildOptions(workspace_size_bytes=2*1024**3,builder_optimization_level=3,enable_fp16=False,enable_tf32=False,batch_size=1),logger_severity='WARNING')
        self.context=self.engine.create_input(self.skeleton);self.target=self.engine.create_input(self.skeleton);self.output=self.engine.create_output(self.skeleton)
        self.provenance={'upstream_commit':actual,'model_sha256':MODEL_SHA,'rig_sha256':self.rig['rig_sha256'],'precision':'FP32','tf32':False,'batch_size':1,
            'device':str(self.engine.device),'cold_initialization_wall_s':time.monotonic()-began,
            'package_versions':{n:importlib.metadata.version(n) for n in ['motionbricks','warp-lang','numpy','usd-core','tensorrt-cu12','newton']},
            'upstream_lock_sha256':sha256(upstream/'uv.lock'),'backend_source_sha256':sha256(__file__),
            'reference_motion_sha256':sha256(reference_motion),'source_skeleton_sha256':sha256(self.rig['source_usd'])}

    def sample_idle(self,time_s):
        wp=self.wp;poses=wp.empty((4,self.skeleton.num_joints),dtype=wp.transform,device=self.engine.device)
        for i in range(4):self.clip.sample(time_s+i/30,poses[i],root_offset=self.to_runtime,stream=self.engine.stream)
        self.engine.synchronize();return poses.numpy()

    def generate(self,context,target):
        from simpeople.motion.rig import validate_poses
        np=self.np;wp=self.wp;n=self.skeleton.num_joints
        context=validate_poses(context,n);target=validate_poses(target,n)
        if context.shape[0]!=4 or not 1<=target.shape[0]<=4:raise ValueError('four context frames and one to four targets required')
        began=time.monotonic()
        c=wp.array(context.astype(np.float32),dtype=wp.transform,device=self.engine.device)
        t=wp.array(target.astype(np.float32),dtype=wp.transform,device=self.engine.device)
        self.context.update_from_poses(c,stream=self.engine.stream);self.target.update_from_poses(t,stream=self.engine.stream)
        self.engine.generate_animation(self.context,self.target,self.output);self.engine.synchronize();frames=self.output.num_frames
        corrected=self.output.poses[:frames].numpy().copy();validate_poses(corrected,n);raw=self.engine.raw_decoded;validate_poses(raw,n)
        if raw.shape!=corrected.shape:raise ValueError('raw/corrected frame mismatch')
        return {'local_poses':corrected,'raw_local_poses':raw,'foot_contacts':self.output.foot_contacts[:frames].numpy().copy(),
            'raw_network_features':self.engine.device_tensor('pred_global_motions').numpy().copy(),'raw_num_tokens':self.engine.device_tensor('pred_num_tokens').numpy().copy(),
            'wall_s':time.monotonic()-began,'engine_stage_ms':dict(self.engine.timer.milliseconds)}

    def close(self):self.engine.close()
