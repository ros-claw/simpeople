"""Independent Isaac 6.2 Deadweight rehearsal. Existing film inputs stay intact."""
import argparse,hashlib,json,os,sys,time,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);a=p.parse_args()
d=ROOT/'runs'/a.run_id;d.mkdir(parents=True,exist_ok=False)
(d/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),'run_id':a.run_id}))
snapshot=d/'source_snapshot';snapshot.mkdir()
for name in ['scripts/deadweight_probe.py','src/simpeople/backends/native/custom_actions.py','src/simpeople/backends/native/adapter.py','configs/deadweight/actions.json']:
 target=snapshot/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
configs=d/'config';shutil.copytree(ROOT/'configs',configs)
shutil.copy2(ROOT/'configs/deadweight/actions.json',configs/'custom_actions.json')
sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':a.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
recorder=None
try:
 import carb,omni.usd,omni.kit.app
 manager=omni.kit.app.get_app().get_extension_manager()
 for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:manager.set_extension_enabled_immediate(ext,True)
 from pxr import UsdGeom,UsdSkel,Usd,Gf
 from simpeople.backends.native.scene import build_scene
 from simpeople.backends.native.adapter import NativeBackend
 from simpeople.backends.native.custom_actions import register
 from simpeople.backends.native.recording import Recorder
 from simpeople.core.engine import Engine
 from simpeople.core.journal import Journal
 omni.usd.get_context().new_stage();sem=build_scene(False);stage=omni.usd.get_context().get_stage()
 for path in ['/World/WallA','/World/WallB','/World/DoorPost','/World/Workbench','/World/MovableBox','/World/Chair']:stage.RemovePrim(path)
 # Visible ground references make horizontal slipping observable.
 from simpeople.backends.native.scene import mesh_box
 for i in range(-9,10):
  prim=mesh_box(stage,f'/World/Grid/x{i+9}',(i,0,.002),(.012,20,.003),(.07,.1,.13))
  prim=mesh_box(stage,f'/World/Grid/y{i+9}',(0,i,.002),(20,.012,.003),(.07,.1,.13))
 backend=NativeBackend(ROOT,sem,allow_unverified=True,config_dir=configs);backend.quality_sampling=True
 register(backend,d/'custom_actions')
 journal=Journal(d,{'scenario':'deadweight_zombie_probe','gpu':a.gpu});engine=Engine(backend,journal)
 engine.cmd_spawn({'actor_id':'tourist_01','asset_id':'female_adult_business_02','spawn_anchor':[-2,0,0]})
 engine.cmd_run_activity({'request_id':'normal','actor_id':'tourist_01','steps':[{'action':'move_to','target':[1,0,0]}]},source='scheduler')
 for _ in range(5):app.update()
 assert backend.nav.start_navmesh_baking_and_wait()
 tl=backend.timeline;tl.set_auto_update(False);tl.set_time_codes_per_second(30);tl.set_end_time(1000);tl.set_play_every_frame(True);tl.play();tl.commit()
 for _ in range(90):
  tl.forward_one_frame();app.update()
  if backend.observe(engine.actors['tourist_01']['handle']).get('ready'):break
 camera=UsdGeom.Xformable(stage.GetPrimAtPath('/World/Camera'));camera.GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(2,-7,2.4),Gf.Vec3d(0,0,.95),Gf.Vec3d(0,0,1)).GetInverse())
 stage.GetPrimAtPath('/World/Camera').GetAttribute('focalLength').Set(38)
 recorder=Recorder(d,(1920,1080),gpu_index=a.gpu);backend.recorder=recorder
 for _ in range(5):recorder.step(0.)
 recorder.control({'mode':'start'})
 log=(d/'zombie_frames.jsonl').open('w');start=tl.get_current_time()
 import numpy as np
 handle=engine.actors['tourist_01']['handle'];agent=backend.agent(handle)
 skeleton=next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(stage.GetPrimAtPath(handle)) if p.IsA(UsdSkel.Skeleton))
 joint_names=list(skeleton.GetJointsAttr().Get());positions=[];rotations=[]
 (d/'cache_rig.json').write_text(json.dumps({'joints':joint_names,'skeleton_path':str(skeleton.GetPath()),'source_uri':next(x['source_uri'] for x in backend.assets if x['asset_id']=='female_adult_business_02'),'skeleton_world_matrix':list(map(list,UsdGeom.XformCache().GetLocalToWorldTransform(skeleton.GetPrim()))),'meters_per_unit':backend.mpu},indent=2))
 for frame in range(390):
  if frame==90:
   engine.cmd_run_activity({'request_id':'infection','actor_id':'tourist_01','steps':[{'action':'custom_action','target':'zombie_walk','duration_s':8,'timeout_s':15}]},source='scheduler')
  wall=time.monotonic();engine.tick(tl.get_current_time(),False);recorder.step(1/30);engine.tick(tl.get_current_time(),False)
  obs=backend.observe(engine.actors['tourist_01']['handle']);identity={'sample':frame,'video_frame':frame,'sim_time':tl.get_current_time()}
  jp_frame=[];jq_frame=[]
  for joint in range(len(joint_names)):
   jp=carb.Float3(0,0,0);jq=carb.Float4(0,0,0,1)
   if not agent.get_joint_world_transform(joint,jp,jq):raise RuntimeError(f'joint {joint} is unavailable')
   jp_frame.append([jp.x,jp.y,jp.z]);jq_frame.append([jq.x,jq.y,jq.z,jq.w])
  positions.append(jp_frame);rotations.append(jq_frame)
  recorder.capture(tl.get_current_time(),identity)
  log.write(json.dumps({'frame':frame,'sim_time':tl.get_current_time(),'wall_s':time.monotonic()-wall,'actor_id':'tourist_01',**obs})+'\n')
  if frame in [0,89,120,160,200,260,320,389]:
   from PIL import Image
   import numpy as np
   Image.fromarray(np.asarray(recorder.rgb.get_data(device='cpu'))[:,:,:3]).save(d/f'frame_{frame:04d}.png')
 log.close();recorder.close();recorder=None
 np.savez_compressed(d/'native_bones.npz',positions=np.asarray(positions),rotations=np.asarray(rotations))
 journal.write('tasks.json',list(engine.tasks.values()));journal.write('environment.json',backend.runtime_revision)
 (d/'scope.json').write_text(json.dumps({'scope':'same production actor: native normal move to imported zombie in-place clip; translating zombie gait is NOT yet accepted','frames':390,'fps':30,'source_assets':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [Path(json.loads((configs/'custom_actions.json').read_text())['actions']['zombie_walk']['clip'])]}},indent=2))
 for aid in engine.actors:engine.abort_actor(aid,'process_shutdown')
 backend.close();journal.finish(engine,exit_code=0,recorded_frames=390,video_timebase='simulation frames')
except Exception:
 import traceback
 traceback.print_exc()
 (d/'failed.txt').write_text(traceback.format_exc())
finally:
 if recorder:recorder.close()
 app.close()
