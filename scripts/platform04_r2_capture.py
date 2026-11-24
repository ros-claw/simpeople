"""Capture R2 performance trials in the installed Isaac 6.2, unique take only."""
import argparse,hashlib,json,os,shutil,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--mode',choices=['identity','duo','trio','parallel','camera_only','bottle'],default='trio');p.add_argument('--case',default='human_fast');p.add_argument('--angle',choices=['side','front45'],default='side');p.add_argument('--body',type=int,default=0);p.add_argument('--camera',choices=['new','full'],default='new');p.add_argument('--gpu',type=int,default=2);p.add_argument('--preview',action='store_true');p.add_argument('--size',default='1920x1080');args=p.parse_args()
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));snap=out/'source_snapshot';shutil.copytree(ROOT/'src/simpeople',snap/'src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,snap/Path(__file__).name);shutil.copytree(ROOT/'.runtime/platform04_r2/kit',snap/'r2_kit');sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});rec=None;code=0
try:
 import omni.usd,omni.timeline,omni.replicator.core as rep,numpy as np
 from PIL import Image
 from simpeople.backends.native.platform04_r2_director import R2Director,audition_scene
 from simpeople.backends.native.platform04_90_scene import create_director_scene
 from simpeople.backends.native.platform04_90_director import Director90
 from simpeople.backends.native.platform04_90_observation import PerformanceReadback
 from simpeople.backends.native.recording import Recorder
 from simpeople.backends.native.platform04_scene import aim
 from pxr import UsdGeom
 resolution=tuple(map(int,args.size.split('x')));omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage()
 if args.mode=='identity':audition_scene(stage);scene={}
 else:scene=create_director_scene(stage,ROOT)
 if args.mode=='camera_only':director=Director90(stage,scene,ROOT,out,'door');duration=10.
 elif args.mode=='bottle':
  from simpeople.backends.native.platform04_r2_bottle import BottleDirector
  director=BottleDirector(stage,scene,ROOT,out);duration=director.duration
 else:director=R2Director(stage,scene,ROOT,out,args.mode,args.case,args.angle,args.body,args.camera);duration=director.duration
 frames=round(duration*30);first=1590 if args.mode=='camera_only' else 0;director.update(first)
 observer=PerformanceReadback(ROOT,out,director.actors,resolution);director.update(first)
 timeline=omni.timeline.get_timeline_interface();timeline.set_auto_update(False);timeline.set_time_codes_per_second(30);timeline.set_end_time(1000);timeline.play();timeline.commit();rec=Recorder(out,resolution,gpu_index=args.gpu);ids=rep.AnnotatorRegistry.get_annotator('instance_id_segmentation_fast',init_params={'colorize':False},device='cpu');ids.attach([rec.product])
 for _ in range(8):rec.step(0)
 keys=([0,15,30,45,60,75,90,105,120,135,149] if args.mode=='identity' else [0,25,40,52,65,75,90,110,135,150,175,195,225,270,300,330,359] if args.mode=='bottle' else [0,45,75,105,125,135,145,155,170,180,195,210,225,240,270,299]);take_keys=set(keys);minimum={};ranges={};previous_rgb=None;duplicates=0;start=time.monotonic();log=(out/'frames.jsonl').open('w');vislog=(out/'actor_frames.jsonl').open('w')
 if not args.preview:rec.control({'mode':'start'})
 previous_shot=None
 for f in (keys if args.preview else range(frames)):
  row=director.update(first+f)
  if args.mode=='camera_only':
   director.camera=args.camera;R2Director.set_camera(director,f/30,row);cam=stage.GetPrimAtPath('/World/Camera');row['camera_matrix']=np.asarray(UsdGeom.Xformable(cam).GetOrderedXformOps()[0].Get()).tolist();row['camera_focal_mm']=float(cam.GetAttribute('focalLength').Get());row['shot']='R1_camera_only'
  if row['shot']!=previous_shot:
   for _ in range(6):rec.step(0)
  previous_shot=row['shot'];rec.step(1/30);rec.step(0);rgb=np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3];rgb_hash=hashlib.sha256(rgb.tobytes()).hexdigest();duplicates+=int(rgb_hash==previous_rgb);previous_rgb=rgb_hash
  if float((rgb.mean(2)>8).mean())<.05:raise RuntimeError(f'black shot at {f}')
  if not args.preview:rec.capture(timeline.get_current_time(),{'source_tick':f,'mode':args.mode,'controller':'exclusive R2 film score' if args.mode!='camera_only' else 'unchanged R1 cache; camera-only diagnostic'})
  data=ids.get_data(device='cpu');id_image=np.asarray(data['data']).reshape(resolution[1],resolution[0]);labels=data['info']['idToLabels'];row.update({'output_frame':f,'sim_time_s':timeline.get_current_time(),'wall_time_s':time.time(),'rgb_sha256':rgb_hash})
  for aid,actor in director.actors.items():
   actual=observer.read_actor(aid);r=row['actors'][aid];r['actual_world_joints_m']=actual['joints_world_m'].tolist();r['actual_root_matrix']=actual['root_matrix'].tolist();parts=dict(zip(actual['part_paths'],actual['parts']));shoes=np.concatenate([parts[str(m['prim'].GetPath())][m['feet']] for m in actor.meshes if str(m['prim'].GetPath()) in parts and m['feet'].any()]);r['actual_shoe_min_z_m']=float(shoes[:,2].min());minimum[aid]=min(minimum.get(aid,1e9),r['actual_shoe_min_z_m'])
   if hasattr(actor,'soles'):
    for side,sole in actor.soles.items():
     point=parts[sole.path][sole.vertex]
     if side in r.get('support',{}):r['support'][side]['actual_point_world_m']=point.tolist()
   bones={}
   for side in ['L','R']:
    for a,b in [('Upperarm','Forearm'),('Forearm','Hand'),('Thigh','Calf'),('Calf','Foot')]:
     key=side+'_'+a+'/'+side+'_'+b;value=float(np.linalg.norm(actual['joints_world_m'][actor.cache.index(side+'_'+a)]-actual['joints_world_m'][actor.cache.index(side+'_'+b)]));bones[key]=value;ranges.setdefault((aid,key),[value,value]);ranges[aid,key]=[min(ranges[aid,key][0],value),max(ranges[aid,key][1],value)]
   r['actual_long_bones_m']=bones
   visibility=observer.visibility(aid,actual,id_image,labels,row['camera_matrix'],row['camera_focal_mm'],args.run_id+':'+row['shot'],f,r);vislog.write(json.dumps(visibility)+'\n')
  if f in take_keys:
   Image.fromarray(rgb).save(out/f'frame_{f:04d}.png');np.save(out/f'frame_{f:04d}_ids.npy',id_image);(out/f'frame_{f:04d}_labels.json').write_text(json.dumps(data['info']));print('R2 frame',f,'states',{aid:a.get('state',a.get('behavior')) for aid,a in row['actors'].items()},'shoe_min',minimum,flush=True)
  log.write(json.dumps(row)+'\n')
 log.close();vislog.close();info=rec.close();worst=max((hi-lo)/max(lo,1e-8) for lo,hi in ranges.values());assert worst<1e-4,worst
 (out/'bone_invariants.json').write_text(json.dumps({'max_relative_range':worst,'actual_USD_FK':True,'ranges':{aid:{k:{'min_m':v[0],'max_m':v[1]} for (who,k),v in ranges.items() if who==aid} for aid in director.actors}},indent=2));(out/'actual_roster.json').write_text(json.dumps({'actors':[{'id':aid} for aid in director.actors]},indent=2));(out/'completed.json').write_text(json.dumps({'preview':args.preview,'mode':args.mode,'case_private':args.case,'body':args.body,'angle':args.angle,'camera':args.camera,'encoded_frames':info['frames'],'sampled_frames':len(keys) if args.preview else frames,'duration_s':duration,'resolution':resolution,'actors':list(director.actors),'capture_wall_s':time.monotonic()-start,'actual_shoe_min_z_m':minimum,'adjacent_rgb_duplicates':duplicates,'long_bones_invariant':True,'human_reviewers':0,'autonomous_infection_pursuit':False,'scope':'authored R2 performance; pose invariants and RGB do not prove role recognition or scariness'},indent=2));stage.GetRootLayer().Export(str(out/'scene.usda'))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 app.close()
raise SystemExit(code)
