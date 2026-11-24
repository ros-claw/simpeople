"""Own-stage direct Behavior gesture exploration; no capability promotion."""
import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3)
args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir()
for name in ['src','configs','schemas']:shutil.copytree(ROOT/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(snap/'reports').mkdir();shutil.copy2(ROOT/'reports/capability_matrix.json',snap/'reports/capability_matrix.json');shutil.copy2(__file__,snap/Path(__file__).name)
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n')
(out/'probe_config.json').write_text(json.dumps(vars(args),indent=2)+'\n')
sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
engine=journal=recorder=stream=None;code=0
try:
 import carb,omni.kit.app,omni.usd
 manager=omni.kit.app.get_app().get_extension_manager()
 for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:assert manager.set_extension_enabled_immediate(ext,True)
 import omni.anim.behavior.core as bh
 from pxr import UsdGeom,UsdSkel,Usd,Gf
 from simpeople.backends.native.scene import build_scene
 from simpeople.backends.native.reservations import ReservationNativeBackend
 from simpeople.backends.native.recording import Recorder
 from simpeople.core.engine import Engine
 from simpeople.core.journal import Journal
 from simpeople.tools.runtime_contract import capture_runtime_contract
 omni.usd.get_context().new_stage();sem=build_scene(False)
 backend=ReservationNativeBackend(ROOT,sem,False,config_dir=snap/'configs',capability_file=snap/'reports/capability_matrix.json');backend.enable_corridor_profile();backend.quality_sampling=True
 journal=Journal(out,{'scenario':'native_gestures_exploration','gpu':args.gpu,'width':1920,'height':1080,'warmup_wall_s':30});engine=Engine(backend,journal)
 def call(method,params):return engine.call(method,{'controller_id':'gesture-probe',**params})
 for aid,asset,pos in [('operator','default',[0,0,0]),('second','female_adult_business_02',[2.2,0,0]),('witness','default',[-5,-3,0])]:
  call('spawn',{'actor_id':aid,'asset_id':asset,'spawn_anchor':pos,'request_id':aid})
 for _ in range(5):app.update()
 assert backend.nav.start_navmesh_baking_and_wait()
 timeline=backend.timeline;timeline.set_time_codes_per_second(30);timeline.set_end_time(100000);timeline.set_auto_update(False);timeline.set_play_every_frame(True);timeline.play()
 for _ in range(120):
  timeline.forward_one_frame();app.update()
  if all(backend.observe(a['handle']).get('ready') for a in engine.actors.values()):break
 assert all(backend.observe(a['handle']).get('ready') for a in engine.actors.values())
 for a in engine.actors.values():backend.agent(a['handle']).idle(facing=carb.Float3(0,-1,0))
 for _ in range(60):timeline.forward_one_frame();app.update()
 capture_runtime_contract(ROOT,out,backend=backend,engine=engine,extensions=[e for e in manager.get_extensions() if e.get('enabled') and 'omni.anim.' in e['id']])
 camera=UsdGeom.Xformable(backend.stage.GetPrimAtPath('/World/Camera'));camera.GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(1.1,-5,2.2),Gf.Vec3d(1.1,0,1),Gf.Vec3d(0,0,1)).GetInverse())
 recorder=Recorder(out,(1920,1080),gpu_index=args.gpu);backend.recorder=recorder
 for _ in range(5):recorder.step(0)
 origin=timeline.get_current_time();engine.tick(origin);recorder.control({'mode':'start'});stream=(out/'gestures.jsonl').open('w')
 baseline={aid:dict(backend.observe(engine.actors[aid]['handle'])) for aid in ['operator','second']}
 for aid,obs in baseline.items():
  skel=next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(backend.stage.GetPrimAtPath(engine.actors[aid]['handle'])) if p.IsA(UsdSkel.Skeleton))
  index=backend.agent(engine.actors[aid]['handle']).get_joint_index('Head');names=list(skel.GetJointsAttr().Get())
  assert names[index].rsplit('/',1)[-1].rsplit(':',1)[-1]=='Head'
  bind=skel.GetBindTransformsAttr().Get()[index]*UsdGeom.XformCache().GetLocalToWorldTransform(skel.GetPrim())
  local=bind.GetInverse().TransformDir(Gf.Vec3d(0,-1,0));local.Normalize();obs['head_local_forward']=list(local)
 descriptions=[('neutral',2,None),('look_left',3,(-.8,-1,1.55)),('look_right',3,(.8,-1,1.55)),('look_high',3,(0,-1,2.1)),('look_low',3,(0,-1,1.0)),
  ('left_low',3,('left',1.05,.32)),('right_low',3,('right',1.05,.32)),('left_high',3,('left',1.45,.32)),('right_high',3,('right',1.45,.32)),
  ('left_edge',3,('left',1.3,.48)),('right_edge',3,('right',1.3,.48)),('cancel_reach',1,('right',1.25,.32)),('after_cancel',2,None),('walk_resume',6,None)]
 expanded=[]
 for description in descriptions:
  expanded.append(description)
  if description[2] is not None:expanded.append(('recover_'+description[0],1,None))
 descriptions=expanded
 phases=[];active={};start=0
 for name,duration,config in descriptions:
  targets={};ids={};phase_baseline={}
  for aid in ['operator','second']:
   handle=engine.actors[aid]['handle'];agent=backend.agent(handle)
   if aid in active:agent.cancel_task(active[aid]);active.pop(aid)
   if name.startswith('recover_') or name=='after_cancel':agent.idle(facing=carb.Float3(0,-1,0))
   obs=backend.observe(handle);root=baseline[aid]['position_m'];phase_baseline[aid]={**obs,'head_local_forward':baseline[aid]['head_local_forward']}
   if name.startswith('look_'):
    target=[root[0]+config[0],root[1]+config[1],root[2]+config[2]]
    tid=agent.look_at(tuple(backend.to_stage(target)),duration=duration)
   elif config is not None:
    side,height,forward=config;shoulder=obs['joints_m'].get(side.title()+'Arm') or obs['joints_m'].get(side.title()+'Shoulder')
    assert shoulder is not None,obs['joints_m']
    target=[shoulder[0],root[1]-forward,root[2]+height]
    tid=agent.reach_hand(bh.BehaviorHandUsage.LEFT_HAND if side=='left' else bh.BehaviorHandUsage.RIGHT_HAND,tuple(backend.to_stage(target)),duration=duration)
   else:target=None;tid=None
   if tid is not None:
    assert tid!=bh.BEHAVIOR_TASK_ID_INVALID,(aid,name);active[aid]=tid
   targets[aid]=target;ids[aid]=tid
  if name=='walk_resume':
   for aid in ['operator','second']:
    root=baseline[aid]['position_m'];call('move_to',{'request_id':'resume_'+aid,'actor_id':aid,'target':[root[0],root[1]-2,0],'timeout_s':10})
  if name=='neutral':call('move_to',{'request_id':'witness_move','actor_id':'witness','target':[-5,5,0],'timeout_s':20})
  phase={'name':name,'start_s':start,'duration_s':duration,'targets_m':targets,'native_task_ids':ids,'baseline':phase_baseline};phases.append(phase);print('GESTURE_PHASE',name,flush=True)
  for index in range(round(duration*30)):
   recorder.step(1/30);engine.tick(timeline.get_current_time());identity={'source_tick':journal.frames,'relative_sim_time':timeline.get_current_time()-origin}
   recorder.capture(timeline.get_current_time(),identity);journal.sample(engine,identity)
   for aid in ['operator','second']:
    handle=engine.actors[aid]['handle'];obs=backend.observe(handle);tid=ids[aid]
    stream.write(json.dumps({'phase':name,'phase_time_s':(index+1)/30,'actor_id':aid,'target_m':targets[aid],'gesture_task_id':tid,
     'gesture_task_status':str(backend.agent(handle).get_task_status(tid)) if tid is not None else None,'native_error':backend.task_error(handle,tid) if tid is not None else None,**obs})+'\n')
  start+=duration
 stream.close();stream=None
 journal.write('gesture_phases.json',{'baseline':baseline,'phases':phases,'capabilities_promoted':False})
 journal.write('asset_manifest.json',backend.assets);journal.write('measurement_end_state.json',engine.cmd_get_state({}))
 journal.write('completed.json',{'harness_completed':True,'duration_s':start,'frames':recorder.frames,'capabilities_promoted':False})
 print('GESTURE_EXPLORATION_DONE',flush=True)
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if stream:stream.close()
 if recorder:recorder.close()
 if engine:
  for aid in list(engine.actors):engine.abort_actor(aid,'process_shutdown')
  engine.backend.close();journal.finish(engine,exit_code=code)
 app.close(exit_code=code)
raise SystemExit(code)
