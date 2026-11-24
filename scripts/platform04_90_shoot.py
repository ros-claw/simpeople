"""Formal first-round opening/character/door takes, never auto-promote to 90s."""
import argparse,hashlib,json,os,sys,shutil,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--mode',choices=['opening','character','door'],required=True);p.add_argument('--gpu',type=int,default=2);p.add_argument('--preview',action='store_true');p.add_argument('--start-frame',type=int);p.add_argument('--end-frame',type=int);args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));snap=out/'source_snapshot';shutil.copytree(ROOT/'src/simpeople',snap/'src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copytree(ROOT/'.runtime/platform04_90/kit',snap/'production_kit');shutil.copy2(__file__,snap/Path(__file__).name);(out/'input_hashes.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in snap.rglob('*') if f.is_file()},indent=2));sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});rec=None;code=0
try:
 import omni.usd,omni.timeline,omni.replicator.core as rep,numpy as np
 from pxr import UsdGeom
 from PIL import Image
 from scipy.spatial import cKDTree
 from simpeople.backends.native.platform04_90_scene import create_director_scene
 from simpeople.backends.native.platform04_90_director import Director90
 from simpeople.backends.native.platform04_90_observation import PerformanceReadback
 from simpeople.backends.native.recording import Recorder
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();scene=create_director_scene(stage,ROOT);director=Director90(stage,scene,ROOT,out,args.mode)
 bounds={'opening':(0,270),'character':(270,630),'door':(1590,1890)};first,last=bounds[args.mode];first=first if args.start_frame is None else args.start_frame;last=last if args.end_frame is None else args.end_frame;assert bounds[args.mode][0]<=first<last<=bounds[args.mode][1]
 for warm in range(bounds[args.mode][0],first):director.update(warm)
 director.update(first);(out/'jog_cycle_calibration.json').write_text(json.dumps(director.bank.jog_calibration,indent=2))
 observer=PerformanceReadback(ROOT,out,director.actors);director.update(first)
 tl=omni.timeline.get_timeline_interface();tl.set_auto_update(False);tl.set_time_codes_per_second(30);tl.set_end_time(1000);tl.play();tl.commit();rec=Recorder(out,(1920,1080),gpu_index=args.gpu);ids=rep.AnnotatorRegistry.get_annotator('instance_id_segmentation_fast',init_params={'colorize':False},device='cpu');ids.attach([rec.product])
 for _ in range(8):rec.step(0)
 keyframes={'opening':[0,60,119,120,165,209,210,240,269], 'character':[270,300,330,359,360,405,449,450,495,539,540,585,629], 'door':[1590,1620,1650,1680,1710,1730,1745,1755,1765,1775,1785,1800,1830,1860,1889]}[args.mode]
 keyframes=[f for f in keyframes if first<=f<last]
 if not args.preview:rec.control({'mode':'start'})
 frameslog=(out/'frames.jsonl').open('w');visibilitylog=(out/'actor_frames.jsonl').open('w');start=time.monotonic();minimum=None;bone_ranges={};actual_count=0;previous_shot=None
 for f in (keyframes if args.preview else range(first,last)):
  row=director.update(f)
  if row['shot']!=previous_shot:
   for _ in range(6):rec.step(0)
  previous_shot=row['shot'];rec.step(1/30);rec.step(0);rgb=np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3]
  if float((rgb.mean(2)>8).mean())<.05:raise RuntimeError(f'black/blocked shot at {f}')
  if not args.preview:rec.capture(tl.get_current_time(),{'source_tick':f,'shot':row['shot'],'mode':args.mode})
  data=ids.get_data(device='cpu');id_image=np.asarray(data['data']).reshape(1080,1920);labels=data['info']['idToLabels'];actual={};row['sim_time_s']=tl.get_current_time();row['wall_time_s']=time.time();row['rgb_sha256']=hashlib.sha256(rgb.tobytes()).hexdigest();row['output_frame']=f-first
  for aid,actor in director.actors.items():
   a=observer.read_actor(aid);actual[aid]=a;row['actors'][aid]['actual_world_joints_m']=a['joints_world_m'].tolist();row['actors'][aid]['actual_root_matrix']=a['root_matrix'].tolist();bones={}
   for side in ['L','R']:
    for top,end in [('Upperarm','Forearm'),('Forearm','Hand'),('Thigh','Calf'),('Calf','Foot')]:
     key=side+'_'+top+'/'+side+'_'+end;value=float(np.linalg.norm(a['joints_world_m'][director.bank.index(side+'_'+top)]-a['joints_world_m'][director.bank.index(side+'_'+end)]));bones[key]=value
     if (aid,key) not in bone_ranges:bone_ranges[aid,key]=[value,value]
     bone_ranges[aid,key][0]=min(bone_ranges[aid,key][0],value);bone_ranges[aid,key][1]=max(bone_ranges[aid,key][1],value)
   row['actors'][aid]['actual_long_bones_m']=bones
   vis=observer.visibility(aid,a,id_image,labels,row['camera_matrix'],row['camera_focal_mm'],args.run_id+':'+row['shot'],f-first,row['actors'][aid]);visibilitylog.write(json.dumps(vis)+'\n')
  if args.mode=='door':
   red=director.actors['F02'];parts=dict(zip(actual['F02']['part_paths'],actual['F02']['parts']));hand=np.concatenate([parts[str(m['prim'].GetPath())][m['hands']['R']] for m in red.meshes if str(m['prim'].GetPath()) in parts and m['hands']['R'].any()]);d,_=cKDTree(actual['H01']['cloud']).query(hand);near={'source_tick':f,'time_s':f/30,'hand_to_hero_deformed_vertex_distance_m':float(d.min()),'scope':'all actual right-hand vertices to hero deformed mesh/props, 30Hz; not continuous collision'};row['near_miss']=near
   if minimum is None or near['hand_to_hero_deformed_vertex_distance_m']<minimum['hand_to_hero_deformed_vertex_distance_m']:minimum=near
  if f in keyframes:
   Image.fromarray(rgb).save(out/f'frame_{f:04d}.png');np.save(out/f'frame_{f:04d}_ids.npy',id_image);(out/f'frame_{f:04d}_labels.json').write_text(json.dumps(data['info']));print('shot',row['shot'],'frame',f,'near',row.get('near_miss'),flush=True)
   if args.mode=='character' and row['shot']=='C06' or args.mode=='door' and f in [1650,1730]:
    for prim in scene['glass']:UsdGeom.Imageable(prim).MakeInvisible()
    for _ in range(4):rec.step(0)
    Image.fromarray(np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3]).save(out/f'no_glass_{f:04d}.png')
    for prim in scene['glass']:UsdGeom.Imageable(prim).MakeVisible()
  frameslog.write(json.dumps(row)+'\n');actual_count+=1
 frameslog.close();visibilitylog.close();info=rec.close();worst=max((hi-lo)/max(lo,1e-8) for lo,hi in bone_ranges.values());assert worst<.0001,worst
 (out/'bone_invariants.json').write_text(json.dumps({'max_long_bone_relative_range':worst,'per_actor':{aid:{k:{'min_m':v[0],'max_m':v[1]} for (who,k),v in bone_ranges.items() if who==aid} for aid in director.actors},'scope':'actual UsdSkel final readback, all L/R long bones; does not decide skin quality or naturalness'},indent=2));(out/'actual_roster.json').write_text(json.dumps({'actors':[{'id':aid} for aid in director.actors]},indent=2));(out/'completed.json').write_text(json.dumps({'preview':args.preview,'mode':args.mode,'actual_pose_frames':actual_count,'encoded_frames':info['frames'],'instances':len(director.actors),'source_ticks':[first,last-1],'duration_s':(last-first)/30,'wall_capture_s':time.monotonic()-start,'bone_length_invariants_passed':True,'near_miss':minimum,'human_reviewers':0,'scope':'first-round cinematic formal take; full 90s/24-character movie not rendered; no Native infection pursuit claim'},indent=2));stage.GetRootLayer().Export(str(out/'scene.usda'))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 app.close()
raise SystemExit(code)
