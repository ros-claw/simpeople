"""Capture actual Native normal locomotion, all 101 joints, before film edits."""
import argparse,json,os,shutil,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);args=p.parse_args()
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False)
(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}))
shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copy2(__file__,out/'source_snapshot'/Path(__file__).name)
sys.path.insert(0,str(out/'source_snapshot/src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});rec=None;backend=None;code=0
try:
 import omni.usd,omni.kit.app,numpy as np,carb
 from pxr import Usd,UsdSkel,UsdGeom,Gf
 manager=omni.kit.app.get_app().get_extension_manager()
 for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:manager.set_extension_enabled_immediate(ext,True)
 from simpeople.backends.native.scene import build_scene
 from simpeople.backends.native.adapter import NativeBackend
 from simpeople.backends.native.recording import Recorder
 from simpeople.backends.native.platform04_scene import aim
 omni.usd.get_context().new_stage();sem=build_scene(True);stage=omni.usd.get_context().get_stage()
 for path in ['/World/WallA','/World/WallB','/World/DoorPost','/World/Workbench','/World/MovableBox','/World/Chair']:stage.RemovePrim(path)
 backend=NativeBackend(ROOT,sem,allow_unverified=True);backend.quality_sampling=True
 handle=backend.spawn('healthy_jog','female_adult_business_02',[-8,0,0])
 for _ in range(8):app.update()
 assert backend.nav.start_navmesh_baking_and_wait()
 tl=backend.timeline;tl.set_auto_update(False);tl.set_time_codes_per_second(30);tl.set_end_time(1000);tl.play();tl.commit()
 for _ in range(90):tl.forward_one_frame();app.update()
 agent=backend.agent(handle);sk=next(UsdSkel.Skeleton(x) for x in Usd.PrimRange(stage.GetPrimAtPath(handle)) if x.IsA(UsdSkel.Skeleton));names=list(sk.GetJointsAttr().Get());assert len(names)==101
 (out/'rig.json').write_text(json.dumps({'joints':names,'source_uri':str(ROOT/'assets/characters/female_adult_business_02/female_adult_business_02.usd'),'runtime':backend.runtime_revision},indent=2))
 task=backend.start(handle,{'action':'move_to','target':[16,0,0],'speed_mps':2.8})
 rec=Recorder(out,(1920,1080),gpu_index=args.gpu)
 for _ in range(6):rec.step(0)
 rec.control({'mode':'start'});positions=[];rotations=[];trace=[];log=(out/'frames.jsonl').open('w')
 for f in range(210):
  o=backend.observe(handle);x,y,z=o['position_m'];aim(stage,[x,y-5.5,1.25],[x,y,1.0],42)
  rec.step(1/30);rec.step(0);o=backend.observe(handle);ps=[];qs=[]
  for j in range(101):
   v=carb.Float3(0,0,0);q=carb.Float4(0,0,0,1)
   if not agent.get_joint_world_transform(j,v,q):raise RuntimeError('actual Native joint unavailable')
   ps.append([v.x,v.y,v.z]);qs.append([q.x,q.y,q.z,q.w])
  positions.append(ps);rotations.append(qs);r={'source_tick':f,'sim_time_s':tl.get_current_time(),'position_m':o['position_m'],'facing_direction':o['facing_direction'],'observation':o,'task':task};trace.append(r);log.write(json.dumps(r)+'\n');rec.capture(tl.get_current_time(),{'source_tick':f,'scope':'actual normal Native movement, no film bone/root writers'})
  if f%30==0:print('jog',f,o['position_m'],o['speed_mps'],flush=True)
 log.close();rec.close();np.savez_compressed(out/'native_bones.npz',positions=np.array(positions),rotations=np.array(rotations))
 asset=next(a for a in backend.assets if a['asset_id']=='female_adult_business_02');rig=json.loads((out/'rig.json').read_text());rig['source_uri']=str(ROOT/'assets/characters'/asset['source_uri'].removeprefix('characters://'));(out/'rig.json').write_text(json.dumps(rig,indent=2))
 (out/'completed.json').write_text(json.dumps({'frames':len(trace),'joints':101,'task_status':backend.task_state(handle,task),'runtime':backend.runtime_revision,'scope':'capture of actual Native 2.8m/s-requested locomotion, not a destination-completion acceptance'},indent=2))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 if backend:backend.close()
 app.close()
raise SystemExit(code)
