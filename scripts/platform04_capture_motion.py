"""Actual 6.2 Behavior retarget + full production-joint capture for film use."""
import argparse,sys,os,json,shutil,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}))
shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,out/'source_snapshot'/Path(__file__).name);shutil.copytree(ROOT/'.runtime/platform04/prepared02',out/'source_snapshot/prepared');shutil.copytree(ROOT/'configs',out/'config');shutil.copy2(ROOT/'.runtime/platform04/prepared02/custom_actions.json',out/'config/custom_actions.json');sys.path.insert(0,str(out/'source_snapshot/src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});rec=None;backend=None;code=0
try:
 import omni.usd,omni.kit.app,carb,numpy as np
 from pxr import Usd,UsdGeom,UsdSkel,Gf
 manager=omni.kit.app.get_app().get_extension_manager()
 for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:manager.set_extension_enabled_immediate(ext,True)
 from simpeople.backends.native.scene import build_scene
 from simpeople.backends.native.adapter import NativeBackend
 from simpeople.backends.native.custom_actions import register
 from simpeople.backends.native.recording import Recorder
 omni.usd.get_context().new_stage();sem=build_scene(False);stage=omni.usd.get_context().get_stage()
 for path in ['/World/WallA','/World/WallB','/World/DoorPost','/World/Workbench','/World/MovableBox','/World/Chair']:stage.RemovePrim(path)
 backend=NativeBackend(ROOT,sem,allow_unverified=True,config_dir=out/'config');backend.quality_sampling=True;register(backend,out/'custom_actions');handle=backend.spawn('motion_actor','female_adult_business_02',[0,0,0])
 for _ in range(8):app.update()
 assert backend.nav.start_navmesh_baking_and_wait();tl=backend.timeline;tl.set_auto_update(False);tl.set_time_codes_per_second(30);tl.set_end_time(1000);tl.play();tl.commit()
 for _ in range(60):tl.forward_one_frame();app.update()
 agent=backend.agent(handle);sk=next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(stage.GetPrimAtPath(handle)) if p.IsA(UsdSkel.Skeleton));names=list(sk.GetJointsAttr().Get());assert len(names)==101
 asset=next(a for a in backend.assets if a['asset_id']=='female_adult_business_02');(out/'rig.json').write_text(json.dumps({'joints':names,'source_uri':asset['source_uri'],'runtime':backend.runtime_revision},indent=2))
 cam=stage.GetPrimAtPath('/World/Camera');UsdGeom.Xformable(cam).GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(2,-6,1.8),Gf.Vec3d(0,0,.85),Gf.Vec3d(0,0,1)).GetInverse());cam.GetAttribute('focalLength').Set(40)
 rec=Recorder(out,(1920,1080),gpu_index=args.gpu)
 for _ in range(6):rec.step(0)
 rec.control({'mode':'start'});log=(out/'frames.jsonl').open('w');positions=[];rotations=[];records=[];start=tl.get_current_time()
 schedule={0:('sprint',3),90:('infected_sprint',3),180:('crouch',3),270:('idle',1)}
 for f in range(300):
  if f in schedule:
   clip,duration=schedule[f];task=backend.start(handle,{'action':'wait'} if clip=='idle' else {'action':'custom_action','target':clip,'duration_s':duration});print('clip',clip,task,flush=True)
  rec.step(1/30);rec.step(0);obs=backend.observe(handle);ps=[];qs=[]
  for j in range(101):
   v=carb.Float3(0,0,0);q=carb.Float4(0,0,0,1)
   if not agent.get_joint_world_transform(j,v,q):raise RuntimeError('unavailable target joint')
   ps.append([v.x,v.y,v.z]);qs.append([q.x,q.y,q.z,q.w])
  positions.append(ps);rotations.append(qs);record={'source_tick':f,'sim_time_s':tl.get_current_time(),'clip':clip,'position_m':obs['position_m'],'facing_direction':obs['facing_direction'],'native_task':task};records.append(record);log.write(json.dumps(record)+'\n');rec.capture(tl.get_current_time(),{'source_tick':f,'clip':clip,'controller':'Native Behavior 110.4'})
  if f in [30,60,120,150,200,240,299]:
   from PIL import Image
   Image.fromarray(np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3]).save(out/f'frame_{f:04d}.png')
 log.close();np.savez_compressed(out/'native_bones.npz',positions=np.array(positions),rotations=np.array(rotations));rec.close();(out/'completed.json').write_text(json.dumps({'frames':300,'joints':101,'runtime':backend.runtime_revision,'scope':'Native production actor plays tagged sprint/infected sprint/crouch in place; film translation and native pursuit are separate tests'},indent=2))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 if backend:backend.close()
 app.close()
raise SystemExit(code)
