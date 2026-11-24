"""Read the old delivered take and its retake through actual UsdSkel FK.

No reinterpretation as a new pass. Existing image/ID samples are sparse; unseen
intervals remain unjudged. Full-length pose holds are candidates, not verdicts.
"""
import json,os,sys,shutil,argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid()}));shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,out/Path(__file__).name);sys.path.insert(0,str(out/'source_snapshot/src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':3,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});code=0
try:
 import omni.usd,numpy as np,math
 from pxr import Usd,UsdGeom,UsdSkel,Gf,Vt
 from simpeople.backends.native.local_pose import FixedAnatomy
 from simpeople.backends.native.deadweight_cinema import quat_apply
 source=ROOT/'runs/platform04-master-01';retake=ROOT/'runs/platform04-ending-02';original={r['source_tick']:r for r in map(json.loads,(source/'frames.jsonl').read_text().splitlines())};ending={r['source_tick']:r for r in map(json.loads,(retake/'frames.jsonl').read_text().splitlines())};names=json.loads((ROOT/'runs/platform04-motion-01/rig.json').read_text())['joints'];index=lambda n:next(i for i,x in enumerate(names) if x.rsplit('/',1)[-1]==n)
 omni.usd.get_context().open_stage(str(source/'scene.usda'))
 for _ in range(6):app.update()
 stage=omni.usd.get_context().get_stage();items={};all_rows=[];max_fk_error=0.;sample_main={0,1,30,60,75,82,84,90,127,132,180,210,240,270,298,330,345,360,362,390};sample_end=set(map(int,np.linspace(395,539,20).round()))
 for aid in original[0]['actors']:
  path='/World/Actors/'+aid;sk=next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(stage.GetPrimAtPath(path)) if p.IsA(UsdSkel.Skeleton));root=next(UsdSkel.Root(p) for p in Usd.PrimRange(stage.GetPrimAtPath(path)) if p.IsA(UsdSkel.Root));items[aid]=(path,sk,root,UsdSkel.Cache(),UsdSkel.Animation.Get(stage,path+'/FilmAnimation'))
 for f in range(540):
  row=ending[f] if f>=395 else original[f];frame={'source_run_id':retake.name if f>=395 else source.name,'source_tick':f,'actors':{}}
  for aid,r in row['actors'].items():
   path,sk,root,cache,anim=items[aid];yaw=r['yaw_rad'];matrix=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0,0,1),math.degrees(yaw)));matrix.SetTranslateOnly(Gf.Vec3d(*r['root_world_m']));m=np.asarray(matrix);p=(np.array(r['joints_world_m'])-m[3,:3])@m[:3,:3].T;q=np.array(r['joint_quaternions_actor']);anatomy=FixedAnatomy(names,p,q);local=anatomy.from_global(p,q,normalize_anatomy=False);UsdGeom.Xformable(stage.GetPrimAtPath(path)).GetOrderedXformOps()[0].Set(matrix);anim.GetTranslationsAttr().Set(Vt.Vec3fArray.FromNumpy(local.translations.astype(np.float32)));anim.GetRotationsAttr().Set(Vt.QuatfArray([Gf.Quatf(float(x[3]),Gf.Vec3f(*map(float,x[:3]))) for x in local.rotations]));cache.Clear();cache.Populate(root,Usd.PrimDefaultPredicate);query=cache.GetSkelQuery(sk);joint_matrices=query.ComputeJointSkelTransforms(Usd.TimeCode.Default());world=UsdGeom.XformCache().GetLocalToWorldTransform(sk.GetPrim());actual=np.array([(x*world).ExtractTranslation() for x in joint_matrices]);error=float(np.linalg.norm(actual-np.array(r['joints_world_m']),axis=1).max());max_fk_error=max(error,max_fk_error)
   canonical=(actual-m[3,:3])@m[:3,:3].T;bones={}
   for a,b in [('R_Upperarm','R_Forearm'),('R_Forearm','R_Hand'),('R_Thigh','R_Calf'),('R_Calf','R_Foot')]:bones[a+'/'+b]=float(np.linalg.norm(actual[index(a)]-actual[index(b)]))
   value={'root_m':list(matrix.ExtractTranslation()),'long_bones_m':bones,'local_body_m':canonical[[index(x) for x in ['Hip','Spine02','Head','L_Upperarm','L_Forearm','L_Hand','R_Upperarm','R_Forearm','R_Hand','L_Thigh','L_Calf','L_Foot','R_Thigh','R_Calf','R_Foot']]].tolist(),'source_position_vs_actual_USD_FK_max_error_m':error}
   if f in sample_main or f in sample_end:value['actual_world_joints_m']=actual.tolist()
   frame['actors'][aid]=value
  all_rows.append(frame)
  if f%90==0:print('baseline actual FK',f,max_fk_error,flush=True)
 (out/'actual_pose_readback.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in all_rows));summary={}
 for aid in items:
  summary[aid]={}
  for bone in all_rows[0]['actors'][aid]['long_bones_m']:
   v=np.array([r['actors'][aid]['long_bones_m'][bone] for r in all_rows]);summary[aid][bone]={'min_m':float(v.min()),'max_m':float(v.max()),'min_tick':int(v.argmin()),'min_over_max':float(v.min()/v.max())}
 holds=[]
 for aid in items:
  for start in range(395,504,9):
   a=all_rows[start:start+36];pts=np.array([r['actors'][aid]['local_body_m'] for r in a]);root=np.array([r['actors'][aid]['root_m'] for r in a]);body=float(np.linalg.norm(np.ptp(pts,axis=0),axis=1).max());travel=float(np.linalg.norm(np.ptp(root,axis=0)))
   if body<.01:holds.append({'actor':aid,'ticks':[start,start+35],'local_body_span_m':body,'root_span_m':travel,'visibility':'NOT_MEASURED over complete window; sparse existing masks insufficient','status':'pose-hold candidate; no visual verdict'})
 (out/'baseline_findings.json').write_text(json.dumps({'actual_USD_FK_frames':540,'actors':11,'original_full_readback_ticks':sorted(sample_main),'retake_full_readback_ticks':sorted(sample_end),'max_original_log_vs_actual_USD_FK_error_m':max_fk_error,'long_bone_ranges':summary,'retake_pose_hold_candidates':holds,'scope':'actual old delivered pose restoration with UsdSkel FK; no skeleton repair applied; sparse prior ID frames do not certify full visible freeze coverage'},indent=2));(out/'completed.json').write_text(json.dumps({'frames':540,'positive_simulation_steps':0,'actual_USD_FK_readback':True,'max_reconstruction_error_m':max_fk_error},indent=2))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:app.close()
raise SystemExit(code)
