"""Independent feature takes, actual Isaac 6.2 synchronized frame capture."""
import argparse,hashlib,json,os,shutil,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--part',required=True);p.add_argument('--gpu',type=int,default=2);p.add_argument('--preview',action='store_true');args=p.parse_args()
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));snap=out/'source_snapshot';shutil.copytree(ROOT/'src/simpeople',snap/'src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,snap/Path(__file__).name);sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});rec=None;code=0
try:
 import omni.usd,omni.timeline,omni.replicator.core as rep,numpy as np
 from PIL import Image
 from pxr import UsdGeom
 from simpeople.backends.native.platform04_feature_director import FeatureDirector
 from simpeople.backends.native.platform04_feature_score import SHOTS
 from simpeople.backends.native.platform04_90_scene import create_director_scene
 from simpeople.backends.native.platform04_90_observation import PerformanceReadback
 from simpeople.backends.native.recording import Recorder
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();scene=create_director_scene(stage,ROOT);director=FeatureDirector(stage,scene,ROOT,out,args.part);first=round(director.first*30);last=round(director.last*30);director.update(first);observer=PerformanceReadback(ROOT,out,director.actors);director.update(first)
 timeline=omni.timeline.get_timeline_interface();timeline.set_auto_update(False);timeline.set_time_codes_per_second(30);timeline.set_end_time(1000);timeline.play();timeline.commit();rec=Recorder(out,(1920,1080),gpu_index=args.gpu);ids=rep.AnnotatorRegistry.get_annotator('instance_id_segmentation_fast',init_params={'colorize':False},device='cpu');ids.attach([rec.product])
 for _ in range(8):rec.step(0)
 keys={first,last-1}
 for lo,hi,shot in SHOTS:
  if first<=lo*30<last:
   keys.update([round(lo*30),round((lo+hi)/2*30),round(hi*30)-1])
 if args.part=='door':keys.update([1725,1735,1745,1755,1765,1775,1785,1795,1805,1815,1830])
 if args.part=='after':keys.update([1955,1970,1985,2000,2015,2040])
 keys=sorted(k for k in keys if first<=k<last)
 if not args.preview:rec.control({'mode':'start'})
 log=(out/'frames.jsonl').open('w');vislog=(out/'actor_frames.jsonl').open('w');start=time.monotonic();previous_shot=None;previous_rgb=None;duplicates=0;ranges={};probes=[];minimum={};frozen={};seen_pixels={aid:0 for aid in director.actors}
 for f in (keys if args.preview else range(first,last)):
  row=director.update(f)
  if row['shot']!=previous_shot:
   for _ in range(6):rec.step(0)
  previous_shot=row['shot'];rec.step(1/30);rec.step(0);rgb=np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3];digest=hashlib.sha256(rgb.tobytes()).hexdigest();duplicates+=int(digest==previous_rgb);previous_rgb=digest
  if float((rgb.mean(2)>8).mean())<.05:raise RuntimeError(f'black/blocked shot at {f}')
  if not args.preview:rec.capture(timeline.get_current_time(),{'source_tick':f,'shot':row['shot'],'part':args.part,'root_owner':'exclusive feature film score'})
  data=ids.get_data(device='cpu');id_image=np.asarray(data['data']).reshape(1080,1920);labels=data['info']['idToLabels'];row.update({'output_frame':f-first,'sim_time_s':timeline.get_current_time(),'wall_time_s':time.time(),'rgb_sha256':digest})
  for aid,actor in director.actors.items():
   numbers=[int(k) for k,v in labels.items() if str(v).startswith(actor.path+'/')];px=int(np.isin(id_image,numbers).sum()) if numbers else 0;seen_pixels[aid]=max(seen_pixels[aid],px);actual=observer.read_actor(aid,with_skin=px>0 or f in keys or bool(row['actors'][aid].get('support')));r=row['actors'][aid];r['actual_world_joints_m']=actual['joints_world_m'].tolist();r['actual_root_matrix']=actual['root_matrix'].tolist();r['instance_pixels']=px;bones={}
   for side in ['L','R']:
    for top,end in [('Upperarm','Forearm'),('Forearm','Hand'),('Thigh','Calf'),('Calf','Foot')]:
     key=side+'_'+top+'/'+side+'_'+end;v=float(np.linalg.norm(actual['joints_world_m'][actor.cache.index(side+'_'+top)]-actual['joints_world_m'][actor.cache.index(side+'_'+end)]));bones[key]=v;ranges.setdefault((aid,key),[v,v]);ranges[aid,key]=[min(ranges[aid,key][0],v),max(ranges[aid,key][1],v)]
   r['actual_long_bones_m']=bones
   if r.get('support'):
    parts=dict(zip(actual['part_paths'],actual['parts']))
    for side,sole in actor.soles.items():
     if side in r['support']:r['support'][side]['actual_point_world_m']=parts[sole.path][sole.vertex].tolist()
   vis=observer.visibility(aid,actual,id_image,labels,row['camera_matrix'],row['camera_focal_mm'],args.run_id+':'+row['shot'],f-first,r);vislog.write(json.dumps(vis)+'\n')
   if f in keys:
    cloud=actual['cloud'];intrusions=[]
    for box in scene['boxes']:
     if box['kind'] in ['glass','light','wet'] or box.get('rot_z') or box['center'][2]<.05:continue
     center=np.array(box['center']);half=np.array(box['size'])/2;lo=center-half;hi=center+half
     if not np.all(cloud.max(0)>lo) or not np.all(cloud.min(0)<hi):continue
     depth=np.minimum(cloud-lo,hi-cloud).min(1)
     if (depth>.008).any():intrusions.append({'group':box['group'],'name':box['name'],'max_depth_m':float(depth.max()),'vertices':int((depth>.008).sum())})
    if intrusions:probes.append({'source_tick':f,'id':aid,'instance_pixels':px,'static_vertex_intrusions':intrusions})
  if f in keys:
   Image.fromarray(rgb).save(out/f'frame_{f:04d}.png');np.save(out/f'frame_{f:04d}_ids.npy',id_image);(out/f'frame_{f:04d}_labels.json').write_text(json.dumps(data['info']));print('feature',args.part,'frame',f,'shot',row['shot'],'visible',{a:r['instance_pixels'] for a,r in row['actors'].items()},flush=True)
  log.write(json.dumps(row)+'\n')
 log.close();vislog.close();info=rec.close();worst=max((hi-lo)/max(lo,1e-8) for lo,hi in ranges.values());assert worst<1e-4,worst
 (out/'bone_invariants.json').write_text(json.dumps({'max_relative_range':worst,'actual_USD_FK':True,'ranges':{aid:{k:{'min_m':v[0],'max_m':v[1]} for (who,k),v in ranges.items() if who==aid} for aid in director.actors}},indent=2));(out/'static_probe_candidates.json').write_text(json.dumps({'candidates':probes,'scope':'actual deformed vertices at selected keyframes; >8mm inside authored static boxes. Not exhaustive surface intersection, CCD or PhysX; offscreen candidates retained.'},indent=2));(out/'actual_roster.json').write_text(json.dumps({'actors':[{'id':aid,'maximum_instance_pixels':px} for aid,px in seen_pixels.items()]},indent=2));(out/'completed.json').write_text(json.dumps({'preview':args.preview,'part':args.part,'frames':info['frames'],'sampled_frames':len(keys) if args.preview else last-first,'source_ticks':[first,last-1],'resolution':[1920,1080],'duration_s':(last-first)/30,'capture_wall_s':time.monotonic()-start,'adjacent_rgb_duplicates':duplicates,'long_bone_max_relative_range':worst,'human_reviewers':0,'autonomous_infected_pursuit':False,'runtime':'6.2.0-rc.14'},indent=2));stage.GetRootLayer().Export(str(out/'scene.usda'))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 app.close()
raise SystemExit(code)
