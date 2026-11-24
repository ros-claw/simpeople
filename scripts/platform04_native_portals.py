"""Actual Native car -> door -> platform -> exit traversals, not just queries."""
import argparse,os,sys,json,shutil,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=2);args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,out/Path(__file__).name);sys.path.insert(0,str(out/'source_snapshot/src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});backend=None;rec=None;code=0
try:
 import omni.usd,omni.kit.app,omni.kit.commands,numpy as np
 from pxr import UsdGeom,Gf,Sdf
 manager=omni.kit.app.get_app().get_extension_manager()
 for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:manager.set_extension_enabled_immediate(ext,True)
 from simpeople.backends.native.platform04_scene import create_metro,aim,technical_view
 from simpeople.backends.native.adapter import NativeBackend
 from simpeople.backends.native.recording import Recorder
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();scene=create_metro(stage,ROOT,collision=True);stage.GetRootLayer().customLayerData={'navmeshSettings':{'agentMaxFloorSlope':30.,'agentMaxRadius':.65,'agentMinRadius':.2,'agentMinHeight':1.6,'agentMaxStepHeight':.2,'agentMinIslandRadius':.2,'agentSamplingDistance':.12,'excludeRigidBodies':True}};omni.kit.commands.execute('CreateNavMeshVolumeCommand',parent_prim_path=Sdf.Path('/World'),volume_type=0);v=stage.GetPrimAtPath('/World/NavMeshVolume');UsdGeom.XformCommonAPI(v).SetTranslate(Gf.Vec3d(17,5,1.5));UsdGeom.XformCommonAPI(v).SetScale(Gf.Vec3f(52,25,6))
 backend=NativeBackend(ROOT,{},allow_unverified=True);backend.quality_sampling=True;handle=backend.spawn('portal_runner','female_adult_business_02',[17,-1.35,0])
 for _ in range(8):app.update()
 assert backend.nav.start_navmesh_baking_and_wait();tl=backend.timeline;tl.set_auto_update(False);tl.set_time_codes_per_second(30);tl.set_end_time(1000);tl.play();tl.commit()
 for _ in range(60):tl.forward_one_frame();app.update()
 diagnostic=technical_view(stage,scene);(out/'diagnostic_view.json').write_text(json.dumps(diagnostic,indent=2));rec=Recorder(out,(1920,1080),gpu_index=args.gpu)
 for _ in range(8):rec.step(0)
 from PIL import Image
 preflight=np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3];Image.fromarray(preflight).save(out/'camera_preflight.png')
 if float((preflight.mean(axis=2)>20).mean())<.10:raise RuntimeError('technical camera occluded/black; reject footage before recording')
 routes=[{'name':'car_to_door','target':[23,.02,0],'via':[[23,-1.10,0]]},{'name':'door_to_platform','target':[25,1.5,0],'via':[[23,.8,0]]},{'name':'platform_to_exit','target':[28,11,0],'via':[]}];i=0;task=None;stable=None;events=[];trace=[];log=(out/'frames.jsonl').open('w');rec.control({'mode':'start'})
 for f in range(900):
  if task is None:
   route=routes[i];task=backend.start(handle,{'action':'move_to','target':route['target'],'via':route['via'],'speed_mps':2.2});events.append({'event':'native_route_started','route':route['name'],'source_tick':f,'task_id':task})
  rec.step(1/30);rec.step(0);o=backend.observe(handle);status=backend.task_state(handle,task);distance=math.dist(o['position_m'],routes[i]['target']);row={'source_tick':f,'sim_time_s':tl.get_current_time(),'route':routes[i]['name'],'task_id':task,'sdk_task_state':status,'distance_m':distance,'observation':o};trace.append(row);log.write(json.dumps(row)+'\n');rec.capture(tl.get_current_time(),{'source_tick':f,'route':routes[i]['name'],'controller':'Native Behavior MoveAlong/MoveTo'})
  if status=='failed':raise RuntimeError('Native portal task failed: '+routes[i]['name'])
  if status=='succeeded' and distance<.3 and o['speed_mps']<.15:
   stable=tl.get_current_time() if stable is None else stable
   if tl.get_current_time()-stable>=.5:
    events.append({'event':'native_route_completed','route':routes[i]['name'],'source_tick':f,'sim_time_s':tl.get_current_time(),'actual_observation':o,'task_id':task});i+=1;task=None;stable=None
    if i==3:break
  else:stable=None
  if f%60==0:print('portal',f,routes[i]['name'],np.round(o['position_m'],2),status,flush=True)
 log.close();rec.close();(out/'events.json').write_text(json.dumps(events,indent=2));(out/'completed.json').write_text(json.dumps({'passed':i==3,'native_completed_routes':i,'frames':len(trace),'runtime':backend.runtime_revision,'scope':'actual Native ordinary movement through metro door and connected platform/exit; visual roof hidden after bake; no zombie gait/PhysX contact claim'},indent=2))
 if i!=3:raise RuntimeError(f'only {i}/3 real portal traversals completed')
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 if backend:backend.close()
 app.close()
raise SystemExit(code)
