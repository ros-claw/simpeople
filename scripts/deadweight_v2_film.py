"""Native 24 s repair rehearsal; --preview captures blocking before a full take."""
import argparse,os,sys,json,shutil,hashlib,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);p.add_argument('--preview',action='store_true');p.add_argument('--start-frame',type=int,default=0);p.add_argument('--end-frame',type=int,default=720);args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(parents=True,exist_ok=False)
(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}))
for file in [Path(__file__),ROOT/'src/simpeople/core/funicular.py',ROOT/'runs/deadweight-v2-rail-01/production_profile.json',ROOT/'configs/assets.json',*list((ROOT/'src/simpeople/backends/native').glob('deadweight*.py')),*list((ROOT/'runs/deadweight-zombie-probe-05').glob('native_bones.npz')),*list((ROOT/'runs/deadweight-zombie-probe-05').glob('cache_rig.json')),*list((ROOT/'runs/deadweight-zombie-probe-05').glob('zombie_frames.jsonl'))]:
 dest=out/'source_snapshot'/file.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,dest)
shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(out/'input_hashes.json').write_text(json.dumps({str(f.relative_to(out/'source_snapshot')):hashlib.sha256(f.read_bytes()).hexdigest() for f in (out/'source_snapshot').rglob('*') if f.is_file()},indent=2))
sys.path.insert(0,str(out/'source_snapshot/src'))
sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});rec=None;code=0
try:
 import omni.usd,omni.timeline,omni.replicator.core as rep,numpy as np
 from PIL import Image
 from pxr import UsdGeom,UsdShade,Gf,Sdf
 from simpeople.backends.native.deadweight_v2_set import create_scene
 from simpeople.backends.native.deadweight_v2_actor import RepairPoseCache
 from simpeople.backends.native.deadweight_v2_director import RepairDirector
 from simpeople.backends.native.deadweight_v2_qa import measure_costume_gaits
 from simpeople.backends.native.recording import Recorder
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();cars,geom=create_scene(stage,ROOT,storm=True);cache=RepairPoseCache(ROOT/'runs/deadweight-zombie-probe-05');director=RepairDirector(stage,cars,geom,cache,ROOT,out);print('director ready',flush=True)
 (out/'healthy_loop.json').write_text(json.dumps({'source_start_frame':cache.walk_start,'period_frames':cache.walk_period,'mean_loop_joint_error_m':cache.walk_loop_mean_joint_error_m,'scope':'measured healthy movie loop; source Native samples unchanged; idle/walk transitions blended'},indent=2))
 (out/'runtime_imports.json').write_text(json.dumps({name:getattr(mod,'__file__',None) for name,mod in sys.modules.items() if name.startswith('simpeople.')},indent=2))
 gaitqa=measure_costume_gaits(director);(out/'deformed_shoe_qa.json').write_text(json.dumps(gaitqa,indent=2));print('actual shoe QA',gaitqa['passed'],flush=True)
 timeline=omni.timeline.get_timeline_interface();timeline.set_auto_update(False);timeline.set_time_codes_per_second(30);timeline.set_end_time(1000);timeline.play();timeline.commit()
 if args.start_frame>=315:
  for f in range(165,315):director.update(f)
 director.update(args.start_frame);rec=Recorder(out,(1920,1080),gpu_index=args.gpu)
 # Leaf IDs and RGB use the same synchronized product.
 ids=rep.AnnotatorRegistry.get_annotator('instance_id_segmentation_fast',init_params={'colorize':False},device='cpu');ids.attach([rec.product])
 for _ in range(8):rec.step(0)
 # Measure image freshness rather than assuming wait_for_render implies it.
 # This temporary magenta sphere is removed before every movie frame.
 marker=UsdGeom.Sphere.Define(stage,'/World/AlignmentWitness');marker.CreateRadiusAttr(.045);move=marker.AddTranslateOp();mat=UsdShade.Material.Define(stage,'/World/AlignmentMaterial');shader=UsdShade.Shader.Define(stage,'/World/AlignmentMaterial/Surface');shader.CreateIdAttr('UsdPreviewSurface');shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(1,0,1));shader.CreateInput('emissiveColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(2,0,2));mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface');UsdShade.MaterialBindingAPI.Apply(marker.GetPrim()).Bind(mat)
 alignment=[];camera=stage.GetPrimAtPath('/World/Camera');camera_world=UsdGeom.Xformable(camera).GetOrderedXformOps()[0].Get();focal=camera.GetAttribute('focalLength').Get()
 for n,x in enumerate([-.40,.40,-.20,.20]):
  move.Set(camera_world.Transform(Gf.Vec3d(x,0,-2)));rec.step(1/30);rec.step(0);rgb=np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3];yy,xx=np.where((rgb[:,:,0]>180)&(rgb[:,:,2]>180)&(rgb[:,:,1]<90));expected=960+x/2*focal/36*1920
  valid=(abs(xx-expected)<90)&(abs(yy-540)<90);cx=float(np.median(xx[valid])) if valid.any() else None;err=None if cx is None else abs(cx-expected);alignment.append({'sample':n,'authored_camera_x_m':x,'expected_pixel_x':expected,'rgb_magenta_center_x':cx,'error_pixels':err,'sim_time_s':timeline.get_current_time()});Image.fromarray(rgb).save(out/f'alignment_{n}.png')
 stage.RemovePrim('/World/AlignmentWitness');stage.RemovePrim('/World/AlignmentMaterial')
 (out/'rgb_pose_alignment.json').write_text(json.dumps({'samples':alignment,'passed':all(r['error_pixels'] is not None and r['error_pixels']<3 for r in alignment),'scope':'actual rendered moving witness vs camera projection; marker excluded from movie'},indent=2))
 if not all(r['error_pixels'] is not None and r['error_pixels']<3 for r in alignment):raise RuntimeError('RGB/pose alignment witness failed')
 for _ in range(5):rec.step(0)
 if not args.preview:rec.control({'mode':'start'})
 selected=[0,60,89,105,139,164,190,225,260,280,290,300,314,315,330,360,400,434,435,480,510,540,584,585,610,645,675,710,719]
 log=(out/'frames.jsonl').open('w');start=time.monotonic();previous_segment=None
 for frame in range(args.start_frame,args.end_frame):
  if args.preview and frame not in selected and not 165<=frame<315:continue
  record=director.update(frame);segment=record['segment']
  if segment!=previous_segment:
   for _ in range(6):rec.step(0)
  rec.step(1/30);rec.step(0) # zero-time barrier: new poses and RGB share the state
  rgb_frame=np.ascontiguousarray(rec.rgb.get_data(device='cpu')[:,:,:3]);dark_fraction=float(np.all(rgb_frame<3,axis=2).mean())
  if dark_fraction>.99:raise RuntimeError(f'black/occluded RGB frame {frame}: {dark_fraction}')
  record['simulation_time_s']=timeline.get_current_time();record['wall_time_s']=time.time();record['capture_barrier']='one positive 1/30 step followed by zero-time synchronized render';record['rgb_sha256']=hashlib.sha256(rgb_frame.tobytes()).hexdigest();record['near_black_pixel_fraction']=dark_fraction
  if not args.preview:rec.capture(timeline.get_current_time(),{k:record[k] for k in ['source_tick','movie_time_s','segment','solver_index','simulation_time_s']})
  log.write(json.dumps(record)+'\n');previous_segment=segment
  if frame in selected:
   Image.fromarray(np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3]).save(out/f'frame_{frame:04d}.png');data=ids.get_data(device='cpu');np.save(out/f'frame_{frame:04d}_ids.npy',data['data']);(out/f'frame_{frame:04d}_labels.json').write_text(json.dumps(data['info']));print('captured',frame,segment,flush=True)
  if frame==510:
   # Same geometry and pose: zero/single/double-glass tests, no elapsed motion.
   glass=[p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh) and p.GetName().startswith('Glass')]
   for condition in ['none','single','double']:
    for p in glass:
     show=condition=='double' or condition=='single' and str(p.GetPath()).startswith(cars['A']['root']);(UsdGeom.Imageable(p).MakeVisible if show else UsdGeom.Imageable(p).MakeInvisible)()
    for _ in range(5):rec.step(0)
    Image.fromarray(np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3]).save(out/f'glass_{condition}.png')
   for p in glass:UsdGeom.Imageable(p).MakeVisible()
 log.close();metrics=rec.close();(out/'events.json').write_text(json.dumps(director.events,indent=2));(out/'completed.json').write_text(json.dumps({'mode':'preview' if args.preview else 'original speed source take','frames':metrics['frames'],'source_window':[args.start_frame,args.end_frame],'encoded_duration_s':metrics['frames']/30,'wall_render_s':time.monotonic()-start,'meeting_solver_time_s':director.profile[director.meet_index]['solver_time_s'],'arrival_solver_time_s':director.profile[-1]['solver_time_s'],'scope':'cached actor choreography; 1D mass driven cars; elapsed travel omitted by hard cuts; not PhysX contacts, not Native navigation','human_mute_review':'not_measured'},indent=2));stage.GetRootLayer().Export(str(out/'scene.usda'))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 app.close()
raise SystemExit(code)
