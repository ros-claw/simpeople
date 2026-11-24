"""Offline SDK inverse-retarget probe using four previously executed samples."""
import argparse,hashlib,json,math,shutil,sys
from pathlib import Path
from collections import defaultdict

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--native-run',required=True);p.add_argument('--clip-dir',required=True);p.add_argument('--model-rig',required=True);p.add_argument('--gpu',type=int,default=3);p.add_argument('--phase',default='mb_stand');p.add_argument('--history-name',default='native_pose_history.jsonl');p.add_argument('--module-converter',action='store_true');args=p.parse_args()
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir()
for name in ['src','configs']:shutil.copytree(ROOT/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copy2(__file__,snap/Path(__file__).name);shutil.copy2(Path(args.clip_dir)/'soma_native.usda',snap/'soma_native.usda');shutil.copy2(args.model_rig,snap/'rig.json')
native=ROOT/'runs'/args.native_run;history=native/args.history_name;groups=defaultdict(list)
for line in history.open():
 r=json.loads(line)
 if args.phase=='all' or r['phase']==args.phase and (args.phase!='mb_stand' or r['actual_observation']['action']=='mb_stand'):
  key=r['actor_id']+'__'+r['phase'] if args.phase=='all' else r['actor_id'];groups[key].append(r)
frames={a:(rows[-8:-4] if len(rows)>=8 else rows[-4:]) for a,rows in groups.items()};assert frames and all(len(rows)==4 for rows in frames.values())
(snap/'executed_samples.json').write_text(json.dumps(frames)+'\n');shutil.copy2(native/'asset_manifest.json',snap/'asset_manifest.json')
(out/'input_provenance.json').write_text(json.dumps({'native_run':args.native_run,'actual_history_sha256':hashlib.sha256(history.read_bytes()).hexdigest(),'context_source':'actual Behavior SDK world joint readback, previously executed'},indent=2)+'\n')
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n')
sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});code=0
try:
 import numpy as np
 import carb,omni.usd,omni.kit.app
 from pxr import Usd,UsdSkel,UsdGeom
 manager=omni.kit.app.get_app().get_extension_manager();assert manager.set_extension_enabled_immediate('omni.anim.behavior.core',True)
 import omni.anim.retarget.core as retarget
 from simpeople.backends.native.motion_import import prepare_soma_rig
 from simpeople.motion.rig import world_to_local,forward_kinematics,convert_root,inverse,validate_poses,project_to_model,expand_from_model,rotate,multiply
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();UsdGeom.Xform.Define(stage,'/World');stage.SetDefaultPrim(stage.GetPrimAtPath('/World'));UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z')
 prepared=prepare_soma_rig(snap/'soma_native.usda',out/'prepared_rig.usda');target=UsdSkel.Root.Define(stage,'/World/Soma');target.GetPrim().GetReferences().AddReference(str(out/'prepared_rig.usda'))
 target_skel=UsdSkel.Skeleton(stage.GetPrimAtPath('/World/Soma/Skeleton'));target_parents=list(UsdSkel.Topology(target_skel.GetJointsAttr().Get()).GetParentIndices());rig=json.loads((snap/'rig.json').read_text());results={}
 for actor,rows in frames.items():
  times=[r['sim_time'] for r in rows];assert all(abs(b-a-1/30)<1e-6 for a,b in zip(times,times[1:]))
  base_actor=rows[-1]['actor_id'];asset_id='default' if base_actor=='operator' else 'female_adult_business_02';asset=next(a for a in json.loads((snap/'asset_manifest.json').read_text()) if a['asset_id']==asset_id)
  source=UsdGeom.Xform.Define(stage,'/World/Source_'+actor);source.GetPrim().GetReferences().AddReference(asset['source_uri'])
  skeleton=next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(source.GetPrim()) if p.IsA(UsdSkel.Skeleton));joints=list(skeleton.GetJointsAttr().Get());assert list(map(str,joints))==rows[0]['joint_paths']
  parents=list(UsdSkel.Topology(joints).GetParentIndices());world=validate_poses([r['world_pose'] for r in rows],len(joints));local=world_to_local(world,parents)
  source_stage=Usd.Stage.Open(asset['source_uri']);mpu=UsdGeom.GetStageMetersPerUnit(source_stage);yup=UsdGeom.GetStageUpAxis(source_stage)=='Y';basis=np.array([math.sqrt(.5),0,0,math.sqrt(.5)])
  if yup:local=convert_root(local,inverse(basis))
  local[:,:,:3]/=mpu
  # Retarget relative motion, not a world offset scaled by body height.
  # The public world origin is restored once after conversion, and its inverse
  # once on return. This is offline root-frame normalization, not a live warp.
  source_origin=local[0,0,:3].copy();local[:,0,:3]-=source_origin
  to_soma=retarget.RetargetController(None,str(skeleton.GetPath()),-1,str(target_skel.GetPath()));to_native=retarget.RetargetController(None,str(target_skel.GetPath()),-1,str(skeleton.GetPath()))
  (out/(actor+'_sdk_contract.json')).write_text(json.dumps({'methods':{name:str(getattr(to_soma,name).__doc__) for name in dir(to_soma) if not name.startswith('_')},'retarget_settings':{key:carb.settings.get_settings().get('/persistent/exts/omni.anim.retarget.core/'+key) for key in ['enableFeetIK','feetIKActivation','feetIKTags']}},indent=2)+'\n')
  renormalization=[]
  def run(controller,poses):
   output=[]
   for pose in poses:
    translations,rotations=controller.retarget([carb.Float3(*map(float,v[:3])) for v in pose],[carb.Float4(*map(float,v[3:])) for v in pose])
    output.append([[*p,*q] for p,q in zip(translations,rotations)])
   array=np.asarray(output,dtype=float)
   np.save(out/(actor+'_sdk_raw_'+str(array.shape[1])+'_'+str(len(renormalization))+'.npy'),array)
   norms=np.linalg.norm(array[:,:,3:],axis=-1);error=float(np.abs(norms-1).max());renormalization.append(error)
   if not np.isfinite(array).all() or error>.01:raise ValueError('SDK rotation is outside numeric normalization bound')
   array[:,:,3:]/=norms[:,:,None]
   return validate_poses(array,len(output[0]))
  soma=run(to_soma,local);restored=run(to_native,soma);restored[:,0,:3]+=source_origin;restored[:,:,:3]*=mpu
  if yup:restored=convert_root(restored,basis)
  back=forward_kinematics(restored,parents);position_error=np.linalg.norm(back[:,:,:3]-world[:,:,:3],axis=-1)
  soma_world=forward_kinematics(soma,target_parents);full=soma[:,1:,:].copy();full[:,0]=soma_world[:,1];full[:,:,:3]*=.01;full=convert_root(full,basis);full[:,0,:3]+=world[0,0,:3];model=project_to_model(full,rig)
  expanded=expand_from_model(model,rig);expanded[:,0,:3]-=world[0,0,:3];expanded=convert_root(expanded,inverse(basis));expanded[:,:,:3]/=.01
  projected=soma.copy();projected[:,1:,:]=expanded
  root_inverse=inverse(soma[:,0,3:]);projected[:,1,:3]=rotate(root_inverse,expanded[:,0,:3]-soma[:,0,:3]);projected[:,1,3:]=multiply(root_inverse,expanded[:,0,3:])
  projected_native=run(to_native,projected);projected_native[:,0,:3]+=source_origin;projected_native[:,:,:3]*=mpu
  if yup:projected_native=convert_root(projected_native,basis)
  model_back=forward_kinematics(projected_native,parents);model_error=float(np.linalg.norm(model_back[:,:,:3]-world[:,:,:3],axis=-1).max())
  np.savez(out/(actor+'_roundtrip.npz'),actual_world=world,restored_world=back,model_restored_world=model_back,soma_local=full,model_context=model)
  root_error=float(np.linalg.norm(full[:,0,:2]-world[:,1,:2],axis=-1).max());maximum=float(position_error.max())
  results[actor]={'passed':maximum<=.03 and model_error<=.03 and root_error<=.03,'source_asset_id':asset_id,'source_asset_file_sha256':hashlib.sha256(Path(asset['source_uri']).read_bytes()).hexdigest(),'frames':4,'sample_times_s':times,'actual_joint_count':len(joints),'max_roundtrip_joint_position_error_m':maximum,'max_model30_roundtrip_joint_position_error_m':model_error,'model_root_xy_error_m':root_error,'actual_actor_instance_id':rows[0]['actor_instance_id'],'frame_origin_world_m':world[0,0,:3].tolist(),'sdk_rotation_renormalization_max_norm_errors':renormalization}
  if args.module_converter:
   import copy,threading
   from types import SimpleNamespace
   from simpeople.motion.pose_bridge import ExecutedPoseHistory,PoseBridge,identity
   from simpeople.backends.native.pose_bridge import NativePoseConverter
   main_thread=threading.get_ident()
   def assert_thread():assert threading.get_ident()==main_thread
   runtime={e['id'].split('-')[0]:e['id'] for e in manager.get_extensions() if e.get('enabled') and any(n in e['id'] for n in ['omni.anim.behavior.core','omni.anim.retarget.core'])}
   facade=SimpleNamespace(stage=stage,namespace='/World/BridgeModule',assert_thread=assert_thread,runtime_revision=runtime)
   converter=NativePoseConverter(facade,asset['source_uri'],snap/'soma_native.usda',rig,out/(actor+'_module'))
   history=ExecutedPoseHistory()
   for original in rows:
    observed=copy.deepcopy(original);observed['sample_source']='behavior_sdk';observed['source_asset_sha256']=results[actor]['source_asset_file_sha256'];history.record(observed)
   context=PoseBridge(rig,converter).to_model_context(history,converter.profile,identity(rows[-1]['task']),rows[-1]['sim_time'])
   converted=np.array(context['context']['local_poses']);deviation=float(np.abs(converted-full).max());context['source_reference_array_max_error']=deviation
   (out/(actor+'_model_context.json')).write_text(json.dumps(context,indent=2)+'\n')
   results[actor]['module_context_passed']=deviation<=1e-8;results[actor]['module_max_array_error']=deviation
   converter.close()
 result={'passed':all(r['passed'] for r in results.values()),'actors':results,'scope':'Offline inverse/forward SDK retarget of four actual previously executed standing samples. No online application, no arbitrary-pose or next-segment seam certification.'}
 (out/'pose_bridge_acceptance.json').write_text(json.dumps(result,indent=2)+'\n');print('POSE_BRIDGE_OFFLINE_DONE',result,flush=True)
 if args.module_converter:(out/'pose_bridge_module_acceptance.json').write_text(json.dumps({'passed':all(r.get('module_context_passed',False) for r in results.values()),'actors':results,'scope':'Reusable skeleton-only converter parity against the original SDK conversion on identical actual samples; does not clear native seam or online application gates.'},indent=2)+'\n')
 code=0 if result['passed'] else 2
except Exception:
 import traceback;(out/'failed.txt').write_text(traceback.format_exc());traceback.print_exc();code=1
finally:app.close(exit_code=code)
raise SystemExit(code)
