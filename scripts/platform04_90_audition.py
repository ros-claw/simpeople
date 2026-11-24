"""Six isolated layers on one production actor, two matched camera angles."""
import argparse,json,os,sys,shutil,hashlib,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);p.add_argument('--preview',action='store_true');args=p.parse_args()
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,out/'source_snapshot'/Path(__file__).name);sys.path.insert(0,str(out/'source_snapshot/src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});rec=None;code=0
try:
 import omni.usd,omni.timeline,numpy as np
 from pxr import UsdGeom,UsdLux,Gf
 from PIL import Image
 from simpeople.backends.native.platform04_90_animation import DirectorMotion,DirectorActor
 from simpeople.backends.native.platform04_scene import aim
 from simpeople.backends.native.deadweight_set import box
 from simpeople.backends.native.recording import Recorder
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();UsdGeom.Xform.Define(stage,'/World');stage.SetDefaultPrim(stage.GetPrimAtPath('/World'));UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z');stage.SetTimeCodesPerSecond(30)
 box(stage,'/World/Ground',(20,0,-.08),(100,30,.16),(.28,.32,.33),0,.8)
 for i,x in enumerate(range(-10,70)):box(stage,f'/World/Marks/M{i}',(x,0,.001),(.015,10,.003),(.15,.19,.20),0,.8)
 dome=UsdLux.DomeLight.Define(stage,'/World/Dome');dome.CreateIntensityAttr(500)
 sun=UsdLux.DistantLight.Define(stage,'/World/Sun');sun.CreateIntensityAttr(1800);sun.AddRotateXYZOp().Set(Gf.Vec3f(25,-30,-20))
 cam=UsdGeom.Camera.Define(stage,'/World/Camera');cam.AddTransformOp();cam.CreateHorizontalApertureAttr(36);cam.CreateVerticalApertureAttr(20.25);cam.CreateClippingRangeAttr(Gf.Vec2f(.05,180))
 bank=DirectorMotion(ROOT);actor=DirectorActor(stage,'/World/Actor',bank,(.76,.43,.055),bank.rig['source_uri'])
 variants=['jog','sdk','old_leg_ik','old_infected','gaze','final'];fits={}
 for name in variants:fits[name]=actor.fit(name)
 report={'jog_period':bank.jog_period,'jog_loop_error_m':bank.jog_loop_error_m,'jog_calibration':bank.jog_calibration,'variants':{name:{k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in f.items() if k!='feet'} for name,f in fits.items()},'scope':'matched production actor; Jog and Sprint source phases normalized to a common gait phase for shape comparison; actual unretimed Native Jog retained in its capture run; no infection layer in final healthy variant'}
 (out/'motion_fit.json').write_text(json.dumps(report,indent=2));print('fits',[(k,round(v['stride_m'],3)) for k,v in fits.items()],flush=True)
 tl=omni.timeline.get_timeline_interface();tl.set_auto_update(False);tl.set_time_codes_per_second(30);tl.set_end_time(1000);tl.play();tl.commit();rec=Recorder(out,(1920,1080),gpu_index=args.gpu);trace=[]
 for angle in ['side','front45']:
  for variant in variants:
   for f in ([0,8,16,30,59,90] if args.preview else range(120)):
    # Shared root distance and stride phase: compare shape without giving one
    # variant an advantageous speed or phase. Retiming is explicit above.
    common_period=bank.jog_period;phase=f%common_period;clip_phase=phase/common_period*fits[variant]['period'];fit=fits['jog'];cycles,part=divmod(f,common_period);distance=cycles*fit['stride_m']+float(fit['travel'][part]);pose=bank.pose(clip_phase,variant);lift=actor.ground_lift(variant,clip_phase)
    actor.safe_update(pose,[distance,0,0],0,lift)
    eye=[distance,5.2,1.18] if angle=='side' else [distance+3.6,3.6,1.3];aim(stage,eye,[distance,0,.95],41)
    if f==0:
     for _ in range(6):rec.step(0)
     if not args.preview:rec.control({'mode':'start'})
    rec.step(1/30);rec.step(0);rgb=np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3]
    if float((rgb.mean(2)>15).mean())<.1:raise RuntimeError('audition camera black')
    if not args.preview:rec.capture(tl.get_current_time(),{'variant':variant,'angle':angle,'phase_frame':f})
    lengths={}
    for a,b in [('R_Upperarm','R_Forearm'),('R_Forearm','R_Hand'),('R_Thigh','R_Calf'),('R_Calf','R_Foot')]:lengths[a+'/'+b]=float(np.linalg.norm(actor.joint_p[bank.index(a)]-actor.joint_p[bank.index(b)]))
    trace.append({'angle':angle,'variant':variant,'source_tick':f,'shared_phase':phase,'shared_root_distance_m':distance,'sim_time_s':tl.get_current_time(),'joints_actor_m':actor.joint_p.tolist(),'quaternions_actor':actor.joint_q.tolist(),'long_bones_m':lengths,'rgb_sha256':hashlib.sha256(rgb.tobytes()).hexdigest()})
    if f in [0,8,16,30,59,90]:Image.fromarray(rgb).save(out/f'{angle}_{variant}_{f:03d}.png')
   if not args.preview:rec.close()
 (out/'frames.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in trace))
 limits={}
 for variant in variants:
  rs=[r for r in trace if r['variant']==variant];limits[variant]={k:{'min_m':min(r['long_bones_m'][k] for r in rs),'max_m':max(r['long_bones_m'][k] for r in rs)} for k in rs[0]['long_bones_m']}
 assert all(v['max_m']-v['min_m']<1e-5 for bones in limits.values() for v in bones.values()),limits
 (out/'bone_lengths.json').write_text(json.dumps(limits,indent=2));(out/'completed.json').write_text(json.dumps({'preview':args.preview,'variants':variants,'angles':['side','front45'],'frames':len(trace),'bone_length_invariant_passed':True,'runtime_scope':'Isaac 6.2 actual RGB; exclusive cache test, phase-normalized shape audition, not Native concurrent control'},indent=2));stage.GetRootLayer().Export(str(out/'scene.usda'))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 app.close()
raise SystemExit(code)
