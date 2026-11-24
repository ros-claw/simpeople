"""Native V2 still review. Each invocation has an immutable run directory."""
import argparse,json,os,sys,shutil,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--mode',choices=['scene','repair','wardrobe'],required=True);p.add_argument('--frame',type=int,default=1981);p.add_argument('--gpu',type=int,default=3);args=p.parse_args()
out=ROOT/'runs'/args.run_id;out.mkdir(parents=True,exist_ok=False)
(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}))
for file in [Path(__file__),*list((ROOT/'src/simpeople/backends/native').glob('deadweight*.py'))]:
 dest=out/'source_snapshot'/file.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,dest)
shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(out/'input_hashes.json').write_text(json.dumps({str(f.relative_to(out/'source_snapshot')):hashlib.sha256(f.read_bytes()).hexdigest() for f in (out/'source_snapshot').rglob('*') if f.is_file()},indent=2))
sys.path.insert(0,str(out/'source_snapshot/src'))
sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
code=0;rec=None
try:
 import omni.usd,omni.timeline,numpy as np
 from pxr import Usd,UsdGeom,UsdSkel,UsdLux,Gf,Vt
 from PIL import Image
 from simpeople.backends.native.recording import Recorder
 from simpeople.backends.native.deadweight_v2_set import create_scene,aim,RUN,FLOOR,Weather
 from simpeople.backends.native.deadweight_cinema import FilmPoseCache,quat_apply,quat_mul,raised_wings
 from simpeople.backends.native.deadweight_v2_actor import ActorV2,wrist_turn
 cache=FilmPoseCache(ROOT/'runs/deadweight-zombie-probe-05');assets=json.loads((ROOT/'configs/assets.json').read_text())['assets'][:11]
 def source(i):return str(ROOT/'assets/characters'/assets[i]['source_uri'].removeprefix('characters://'))
 timeline=omni.timeline.get_timeline_interface();timeline.set_auto_update(False)
 if args.mode=='repair':
  # -1 replay reproduces both hand/camera control landmarks of the V1 RGB.
  original=ROOT/f'runs/deadweight-v2-attribution-02/frame_{args.frame}/restored_scene.usda'
  omni.usd.get_context().open_stage(str(original))
  for _ in range(8):app.update()
  stage=omni.usd.get_context().get_stage();path='/World/Cars/A/Passengers/heroine'
  old=UsdSkel.Animation(stage.GetPrimAtPath(path+'/FilmAnimation'));translations=old.GetTranslationsAttr().Get();rotations=old.GetRotationsAttr().Get();root_matrix=UsdGeom.Xformable(stage.GetPrimAtPath(path)).GetOrderedXformOps()[0].Get()
  # Preserve the exact deformed body pose, scale and original material edits.
  for prim in list(stage.Traverse()):
   if prim.GetName() in ['RainCape','LWing','RWing']:UsdGeom.Imageable(prim).MakeInvisible()
  # Use a separate diagnostic fitter; no replacement of the source body.
  fit=ActorV2(stage,'/World/DiagnosticFitter',cache,source_uri=source(3));fit.update(*cache.pose(0,'idle'),[0,0,0]);measure=fit.short_mitts(ROOT,out/'fitted_mitts')
  # Copy only fitted accessories to the original wrist. Root/bones untouched.
  local_p=np.asarray(translations,dtype=float);local_q=np.array([[*r.GetImaginary(),r.GetReal()] for r in rotations]);gp=local_p.copy();gq=local_q.copy()
  for js in cache.levels:
   ps=cache.parent_indices[js];gp[js]=gp[ps]+quat_apply(gq[ps],local_p[js]);gq[js]=quat_mul(gq[ps],local_q[js])
  for side in ['L','R']:
   prop=UsdGeom.Xform.Define(stage,path+'/'+side+'ShortWing');prop.GetPrim().GetReferences().AddReference(str(out/'fitted_mitts'/f'{side}_short_wing.usda'))
   j=cache.index(side+'_Hand');basis=np.asarray(measure[side]['socket_hand_basis'])@quat_apply(gq[j],np.eye(3));m=np.eye(4);m[:3,:3]=basis;m[3,:3]=gp[j];prop.AddTransformOp().Set(Gf.Matrix4d(*m.ravel().tolist()))
  stage.RemovePrim('/World/DiagnosticFitter')
  timeline.play();timeline.commit();rec=Recorder(out,(1920,1080),gpu_index=args.gpu)
  for _ in range(10):rec.step(0)
  Image.fromarray(np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3]).save(out/'repaired.png')
  if list(old.GetTranslationsAttr().Get())!=list(translations) or list(old.GetRotationsAttr().Get())!=list(rotations):raise RuntimeError('same-frame body pose was modified')
  (out/'repair_identity.json').write_text(json.dumps({'original_frame':args.frame,'pose_offset_frames':-1,'body_TRS_unchanged':True,'body_root_unchanged':UsdGeom.Xformable(stage.GetPrimAtPath(path)).GetOrderedXformOps()[0].Get()==root_matrix,'preserved':['original skinned clothing','GullHood','TouristCamera','backpack'],'removed_visible':['RainCape','LWing','RWing'],'fit_measurements':measure},indent=2))
 else:
  omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();cars,geometry=create_scene(stage,ROOT)
  timeline.play();timeline.commit();aim(stage,[-65,-112,65],[40,0,29],42);rec=Recorder(out,(1920,1080),gpu_index=args.gpu)
  def shot(name,eye,target,lens=40):
   aim(stage,eye,target,lens)
   for _ in range(8):rec.step(0)
   Image.fromarray(np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3]).save(out/(name+'.png'));print('saved',name,flush=True)
  if args.mode=='scene':
   weather_fx=Weather(stage)
   geometry.apply(82)
   views=[('lower_to_upper',[-50,-150,65],[40,-3,27],37),('foundation',[48,-24,26],[52,0,31],32),('refuge',[-3.0,-1.8,7.5],[-5.1,-5.6,6.1],32)]
   # q=112 for exit views. Other shots retain a readable separation of cars.
   for weather in ['dry','storm']:
    storm=weather=='storm';stage.GetPrimAtPath('/World/Lights/Sky').GetAttribute('inputs:intensity').Set(430 if storm else 650);stage.GetPrimAtPath('/World/Lights/Day').GetAttribute('inputs:intensity').Set(950 if storm else 1700)
    (UsdGeom.Imageable(weather_fx.curves).MakeVisible if storm else UsdGeom.Imageable(weather_fx.curves).MakeInvisible)()
    for name,eye,target,lens in views:
     geometry.apply(112 if name=='refuge' else 82);shot(weather+'_'+name,eye,target,lens)
   (out/'camera_views.json').write_text(json.dumps(views,indent=2))
  else:
   # Actual eleven source rigs, using the costumes used by the movie.
   for car in cars.values():UsdGeom.Imageable(stage.GetPrimAtPath(car['root'])).MakeInvisible()
   from simpeople.backends.native.deadweight_set import box
   box(stage,'/World/ReviewDeck',(0,-70,-.15),(30,9,.3),(.25,.27,.26))
   actors=[];measurements=[]
   palette=[(.18,.39,.41),(.61,.25,.10),(.25,.33,.16),(.16,.24,.42),(.49,.16,.19),(.45,.38,.16)]
   for i,a in enumerate(assets):
    tint=(.74,.48,.1) if i==3 else palette[2] if i==5 else palette[i%6]
    actor=ActorV2(stage,f'/World/Wardrobe/Actor{i}',cache,tint,source(i));actor.update(*cache.pose(0,'idle'),[(i-5)*1.5,-70,0],-np.pi/2);actors.append(actor)
    if i==3:actor.hood(ROOT/'.runtime/deadweight/Deadweight_Feasibility_Assets/gull_hood.usda');measurements.append(actor.short_mitts(ROOT,out/'fitted_mitts'))
    if i==5:actor.camera_prop()
   shot('eleven_costumes',[0,-87,4.8],[0,-70,1.0],36)
   hero=actors[3]
   for i,a in enumerate(actors):
    if i!=3:UsdGeom.Imageable(stage.GetPrimAtPath(a.path)).MakeInvisible()
   hero.update(*cache.pose(0,'idle'),[0,-70,0],-np.pi/2)
   for name,amount,turn in [('hands_down',0,0),('hand_raised',.68,0),('wrist_turn',.68,1.0),('window_gesture',.76,-.35)]:
    p,q=raised_wings(cache,*cache.pose(0,'idle'),amount,('L',));p,q=wrist_turn(cache,p,q,'L',turn);hero.update(p,q,[0,-70,0],-np.pi/2);shot(name,[2.2,-75.0,1.35],[0,-70,1.03],45)
   # A real 9-second action fit, with a fixed transparent pane as reference.
   from pxr import UsdShade,Sdf
   from simpeople.backends.native.deadweight_set import box
   nearest=[]
   for amount,turn in [(0,0),(.68,0),(.68,1.0),(.76,-.35)]:
    p,q=raised_wings(cache,*cache.pose(0,'idle'),amount,('L',));p,q=wrist_turn(cache,p,q,'L',turn);hero.update(p,q,[0,-70,0],-np.pi/2);nearest.append(min(float(v[:,1].min()) for v in hero.mitt_world_points().values()))
   pane_y=min(nearest)-.008;pane=box(stage,'/World/FitPane',(0,pane_y,1.15),(2.1,.01,2.3),(.16,.30,.34),.0,.25);UsdShade.Shader(stage.GetPrimAtPath('/World/FitPane/Material/Surface')).CreateInput('opacity',Sdf.ValueTypeNames.Float).Set(.035)
   for i,x in enumerate([-1.05,1.05]):box(stage,f'/World/FitFrame/P{i}',(x,pane_y,1.15),(.04,.035,2.3),(.18,.25,.26),.5)
   box(stage,'/World/FitFrame/Top',(0,pane_y,2.30),(2.1,.035,.04),(.18,.25,.26),.5)
   rec.control({'mode':'start'});motion=[]
   for f in range(270):
    t=f/30
    if t<2:amount,turn=0,0
    elif t<4:amount,turn=.68*(.5-.5*np.cos(np.pi*(t-2)/2)),0
    elif t<6:amount,turn=.68,.5-.5*np.cos(np.pi*(t-4))
    else:amount,turn=.68+.08*min(1,(t-6)/.8),-.35*min(1,(t-6)/.8)
    p,q=raised_wings(cache,*cache.pose(0,'idle'),amount,('L',));p,q=wrist_turn(cache,p,q,'L',turn);hero.update(p,q,[0,-70,0],-np.pi/2);rec.step(1/30);rec.step(0);rec.capture(timeline.get_current_time(),{'source_tick':f,'action':'down' if t<2 else 'raise' if t<4 else 'wrist_turn' if t<6 else 'window_gesture'})
    gap=min(float(v[:,1].min()) for v in hero.mitt_world_points().values())-pane_y-.005;motion.append({'source_tick':f,'pane_gap_m':gap})
   rec.close();(out/'mitt_window_clearance.json').write_text(json.dumps({'min_gap_m':min(r['pane_gap_m'] for r in motion),'last_gap_m':motion[-1]['pane_gap_m'],'samples':motion,'scope':'measured foam mesh/window-plane clearance; no contact forces'},indent=2))
   (out/'costume_qa.json').write_text(json.dumps({'sources':[a['asset_id'] for a in assets],'fit_measurements':measurements,'scope':'eleven actual original skinned costumes; no unskeletal RainCape or egg wing'},indent=2))
 stage.GetRootLayer().Export(str(out/'scene.usda'));(out/'completed.json').write_text(json.dumps({'mode':args.mode,'frame':args.frame,'renderer':'Isaac Sim 6.2','positive_time_steps':270 if args.mode=='wardrobe' else 0},indent=2))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 app.close()
raise SystemExit(code)
