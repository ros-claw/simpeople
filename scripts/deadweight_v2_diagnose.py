"""Restore frozen V1 shots; identify suspect meshes with leaf IDs and A/B toggles."""
import argparse,hashlib,json,os,sys,shutil,importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);p.add_argument('--pose-offset-frames',type=int,default=0);args=p.parse_args()
out=ROOT/'runs'/args.run_id;out.mkdir(parents=True,exist_ok=False)
(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}))
snap=ROOT/'runs/deadweight-master-03/source_snapshot'
shutil.copytree(snap,out/'source_snapshot');shutil.copy2(__file__,out/'source_snapshot/deadweight_v2_diagnose.py')
sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
rec=None;code=0
try:
 import omni.usd,omni.timeline,omni.replicator.core as rep
 import numpy as np
 from pxr import UsdGeom,UsdSkel,Usd,Gf
 from PIL import Image
 # Load the actual frozen modules, not a newly edited V2 director.
 for name in ['simpeople.core.deadweight','simpeople.backends.native.deadweight_cinema','simpeople.backends.native.deadweight_set','simpeople.backends.native.deadweight_director']:
  path=snap/'src'/Path(*name.split('.')).with_suffix('.py');spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
 from simpeople.backends.native.deadweight_cinema import FilmPoseCache
 from simpeople.backends.native.deadweight_set import create_set
 from simpeople.backends.native.deadweight_director import DeadweightDirector
 from simpeople.backends.native.recording import Recorder
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();cars=create_set(stage,ROOT)
 cache=FilmPoseCache(ROOT/'runs/deadweight-zombie-probe-05');director=DeadweightDirector(stage,cars,cache,ROOT,'full')
 result=json.loads((ROOT/'runs/deadweight-master-03/completed.json').read_text())
 original={r['source_tick']:r for r in map(json.loads,(ROOT/'runs/deadweight-master-03/frames.jsonl').read_text().splitlines())}
 timeline=omni.timeline.get_timeline_interface();timeline.set_auto_update(False);timeline.play();timeline.commit()
 ids=None;depth=None;records=[]
 for frame in [1981,2570]:
  director.dispatch.departure_s=result['departure_s'];director.dispatch.last_sim_s=None
  director.dispatch.upper_closed=director.dispatch.lower_closed=director.dispatch.booth_closed=director.dispatch.driver_release=True
  observations,_=director.update((frame+args.pose_offset_frames)/30)
  matrix=director.camera.Get();error=float(np.max(np.abs(np.array(matrix)-np.array(original[frame]['camera_matrix']))))
  if error>1e-7:raise RuntimeError(f'frozen camera mismatch: {error}')
  if rec is None:
   rec=Recorder(out,(1920,1080),gpu_index=args.gpu)
   ids=rep.AnnotatorRegistry.get_annotator('instance_id_segmentation_fast',init_params={'colorize':False},device='cpu');ids.attach([rec.product])
   depth=rep.AnnotatorRegistry.get_annotator('distance_to_camera',device='cpu');depth.attach([rec.product])
  folder=out/f'frame_{frame}';folder.mkdir()
  def shot(name):
   before=timeline.get_current_time()
   for _ in range(5):rec.step(0)
   if abs(timeline.get_current_time()-before)>1e-8:raise RuntimeError('diagnostic warmup advanced simulation')
   data=ids.get_data(device='cpu');rgb=np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3]
   Image.fromarray(rgb).save(folder/(name+'.png'))
   np.save(folder/(name+'_ids.npy'),np.array(data['data'],copy=True));np.save(folder/(name+'_depth.npy'),np.array(depth.get_data(device='cpu'),copy=True))
   (folder/(name+'_labels.json')).write_text(json.dumps(data['info'],indent=2))
   print('saved',frame,name,flush=True)
  shot('F_full')
  glass=[p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh) and str(p.GetPath()).startswith('/World/Cars/') and p.GetName().startswith('Glass')]
  for p in glass:UsdGeom.Imageable(p).MakeInvisible()
  shot('F_glass_hidden')
  suspects=['/World/Cars/B/Passengers/survivor_01/RainCape','/World/Cars/A/Passengers/heroine/RainCape','/World/Cars/A/Passengers/heroine/LWing','/World/Cars/A/Passengers/heroine/RWing']
  for i,path in enumerate(suspects):
   prim=stage.GetPrimAtPath(path);imageable=UsdGeom.Imageable(prim);old=imageable.GetVisibilityAttr().Get();imageable.MakeInvisible();shot(f'hide_{i}');imageable.GetVisibilityAttr().Set(old);shot(f'restore_{i}')
   records.append({'frame':frame,'path':path,'type':prim.GetTypeName(),'parent':str(prim.GetParent().GetPath()),'prim_stack':[{'layer':p.layer.identifier,'path':str(p.path)} for p in prim.GetPrimStack()], 'skinned':bool(UsdSkel.BindingAPI(prim).GetJointIndicesPrimvar()),'generated_by':'FilmActor.rainwear' if path.endswith('RainCape') else 'FilmActor.gull','source_file':str(snap/'src/simpeople/backends/native/deadweight_cinema.py'),'toggle_pair':[f'hide_{i}.png',f'restore_{i}.png']})
  props=[p for p in stage.Traverse() if p.GetName() in ['RainCape','GullHood','LWing','RWing','TouristCamera']]
  for p in props:UsdGeom.Imageable(p).MakeInvisible()
  shot('B_cached_original_clothing')
  for p in props:
   if p.GetName()=='GullHood':UsdGeom.Imageable(p).MakeVisible()
  shot('D_hood_only')
  for p in props:UsdGeom.Imageable(p).MakeInvisible()
  for p in props:
   if p.GetName() in ['LWing','RWing']:UsdGeom.Imageable(p).MakeVisible()
  shot('E_wrists_only')
  for p in props:UsdGeom.Imageable(p).MakeVisible()
  for p in glass:UsdGeom.Imageable(p).MakeVisible()
  stage.GetRootLayer().Export(str(folder/'restored_scene.usda'))
  (folder/'frame_identity.json').write_text(json.dumps({'original_run':'deadweight-master-03','original_frame':frame,'pose_offset_frames':args.pose_offset_frames,'pose_story_time_s':(frame+args.pose_offset_frames)/30,'camera_max_abs_matrix_error':error,'simulation_time_during_paused_replay':timeline.get_current_time(),'warmup_delta_time':0,'pixel_origin':'top left; native 1920x1080','scope':'offset is an explicit timing-alignment experiment; temporal denoising warmup can change radiance'},indent=2))
 (out/'suspect_meshes.json').write_text(json.dumps(records,indent=2));(out/'completed.json').write_text(json.dumps({'frames_restored':[1981,2570],'leaf_annotator':'instance_id_segmentation_fast','scope':'frozen-frame attribution, not animation/physics acceptance'},indent=2))
 rec.close();rec=None
except Exception:
 import traceback
 traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 app.close()
raise SystemExit(code)
