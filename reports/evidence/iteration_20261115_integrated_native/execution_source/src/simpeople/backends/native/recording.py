"""Rendered RGB capture with explicit wall and simulation time stamps."""
import json
from pathlib import Path
import subprocess
import threading
from queue import Queue, Full
import time
import numpy as np
import omni.replicator.core as rep
import omni.usd
from pxr import Gf, UsdGeom

class Recorder:
    def __init__(self,directory,resolution=(1920,1080),fps=30,gpu_index=0,capture_profile='full',encoder_threads=4):
        self.directory=Path(directory);self.resolution=resolution;self.fps=fps
        self.encoder_threads=encoder_threads
        self.capture_profile=capture_profile
        self.product=rep.create.render_product('/World/Camera',resolution)
        # The local 6.2 RC's Warp GPU readback fails on nonzero GPUs, including
        # explicit cuda:<index>. CPU readback has been verified on this machine.
        self.rgb=None;self.gpu_rgb=None
        if capture_profile!='render_only':
            self.rgb=rep.AnnotatorRegistry.get_annotator('rgb',device='cpu',do_array_copy=False)
            self.rgb.attach([self.product])
        else:
            # Keep an active GPU RGB graph; merely retaining a render product
            # can let the orchestrator skip the image pipeline entirely.
            # No get_data() or Warp readback is performed in this ablation.
            self.gpu_rgb=rep.AnnotatorRegistry.get_annotator('rgb',device=f'cuda:{gpu_index}',do_array_copy=False)
            self.gpu_rgb.attach([self.product])
        self.pipe=None;self.timestamps=None;self.frames=0;self.recording_id=None
        self.segment=0;self.writer=None;self.writer_error=None;self.segments=[]
        self.backpressure_s=[];self.max_queue_depth=0;self.written_frames=0;self.empty_rgb_frames=0
        self.camera_mode='overview';self.focus_actor_id=None
        camera=UsdGeom.Xformable(omni.usd.get_context().get_stage().GetPrimAtPath('/World/Camera'))
        self.overview_transform=camera.GetOrderedXformOps()[0].Get()
        self.overview_lens={name:camera.GetPrim().GetAttribute(name).Get() for name in ['focalLength','horizontalAperture','verticalAperture']}

    def follow(self,position):
        target=Gf.Vec3d(position[0],position[1],1.0)
        eye=target+(Gf.Vec3d(3.4,.3,.35) if self.camera_mode=='seat_side' else Gf.Vec3d(.3,-3.5,.6) if self.camera_mode=='gait_side' else Gf.Vec3d(3.2,-5.0,2.8))
        camera=UsdGeom.Xformable(omni.usd.get_context().get_stage().GetPrimAtPath('/World/Camera'))
        for name,value in {'focalLength':35.,'horizontalAperture':36.,'verticalAperture':20.25}.items():camera.GetPrim().GetAttribute(name).Set(value)
        camera.GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(eye,target,Gf.Vec3d(0,0,1)).GetInverse())

    def snapshot(self,name):
        if self.rgb is None:raise RuntimeError('RGB readback is disabled in render_only mode')
        from PIL import Image
        rep.orchestrator.step(rt_subframes=4,delta_time=0.0,pause_timeline=False,wait_for_render=True)
        data=self.rgb.get_data(device='cpu')
        path=self.directory/name;path.parent.mkdir(parents=True,exist_ok=True)
        Image.fromarray(np.ascontiguousarray(data[:,:,:3])).save(path)
        return str(path)

    def step(self,dt):
        rep.orchestrator.step(rt_subframes=1,delta_time=dt,pause_timeline=False,wait_for_render=True)

    def control(self,p):
        mode=p.get('mode')
        if mode=='camera':
            self.camera_mode=p['view'];self.focus_actor_id=p.get('actor_id')
            if self.camera_mode=='overview':
                camera=UsdGeom.Xformable(omni.usd.get_context().get_stage().GetPrimAtPath('/World/Camera'))
                camera.GetOrderedXformOps()[0].Set(self.overview_transform)
                for name,value in self.overview_lens.items():camera.GetPrim().GetAttribute(name).Set(value)
            return {'status':'succeeded','view':self.camera_mode,'actor_id':self.focus_actor_id}
        if mode=='start':
            if self.capture_profile!='full':return {'status':'disabled_by_capture_profile','capture_profile':self.capture_profile}
            if self.pipe:return {'recording_id':self.recording_id,'status':'running'}
            self.recording_id='rgb-'+str(time.time_ns())
            self.name='raw_video.mp4' if self.segment==0 else f'raw_video_{self.segment:03d}.mp4'
            stamp_name='video_timestamps.jsonl' if self.segment==0 else f'video_timestamps_{self.segment:03d}.jsonl'
            self.segment+=1;self.frames=0;self.writer_error=None;self.written_frames=0
            w,h=self.resolution
            self.pipe=subprocess.Popen(['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24',
                '-s',f'{w}x{h}','-r',str(self.fps),'-i','-','-an','-c:v','libx264','-preset','fast',
                '-crf','20','-threads',str(self.encoder_threads),'-pix_fmt','yuv420p',str(self.directory/self.name)],stdin=subprocess.PIPE)
            self.timestamps=(self.directory/stamp_name).open('w',buffering=1)
            self.queue=Queue(maxsize=16)
            self.writer=threading.Thread(target=self.write_frames,daemon=True);self.writer.start()
            return {'recording_id':self.recording_id,'status':'running','file':self.name,
                'timebase':'simulation frames; actual wall time is retained in video_timestamps.jsonl'}
        if mode=='stop':return self.close()
        raise ValueError('mode must be start or stop')

    def capture(self,sim_time,frame_identity=None):
        if self.capture_profile=='render_only':return
        if self.capture_profile=='no_encode':
            data=self.rgb.get_data(device='cpu')
            if isinstance(data,np.ndarray) and data.size:
                frame=np.ascontiguousarray(data[:,:,:3]);frame.tobytes();self.frames+=1
            return
        if self.pipe is None:return
        if self.writer_error:raise RuntimeError('video encoder failed: '+str(self.writer_error))
        data=self.rgb.get_data(device='cpu')
        if not isinstance(data,np.ndarray) or data.size==0:self.empty_rgb_frames+=1;return
        frame=np.ascontiguousarray(data[:,:,:3])
        queued_at=time.monotonic()
        try:self.queue.put(frame.tobytes(),timeout=5)
        except Full:raise RuntimeError('video encoder stalled for five wall-clock seconds')
        queue_wait=time.monotonic()-queued_at;self.backpressure_s.append(queue_wait)
        self.max_queue_depth=max(self.max_queue_depth,self.queue.qsize())
        self.timestamps.write(json.dumps({'frame':self.frames,'sim_time':sim_time,'wall_time':time.time(),
                                         'queue_submit_s':queue_wait,'queue_depth':self.queue.qsize(),'frame_identity':frame_identity})+'\n')
        if self.frames==0:
            from PIL import Image
            Image.fromarray(frame).save(self.directory/('first_frame.png' if self.segment==1 else f'first_frame_{self.segment:03d}.png'))
        self.frames+=1
        return self.frames-1

    def write_frames(self):
        try:
            while True:
                frame=self.queue.get()
                if frame is None:break
                self.pipe.stdin.write(frame)
                self.written_frames+=1
        except Exception as error:self.writer_error=error
        finally:
            try:self.pipe.stdin.close()
            except OSError:pass

    def close(self):
        if self.pipe:
            if self.writer.is_alive():self.queue.put(None,timeout=5)
            self.writer.join(timeout=30)
            if self.writer.is_alive():self.pipe.kill();raise RuntimeError('encoder shutdown timed out')
            code=self.pipe.wait(timeout=30)
            self.timestamps.close();self.pipe=None
            if code or self.writer_error:raise RuntimeError('ffmpeg failed: '+str(self.writer_error or code))
            if self.frames!=self.written_frames:raise RuntimeError('encoder frame count mismatch')
            self.segments.append({'recording_id':self.recording_id,'file':self.name,'frames':self.frames,
                                  'encoding_fps':self.fps,'clock':'simulation frames'})
            (self.directory/'video_index.json').write_text(json.dumps(self.segments,indent=2))
            waits=sorted(self.backpressure_s)
            (self.directory/'recording_metrics.json').write_text(json.dumps({'queue_capacity':16,'max_queue_depth':self.max_queue_depth,
                'encoder_threads':self.encoder_threads,
                'submit_wait_p95_s':waits[min(len(waits)-1,int(.95*len(waits)))] if waits else 0,
                'empty_rgb_frames':self.empty_rgb_frames,'frames_written':sum(x['frames'] for x in self.segments),
                'dropped_frames':0,'policy':'bounded blocking queue; fail if encoder stalls >5 wall seconds'},indent=2))
        return {'recording_id':self.recording_id,'status':'stopped','frames':self.frames,
                'file':str(self.directory/getattr(self,'name','raw_video.mp4'))}
