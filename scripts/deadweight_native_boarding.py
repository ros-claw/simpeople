"""Six stationary-cabin Native navigation rehearsals on the actual high platform.

This separately tests SDK pathing at +61.63m. The film director does not own
these actors. It does not validate moving-cabin ride or zombie navigation.
"""
import argparse,sys,os,json,shutil,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);a=p.parse_args()
directory=ROOT/'runs'/a.run_id;directory.mkdir(parents=True,exist_ok=False)
(directory/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),'run_id':a.run_id}))
for name in ['scripts/deadweight_native_boarding.py','src/simpeople/backends/native/deadweight_set.py','src/simpeople/backends/native/adapter.py']:
 target=directory/'source_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':a.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
recorder=None;backend=None;code=0
try:
 import omni.usd,omni.kit.app,omni.kit.commands
 from pxr import UsdGeom,UsdPhysics,Gf,Sdf
 import numpy as np
 from simpeople.backends.native.scene import build_scene
 from simpeople.backends.native.deadweight_set import create_set,RUN,FLOOR
 from simpeople.backends.native.recording import Recorder
 manager=omni.kit.app.get_app().get_extension_manager()
 for extension in ['omni.anim.behavior.core','omni.anim.navigation.core']:manager.set_extension_enabled_immediate(extension,True)
 from simpeople.backends.native.adapter import NativeBackend
 omni.usd.get_context().new_stage();sem=build_scene(False);stage=omni.usd.get_context().get_stage()
 for path in ['/World/Ground','/World/WallA','/World/WallB','/World/DoorPost','/World/Workbench','/World/MovableBox','/World/Chair','/World/Camera']:stage.RemovePrim(path)
 cars=create_set(stage,ROOT)
 for name,car in cars.items():
  car['xform'].Set(Gf.Vec3d(RUN if name=='A' else 0,-2.4 if name=='A' else 2.4,59 if name=='A' else 3))
  for key,op in car['doors'].items():op.Set(Gf.Vec3d(0,0,3) if key=='inner' else Gf.Vec3d(1.85,0,0))
 volume=stage.GetPrimAtPath('/World/NavMeshVolume');UsdGeom.XformCommonAPI(volume).SetTranslate(Gf.Vec3d(RUN,-6,62));UsdGeom.XformCommonAPI(volume).SetScale(Gf.Vec3f(20,18,6))
 for prim in stage.Traverse():
  if prim.IsA(UsdGeom.Mesh) and ('/Cars/' in str(prim.GetPath()) or '/Upper/' in str(prim.GetPath())):UsdPhysics.CollisionAPI.Apply(prim)
 backend=NativeBackend(ROOT,sem,allow_unverified=True);backend.quality_sampling=True
 actors=[]
 for i in range(6):
  x=-2.2 if i<3 else 3.3;y=-3.2-(i%3)*1.3
  handle=backend.spawn(f'boarder_{i+1:02d}','female_adult_business_02',[RUN+x,-2.4+y,59+FLOOR])
  slot=[RUN+[-2.8,-1.7,-.6,1.6,2.7,3.8][i],-2.4+1.05,59+FLOOR]
  actors.append({'id':f'boarder_{i+1:02d}','handle':handle,'slot':slot,'door_x':RUN+x})
 for _ in range(6):app.update()
 stage.GetRootLayer().Export(str(directory/'scene.usda'))
 if not backend.nav.start_navmesh_baking_and_wait():raise RuntimeError('high-platform NavMesh bake failed')
 timeline=backend.timeline;timeline.set_auto_update(False);timeline.set_time_codes_per_second(30);timeline.set_end_time(1000);timeline.play();timeline.commit()
 for _ in range(60):timeline.forward_one_frame();app.update()
 camera=UsdGeom.Xformable(stage.GetPrimAtPath('/World/Camera')).GetOrderedXformOps()[0];target=Gf.Vec3d(RUN,-3,63);camera.Set(Gf.Matrix4d().SetLookAt(target+Gf.Vec3d(-3,-18,5),target,Gf.Vec3d(0,0,1)).GetInverse());stage.GetPrimAtPath('/World/Camera').GetAttribute('focalLength').Set(38)
 recorder=Recorder(directory,(1920,1080),gpu_index=a.gpu)
 for _ in range(5):recorder.step(0)
 recorder.control({'mode':'start'});log=(directory/'frames.jsonl').open('w');current=0;task=None;stable=None;events=[]
 for frame in range(1500):
  wall=time.monotonic();sim=timeline.get_current_time()
  if current<len(actors) and task is None:
   actor=actors[current];x=actor['door_x'];z=59+FLOOR
   step={'action':'move_to','target':actor['slot'],'via':[[x,-5,z],[x,-2.925,z],[actor['slot'][0],-2.925,z]],'speed_mps':1.0}
   task=backend.start(actor['handle'],step);events.append({'event':'native_move_started','actor_id':actor['id'],'task_id':task,'frame':frame,'sim_time':sim})
  recorder.step(1/30);obs={v['id']:backend.observe(v['handle']) for v in actors}
  if current<len(actors):
   actor=actors[current];o=obs[actor['id']];state=backend.task_state(actor['handle'],task)
   if state=='failed':raise RuntimeError(f"Native boarding failed: {actor['id']}")
   good=state=='succeeded' and np.linalg.norm(np.array(o['position_m'])-actor['slot'])<.3 and o['speed_mps']<.15
   if good:
    stable=timeline.get_current_time() if stable is None else stable
    if timeline.get_current_time()-stable>=.5:
     events.append({'event':'native_boarding_completed','actor_id':actor['id'],'frame':frame,'sim_time':timeline.get_current_time(),'observation':o});current+=1;task=None;stable=None
   else:stable=None
  recorder.capture(timeline.get_current_time(),{'source_tick':frame,'controller':'Native Behavior SDK'})
  log.write(json.dumps({'frame':frame,'sim_time':timeline.get_current_time(),'wall_s':time.monotonic()-wall,'actors':obs})+'\n')
  if frame in [0,300,600,900] or current==6:
   from PIL import Image
   Image.fromarray(np.asarray(recorder.rgb.get_data(device='cpu'))[:,:,:3]).save(directory/f'frame_{frame:04d}.png')
  if current==6:break
 log.close();recorder.close();recorder=None
 (directory/'result.json').write_text(json.dumps({'passed':current==6,'boarded':current,'events':events,'runtime':backend.runtime_revision,'scope':'Native ordinary walk through stationary car door at +61.63m. No moving-car ride or Native zombie locomotion claim.'},indent=2))
 if current!=6:raise RuntimeError(f'only {current}/6 actors completed native boarding')
except Exception:
 import traceback
 traceback.print_exc();(directory/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if recorder:recorder.close()
 if backend:backend.close()
 app.close()
raise SystemExit(code)
