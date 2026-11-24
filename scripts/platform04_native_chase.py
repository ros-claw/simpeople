"""One observed target, native follow/nav/bones. Counterfactual branch is input.

Only a perception proxy Xform is updated; actor transforms and bones remain
exclusively owned by Behavior. This is a 1v1 ordinary-jog prototype, not native
infected-sprint locomotion or multi-zombie combat.
"""
import argparse,os,sys,json,shutil,math,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--branch',choices=['north','south','occlusion'],required=True);p.add_argument('--gpu',type=int,default=2);args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,out/'source_snapshot'/Path(__file__).name);sys.path.insert(0,str(out/'source_snapshot/src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});rec=None;backend=None;code=0
try:
 import omni.usd,omni.kit.app,omni.kit.commands,carb,numpy as np
 from dataclasses import asdict
 from pxr import UsdGeom,UsdPhysics,Gf,Sdf
 from simpeople.core.pursuit import PursuitMemory,visible
 from simpeople.backends.native.platform04_scene import create_metro,aim,technical_view
 from simpeople.backends.native.recording import Recorder
 manager=omni.kit.app.get_app().get_extension_manager()
 for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:manager.set_extension_enabled_immediate(ext,True)
 from simpeople.backends.native.adapter import NativeBackend
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();scene=create_metro(stage,ROOT,collision=True);stage.GetRootLayer().customLayerData={'navmeshSettings':{'agentMaxFloorSlope':30.,'agentMaxRadius':.65,'agentMinRadius':.2,'agentMinHeight':1.6,'agentMaxStepHeight':.2,'agentMinIslandRadius':.2,'agentSamplingDistance':.12,'excludeRigidBodies':True}}
 omni.kit.commands.execute('CreateNavMeshVolumeCommand',parent_prim_path=Sdf.Path('/World'),volume_type=0);vol=stage.GetPrimAtPath('/World/NavMeshVolume');UsdGeom.XformCommonAPI(vol).SetTranslate(Gf.Vec3d(17,5,1.5));UsdGeom.XformCommonAPI(vol).SetScale(Gf.Vec3f(52,25,6))
 proxy=UsdGeom.Xform.Define(stage,'/World/ObservedTarget');proxy_op=proxy.AddTranslateOp();proxy_op.Set(Gf.Vec3d(20,4.4,0));anchor=UsdGeom.Xform.Define(stage,'/World/FacingAnchor');anchor.AddTranslateOp().Set(Gf.Vec3d(32,4.4,0))
 initial_runner=[32.3,6.4,0] if args.branch=='occlusion' else [20,4.4,0];initial_hunter=[20,4.4,0] if args.branch=='occlusion' else [14.4,4.4,0];proxy_op.Set(Gf.Vec3d(*initial_runner))
 backend=NativeBackend(ROOT,{},allow_unverified=True);backend.quality_sampling=True;backend.nav.set_random_seed('platform04',4011);runner=backend.spawn('runner','female_adult_business_02',initial_runner);hunter=backend.spawn('hunter','male_adult_construction_01',initial_hunter)
 for _ in range(8):app.update()
 if not backend.nav.start_navmesh_baking_and_wait():raise RuntimeError('metro NavMesh bake failed')
 tl=backend.timeline;tl.set_auto_update(False);tl.set_time_codes_per_second(30);tl.set_end_time(1000);tl.play();tl.commit()
 for _ in range(60):tl.forward_one_frame();app.update()
 ra=backend.agent(runner);ha=backend.agent(hunter);ha.idle(facing='/World/ObservedTarget');ra.idle(facing='/World/FacingAnchor')
 for _ in range(45):tl.forward_one_frame();app.update()
 # Three connectivity queries use the same baked, visible metric station.
 navmesh=backend.nav.get_navmesh();import omni.anim.navigation.core as nav
 profile=nav.NavAgentDesc(radius=.4,height=ra.get_height(),collision_gap=.05);connectivity=[]
 for name,start,goal in [('platform',[10,1.5,0],[26,5.8,0]),('car_to_platform',[17,-1.35,0],[25,1.5,0]),('door_to_exit',[23,.02,0],[28,11,0])]:
  path=navmesh.query_shortest_path(start_pos=carb.Float3(*start),end_pos=carb.Float3(*goal),agent=profile);points=[list(x) for x in path.get_points()] if path else [];ok=bool(points) and math.dist(points[-1],goal)<.3;connectivity.append({'name':name,'start':start,'goal':goal,'reachable':ok,'actual_navmesh_points':points})
 (out/'connectivity.json').write_text(json.dumps(connectivity,indent=2))
 if not all(r['reachable'] for r in connectivity):raise RuntimeError('one or more actual metro connectivity queries failed')
 # A technical view hides the roof AFTER baking; geometry is not removed.
 diagnostic=technical_view(stage,scene);(out/'diagnostic_view.json').write_text(json.dumps(diagnostic,indent=2));rec=Recorder(out,(1920,1080),gpu_index=args.gpu)
 for _ in range(8):rec.step(0)
 from PIL import Image
 preflight=np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3];Image.fromarray(preflight).save(out/'camera_preflight.png')
 if float((preflight.mean(axis=2)>20).mean())<.10:raise RuntimeError('technical camera occluded/black; reject footage before recording')
 ra.set_speed(2.35);runner_task=ra.move_to(target=carb.Float3(*([32.3,4.4,0] if args.branch=='occlusion' else [25,4.4,0])));ha.set_speed(1.2 if args.branch=='occlusion' else 2.95);hunter_task=ha.idle(facing='/World/ObservedTarget') if args.branch=='occlusion' else ha.follow(target='/World/ObservedTarget',distance=1.25)
 import omni.anim.behavior.core as bh
 if hunter_task==bh.BEHAVIOR_TASK_ID_INVALID:raise RuntimeError('Native follow proxy rejected')
 occluders=[]
 for b in scene['boxes']:
  if b['kind'] in ['glass','light'] or b['group'] in ['Platform','Track']:continue
  c=np.array(b['center']);h=np.array(b['size'])/2;occluders.append(((c-h).tolist(),(c+h).tolist()))
 brain=PursuitMemory();intent=None;events=[];records=[];rec.control({'mode':'start'});log=(out/'frames.jsonl').open('w');stable=None;cancel_time=None;began=tl.get_current_time();last_state=None
 for f in range(390):
  t=f/30;ro=backend.observe(runner);ho=backend.observe(hunter)
  if args.branch=='occlusion' and f==75:
   hunter_task=ha.follow(target='/World/ObservedTarget',distance=1.25);events.append({'event':'native_memory_follow_started','tick':f,'target_m':None if intent is None else intent.target_m,'state':None if intent is None else intent.state,'task':hunter_task})
  if args.branch=='occlusion' and f==90:runner_task=ra.idle();events.append({'event':'runner_holds_behind_real_column','tick':f})
  if args.branch=='occlusion' and f==150:runner_task=ra.move_to(target=carb.Float3(32.3,6.4,0));events.append({'event':'runner_reemerges','tick':f})
  if args.branch!='occlusion' and f==30:
   sign=1 if args.branch=='north' else -1;y=4.4+sign*1.65;runner_task=ra.move_along(target=[carb.Float3(24.8,y,0),carb.Float3(27.4,y,0),carb.Float3(32,4.4,0)]);events.append({'event':'runner_branch','tick':f,'choice':args.branch,'task':runner_task})
  if f%8==0 and f<300:
   seen=visible(ho['position_m'],ho['facing_direction'],ro['position_m'],occluders);intent=brain.update(t,'runner',ro['position_m'] if seen else None)
   if intent.target_m is not None:proxy_op.Set(Gf.Vec3d(*intent.target_m))
   if intent.state!=last_state:events.append({'event':'perception_state','tick':f,**asdict(intent)});last_state=intent.state
  if f==300:ha.cancel_task(hunter_task);cancel_time=tl.get_current_time();events.append({'event':'cancel_requested','tick':f,'task':hunter_task})
  rec.step(1/30);rec.step(0);ro=backend.observe(runner);ho=backend.observe(hunter);row={'source_tick':f,'relative_sim_time_s':t,'sim_time_s':tl.get_current_time(),'runner':ro,'hunter':ho,'intent':None if intent is None else asdict(intent),'runner_task':runner_task,'hunter_task':hunter_task,'hunter_task_status':str(ha.get_task_status(hunter_task))};records.append(row);log.write(json.dumps(row)+'\n');rec.capture(tl.get_current_time(),{'source_tick':f,'branch':args.branch,'controller':'Native Behavior follow + observed proxy'})
  if f in [0,30,60,90,120,180,240,299,330]:
   from PIL import Image
   Image.fromarray(np.array(rec.rgb.get_data(device='cpu'),copy=True)[:,:,:3]).save(out/f'frame_{f:04d}.png');print('frame',f,'runner',np.round(ro['position_m'],2),'hunter',np.round(ho['position_m'],2),'state',intent.state,flush=True)
  if f>=300:
   if ho['speed_mps']<.15:stable=tl.get_current_time() if stable is None else stable
   else:stable=None
   if stable is not None and tl.get_current_time()-stable>=.5:break
 log.close();rec.close();(out/'events.json').write_text(json.dumps(events,indent=2));(out/'completed.json').write_text(json.dumps({'runtime':backend.runtime_revision,'branch':args.branch,'frames':len(records),'nav_seed':4011,'actual_initial_states':{'runner':records[0]['runner']['position_m'],'hunter':records[0]['hunter']['position_m']},'one_native_follow_task':hunter_task,'cancel_settled':stable is not None and tl.get_current_time()-stable>=.5,'cancel_to_stop_and_hold_s':None if cancel_time is None else tl.get_current_time()-cancel_time,'render_diagnostic':'ceiling hidden after bake for overhead technical view; colliders/NavMesh unchanged','occlusion_probe_setup':'observer holds native Idle until tick 75 to isolate visibility/memory, then one Native follow task' if args.branch=='occlusion' else None,'scope':'Native ordinary jog movement, observation-limited proxy follow, 1v1 prototype; no Native infected sprint or multi-zombie/Agent MCP claim'},indent=2));stage.GetRootLayer().Export(str(out/'scene.usda'))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 if backend:backend.close()
 app.close()
raise SystemExit(code)
