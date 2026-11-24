"""Same-SOMA-rig USD playback gate. The SOMA probe has no Behavior writer."""
import argparse,hashlib,json,math,shutil,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--data-dir',required=True);p.add_argument('--gpu',type=int,default=3);args=p.parse_args()
data=Path(args.data_dir).resolve();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir()
for name in ['src','configs','schemas']:shutil.copytree(ROOT/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copytree(data,snap/'inputs');(snap/'reports').mkdir();shutil.copy2(ROOT/'reports/capability_matrix.json',snap/'reports/capability_matrix.json');shutil.copy2(__file__,snap/Path(__file__).name)
(out/'probe_config.json').write_text(json.dumps(vars(args),indent=2)+'\n')
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n')
sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
engine=journal=recorder=stream=None;code=0
try:
 import numpy as np
 import omni.kit.app,omni.usd
 from pxr import Usd,UsdGeom,UsdSkel,Gf,Vt
 manager=omni.kit.app.get_app().get_extension_manager()
 for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:assert manager.set_extension_enabled_immediate(ext,True)
 from simpeople.backends.native.scene import build_scene
 from simpeople.backends.native.reservations import ReservationNativeBackend
 from simpeople.backends.native.recording import Recorder
 from simpeople.core.engine import Engine
 from simpeople.core.journal import Journal
 from simpeople.motion.rig import validate_rig,rig_digest,forward_kinematics
 rig=json.loads((snap/'inputs/rig.json').read_text());validate_rig(rig);assert rig_digest(rig)==rig['rig_sha256']
 source=Path(rig['source_usd']);assert hashlib.sha256(source.read_bytes()).hexdigest()==rig['source_sha256']
 omni.usd.get_context().new_stage();sem=build_scene(False);stage=omni.usd.get_context().get_stage()
 model=UsdSkel.Root.Define(stage,'/World/SOMAProbe/Model').GetPrim();model.GetReferences().AddReference(str(source))
 # Original geometry is Y-up centimetres; this is the sole geometry basis transform.
 wrapper=Gf.Matrix4d().SetScale(rig['source_meters_per_unit'])*Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1,0,0),90))
 UsdGeom.Xformable(model).MakeMatrixXform().Set(wrapper)
 skeleton=next(UsdSkel.Skeleton(prim) for prim in Usd.PrimRange(model) if prim.IsA(UsdSkel.Skeleton));joint_paths=list(skeleton.GetJointsAttr().Get())
 assert [n.rsplit('/',1)[-1] for n in joint_paths]==rig['joint_names']
 assert all(not any('BehaviorAgentAPI' in s for s in prim.GetAppliedSchemas()) for prim in Usd.PrimRange(model))
 anim=UsdSkel.Animation.Define(stage,'/World/SOMAProbe/Playback');anim.CreateJointsAttr(joint_paths)
 UsdSkel.BindingAPI.Apply(skeleton.GetPrim()).CreateAnimationSourceRel().SetTargets([anim.GetPath()])
 for matrix in skeleton.GetRestTransformsAttr().Get():assert np.max(np.abs(np.asarray(Gf.Transform(matrix).GetScale())-1))<1e-5
 backend=ReservationNativeBackend(ROOT,sem,False,config_dir=snap/'configs',capability_file=snap/'reports/capability_matrix.json');backend.enable_corridor_profile()
 journal=Journal(out,{'scenario':'soma_same_rig_readback','gpu':args.gpu,'width':1920,'height':1080,'warmup_wall_s':30});engine=Engine(backend,journal)
 def call(method,params):return engine.call(method,{'controller_id':'soma-probe',**params})
 call('spawn',{'request_id':'spawn_witness','actor_id':'witness','spawn_anchor':[-5,-3,0]})
 for _ in range(5):app.update()
 assert backend.nav.start_navmesh_baking_and_wait()
 timeline=backend.timeline;timeline.set_time_codes_per_second(30);timeline.set_end_time(100000);timeline.set_auto_update(False);timeline.set_play_every_frame(True);timeline.play()
 for _ in range(120):
  timeline.forward_one_frame();app.update()
  if backend.observe(engine.actors['witness']['handle']).get('ready'):break
 engine.tick(timeline.get_current_time())
 witness=call('move_to',{'request_id':'witness_move','actor_id':'witness','target':[-5,0,0],'timeout_s':15})['task_id']
 all_poses=[];labels=[]
 fixture=json.loads((snap/'inputs/fixture_manifest.json').read_text())
 for entry in fixture['checks']:
  path=snap/'inputs'/(entry['name']+'.npz');assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256']
  with np.load(path,allow_pickle=False) as value:poses=value['local_poses']
  all_poses.extend(poses);labels.extend([entry['name']]*len(poses))
 poses=np.asarray(all_poses);expected=forward_kinematics(poses,rig['parents']);start_tick=round(timeline.get_current_time()*30)+1
 frame=UsdGeom.XformCache().GetLocalToWorldTransform(skeleton.GetPrim());inv=frame.GetInverse();orientation=Gf.Transform(frame).GetRotation().GetQuat().GetInverse()
 for index,pose in enumerate(poses):
  values=[Gf.Vec3f(*map(float,p[:3]/rig['source_meters_per_unit'])) for p in pose]
  values[0]=Gf.Vec3f(*inv.Transform(Gf.Vec3d(*map(float,pose[0,:3]))))
  rotations=[Gf.Quatf(float(p[6]),Gf.Vec3f(*map(float,p[3:6]))) for p in pose]
  q=orientation*Gf.Quatd(float(pose[0,6]),Gf.Vec3d(*map(float,pose[0,3:6])));rotations[0]=Gf.Quatf(q)
  time=Usd.TimeCode(start_tick+index);anim.CreateTranslationsAttr().Set(Vt.Vec3fArray(values),time);anim.CreateRotationsAttr().Set(Vt.QuatfArray(rotations),time)
  anim.CreateScalesAttr().Set(Vt.Vec3hArray([Gf.Vec3h(1,1,1)]*len(values)),time)
 cache=UsdSkel.Cache();root=next(UsdSkel.Root(prim) for prim in Usd.PrimRange(model) if prim.IsA(UsdSkel.Root));cache.Populate(root,Usd.PrimDefaultPredicate);query=cache.GetSkelQuery(skeleton)
 assert query.GetAnimQuery().GetPrim().GetPath()==anim.GetPath()
 camera=UsdGeom.Xformable(stage.GetPrimAtPath('/World/Camera'));camera.GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(3,-5,2.4),Gf.Vec3d(0,0,1),Gf.Vec3d(0,0,1)).GetInverse())
 recorder=Recorder(out,(1920,1080),gpu_index=args.gpu)
 for _ in range(5):recorder.step(0)
 recorder.control({'mode':'start'});stream=(out/'soma_readback.jsonl').open('w');errors=[];max_position=0;max_angle=0;origin=timeline.get_current_time()
 for index in range(len(poses)):
  recorder.step(1/30);engine.tick(timeline.get_current_time());tick=round(timeline.get_current_time()*30)
  if tick!=start_tick+index:raise AssertionError(('simulation/frame mismatch',tick,start_tick+index))
  transforms=query.ComputeJointWorldTransforms(UsdGeom.XformCache(Usd.TimeCode(tick)))
  actual=[]
  for matrix in transforms:
   t=Gf.Transform(matrix);q=t.GetRotation().GetQuat();actual.append([*t.GetTranslation(),*q.GetImaginary(),q.GetReal()])
  actual=np.asarray(actual);position=float(np.max(np.linalg.norm(actual[:,:3]-expected[index,:,:3],axis=-1)))
  dot=np.abs(np.sum(actual[:,3:]*expected[index,:,3:],axis=-1));angular=float(np.degrees(2*np.arccos(np.clip(dot,0,1))).max())
  max_position=max(max_position,position);max_angle=max(max_angle,angular)
  if position>.001 or angular>.1:errors.append({'frame':index,'fixture':labels[index],'position_error_m':position,'rotation_error_deg':angular})
  identity={'source_tick':journal.frames,'relative_sim_time':timeline.get_current_time()-origin};recorder.capture(timeline.get_current_time(),identity);journal.sample(engine,identity)
  stream.write(json.dumps({'frame':index,'source_tick':tick,'fixture':labels[index],'sim_time':timeline.get_current_time(),'actual_world_pose':actual.tolist(),'position_error_m':position,'rotation_error_deg':angular})+'\n')
 for _ in range(300):
  if engine.tasks[witness]['status'] in {'succeeded','failed','cancelled'}:break
  recorder.step(1/30);engine.tick(timeline.get_current_time());identity={'source_tick':journal.frames,'relative_sim_time':timeline.get_current_time()-origin};recorder.capture(timeline.get_current_time(),identity);journal.sample(engine,identity)
 stream.close();stream=None
 passed=not errors and engine.tasks[witness]['status']=='succeeded';assert hashlib.sha256(source.read_bytes()).hexdigest()==rig['source_sha256']
 passed=passed and (not fixture.get('model_used') or fixture.get('all_model_cases_passed') is True)
 journal.write('same_rig_acceptance.json',{'passed':passed,'model_used':fixture.get('model_used',False),'behavior_on_soma':False,'rig_sha256':rig['rig_sha256'],'fixtures':fixture['checks'],'samples':len(poses)*len(joint_paths),'maximum_position_error_m':max_position,'maximum_rotation_error_deg':max_angle,'errors':errors,'witness_task':engine.public(engine.tasks[witness]),'limits':'Independent SOMA USD animation readback; not native Behavior generation playback or PhysX contact.'})
 journal.write('asset_manifest.json',backend.assets);journal.write('measurement_end_state.json',engine.cmd_get_state({}));journal.write('completed.json',{'harness_completed':True,'functional_expected_matched':passed,'frames':recorder.frames,'duration_s':timeline.get_current_time()-origin})
 print('SOMA_SAME_RIG_DONE',passed,max_position,max_angle,flush=True)
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if stream:stream.close()
 if recorder:recorder.close()
 if engine:
  for aid in list(engine.actors):engine.abort_actor(aid,'process_shutdown')
  engine.backend.close();journal.finish(engine,exit_code=code)
 app.close(exit_code=code)
raise SystemExit(code)
