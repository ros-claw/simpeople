"""Open supplied OPEN_METRO/ShotCamera in 6.2 and produce exact-camera stills."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--mode',choices=['kit','formal'],required=True);p.add_argument('--gpu',type=int,default=3);args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));sys.path.insert(0,str(ROOT/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});rec=None;code=0
try:
 import omni.usd,omni.timeline,numpy as np
 from pxr import Usd,UsdGeom,UsdSkel,Gf,Vt
 from PIL import Image
 from simpeople.backends.native.recording import Recorder
 from simpeople.backends.native.platform04_animation import MetroMotion
 kitfile=ROOT/'.runtime/platform04/kit/previs/OPEN_METRO.usda';reference=Usd.Stage.Open(str(kitfile));source_camera=UsdGeom.Camera.Get(reference,'/Metro/Cameras/ShotCamera');assert source_camera
 chosen=kitfile if args.mode=='kit' else ROOT/'runs/platform04-master-01/scene.usda';omni.usd.get_context().open_stage(str(chosen))
 for _ in range(8):app.update()
 stage=omni.usd.get_context().get_stage();camera=UsdGeom.Camera.Define(stage,'/World/Camera');xf=UsdGeom.Xformable(camera)
 if not xf.GetOrderedXformOps():xf.AddTransformOp()
 tl=omni.timeline.get_timeline_interface();tl.set_auto_update(False);tl.set_time_codes_per_second(24 if args.mode=='kit' else 30);tl.play();tl.commit()
 if args.mode=='formal':
  rows={r['source_tick']:r for r in map(json.loads,(ROOT/'runs/platform04-master-01/frames.jsonl').read_text().splitlines())};bank=MetroMotion(ROOT)
 metadata=[]
 for t in [8.5,11.5]:
  if args.mode=='formal':
   r=rows[round(t*30)]
   for aid,a in r['actors'].items():
    matrix=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0,0,1),math_degrees:=a['yaw_rad']*180/np.pi));matrix.SetTranslateOnly(Gf.Vec3d(*a['root_world_m']));m=np.asarray(matrix);points=(np.asarray(a['joints_world_m'])-m[3,:3])@m[:3,:3].T;q=np.array(a['joint_quaternions_actor']);tr,rot=bank.local_trs(points,q);path='/World/Actors/'+aid;UsdGeom.Xformable(stage.GetPrimAtPath(path)).GetOrderedXformOps()[0].Set(matrix);animation=UsdSkel.Animation.Get(stage,path+'/FilmAnimation');animation.GetTranslationsAttr().Set(Vt.Vec3fArray.FromNumpy(tr.astype(np.float32)));animation.GetRotationsAttr().Set(Vt.QuatfArray([Gf.Quatf(float(v[3]),Gf.Vec3f(*map(float,v[:3]))) for v in rot]))
   UsdGeom.Xformable(stage.GetPrimAtPath('/World/Metro/StationGate')).GetOrderedXformOps()[0].Set(Gf.Vec3d(-6.35,0,0))
  tl.set_current_time(t if args.mode=='kit' else 0);tl.commit();timecode=Usd.TimeCode(t*24);matrix=UsdGeom.XformCache(timecode).GetLocalToWorldTransform(source_camera.GetPrim());xf.GetOrderedXformOps()[0].Set(matrix)
  for name in ['focalLength','horizontalAperture','verticalAperture','clippingRange']:camera.GetPrim().GetAttribute(name).Set(source_camera.GetPrim().GetAttribute(name).Get(timecode))
  if rec is None:rec=Recorder(out,(1920,1080),gpu_index=args.gpu)
  for _ in range(8):rec.step(0)
  Image.fromarray(np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3]).save(out/f'reference_{t:.1f}.png');metadata.append({'story_time_s':t,'supplied_source_frame_24fps':t*24,'formal_source_frame_30fps':t*30 if args.mode=='formal' else None,'camera_matrix':np.asarray(matrix).tolist(),'focal_mm':camera.GetFocalLengthAttr().Get(),'mode':args.mode,'scope':'exact camera from supplied USD; formal poses read from actual movie; kit is cached low-poly previs, not Native people'})
 (out/'completed.json').write_text(json.dumps({'opened_input':str(chosen),'source_camera':'/Metro/Cameras/ShotCamera','stills':metadata,'positive_simulation_steps':0},indent=2))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 app.close()
raise SystemExit(code)
