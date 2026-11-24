"""Actual Isaac 6.2 metro rehearsal, with film and geometry evidence separate."""
import argparse,os,sys,json,shutil,hashlib,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);p.add_argument('--preview',action='store_true');p.add_argument('--principals',action='store_true');p.add_argument('--start-frame',type=int,default=0);p.add_argument('--end-frame',type=int,default=540);args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}))
snap=out/'source_snapshot';shutil.copytree(ROOT/'src/simpeople',snap/'src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,snap/Path(__file__).name);shutil.copytree(ROOT/'.runtime/platform04/kit',snap/'production_kit');(out/'input_hashes.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in snap.rglob('*') if f.is_file()},indent=2));sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});rec=None;code=0
try:
 import omni.usd,omni.timeline,numpy as np,omni.replicator.core as rep
 from pxr import UsdGeom
 from PIL import Image
 from simpeople.backends.native.platform04_scene import create_metro
 from simpeople.backends.native.platform04_director import MetroDirector
 from simpeople.backends.native.recording import Recorder
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();scene=create_metro(stage,ROOT);director=MetroDirector(stage,scene,ROOT,out,extras=not args.principals)
 for f in range(37):director.update(f)
 director.update(args.start_frame);tl=omni.timeline.get_timeline_interface();tl.set_auto_update(False);tl.set_time_codes_per_second(30);tl.set_end_time(1000);tl.play();tl.commit();rec=Recorder(out,(1920,1080),gpu_index=args.gpu)
 ids=rep.AnnotatorRegistry.get_annotator('instance_id_segmentation_fast',init_params={'colorize':False},device='cpu');ids.attach([rec.product])
 for _ in range(8):rec.step(0)
 if not args.preview:rec.control({'mode':'start'})
 keys=[0,24,48,75,90,110,132,180,210,240,270,300,315,330,342,345,348,351,354,357,360,366,375,390,420,450,480,510,539]
 log=(out/'frames.jsonl').open('w');last=None;start=time.monotonic();min_distance=None
 for f in range(args.start_frame,args.end_frame):
  if args.preview and f not in keys:continue
  record=director.update(f,geometry=9.8<=f/30<=13.0);camera=record['camera_matrix']
  if last is None or f in [69,129,306,395,475]:
   for _ in range(6):rec.step(0)
  rec.step(1/30);rec.step(0);rgb=np.ascontiguousarray(rec.rgb.get_data(device='cpu')[:,:,:3]);black=float(np.all(rgb<3,axis=2).mean())
  if black>.99:raise RuntimeError(f'black/occluded frame {f}')
  record.update(sim_time_s=tl.get_current_time(),wall_time_s=time.time(),rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),black_fraction=black)
  if not args.preview:rec.capture(tl.get_current_time(),{'source_tick':f,'scope':'cinematic full-pose cache'})
  for aid,a in director.actors.items():
   matrix=np.asarray(a.matrix);record['actors'][aid]['joints_world_m']=(a.joint_p@matrix[:3,:3]+matrix[3,:3]).tolist();record['actors'][aid]['joint_quaternions_actor']=a.joint_q.tolist()
  from simpeople.backends.native.deadweight_cinema import quat_apply
  head=director.bank.index('Head');red=director.actors['intercept'];hero=director.actors['hero'];rm=np.asarray(red.matrix);hm=np.asarray(hero.matrix);forward=quat_apply(red.joint_q[head],[0,0,1])@rm[:3,:3];delta=hero.joint_p[head]@hm[:3,:3]+hm[3,:3]-(red.joint_p[head]@rm[:3,:3]+rm[3,:3]);record['red_head_target_error_deg']=float(np.degrees(np.arccos(np.clip(forward@delta/np.linalg.norm(delta),-1,1))))
  if 'near_miss' in record and (min_distance is None or record['near_miss']['min_vertex_distance_m']<min_distance['min_vertex_distance_m']):min_distance={'source_tick':f,**record['near_miss']}
  log.write(json.dumps(record)+'\n');last=camera
  if f in keys:
   Image.fromarray(rgb).save(out/f'frame_{f:04d}.png');data=ids.get_data(device='cpu');np.save(out/f'frame_{f:04d}_ids.npy',data['data']);(out/f'frame_{f:04d}_labels.json').write_text(json.dumps(data['info']));print('frame',f,'near',record.get('near_miss',{}).get('min_vertex_distance_m'),flush=True)
  if f in [210,270,345]:
   for condition in ['none','single']:
    for prim in scene['glass']:(UsdGeom.Imageable(prim).MakeInvisible if condition=='none' else UsdGeom.Imageable(prim).MakeVisible)()
    for _ in range(5):rec.step(0)
    Image.fromarray(np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3]).save(out/f'glass_{condition}_{f:04d}.png')
   for prim in scene['glass']:UsdGeom.Imageable(prim).MakeVisible()
 log.close();info=rec.close();(out/'completed.json').write_text(json.dumps({'frames':info['frames'],'duration_s':info['frames']/30,'preview':args.preview,'instances':len(director.actors),'source_motion_run':'platform04-motion-01','min_vertex_near_miss':min_distance,'wall_capture_s':time.monotonic()-start,'human_blind_review':'not_measured','scope':'actual Isaac RGB, directed trajectories and full production skeleton cache; reactive Native pursuit has separate runs'},indent=2));stage.GetRootLayer().Export(str(out/'scene.usda'))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 app.close()
raise SystemExit(code)
