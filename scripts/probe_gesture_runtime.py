"""Own-stage Engine gesture hold/cancel/recovery acceptance."""
import argparse
import hashlib
import json
import math
import shutil
import sys
from collections import deque
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);p.add_argument('--strict',action='store_true');p.add_argument('--host-probe',action='store_true');p.add_argument('--port',type=int,default=8881)
p.add_argument('--hold-seconds',type=float,default=.6);p.add_argument('--experimental-hold',action='store_true')
p.add_argument('--experimental-base-clips')
p.add_argument('--idle-profile',choices=['default','basic'],default='default')
p.add_argument('--pose-contexts',action='store_true',help='Retain four actual full-SDK poses from each successful hold')
p.add_argument('--workspace-root',default=str(ROOT));p.add_argument('--source-root')
p.add_argument('--diagnostic-idle-tags',choices=['default','basic','disabled'],default='default')
p.add_argument('--diagnostic-response-profile',choices=['default','fixed30'],default='default')
p.add_argument('--diagnostic-seed',type=int)
args=p.parse_args()
ROOT=Path(args.workspace_root).resolve();source=Path(args.source_root or ROOT).resolve()
if not math.isfinite(args.hold_seconds) or not .01<=args.hold_seconds<=5:p.error('hold seconds must be in [.01,5]')
if args.experimental_hold and args.strict:p.error('experimental hold cannot use strict qualification')
if args.experimental_base_clips and not args.experimental_hold:p.error('alternate base requires experimental hold mode')
if (args.diagnostic_idle_tags!='default' or args.diagnostic_response_profile!='default' or args.diagnostic_seed is not None) and not args.experimental_hold:p.error('SDK setting counterfactuals require experimental hold mode')
if args.diagnostic_seed is not None and not 0<=args.diagnostic_seed<2**31:p.error('diagnostic seed must be a nonnegative 31-bit integer')
if args.idle_profile!='default' and (args.experimental_hold or args.diagnostic_idle_tags!='default' or args.diagnostic_response_profile!='default' or args.diagnostic_seed is not None):p.error('use the product startup profile separately from diagnostic setting overrides')
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir()
for name in ['src','configs','schemas']:shutil.copytree(source/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.egg-info'))
(snap/'reports').mkdir();shutil.copy2(source/'reports/capability_matrix.json',snap/'reports/capability_matrix.json');shutil.copy2(__file__,snap/Path(__file__).name)
if args.experimental_hold:
 catalog=snap/'configs/native_gesture_catalog.json';data=json.loads(catalog.read_text())
 for record in data['records']:
  record.update(status='discovered',max_hold_duration_s=max(.6,args.hold_seconds),scope='Run-local exploration; does not promote the installed catalog.')
 catalog.write_text(json.dumps(data,indent=2)+'\n')
if args.experimental_base_clips:
 shutil.copytree(Path(args.experimental_base_clips).resolve(),snap/'base_inputs');registry=json.loads((snap/'base_inputs/actions.json').read_text())
 registry['actions']={'mb_stand':registry['actions']['mb_stand']};registry['actions']['mb_stand'].update(clip=str(snap/'base_inputs/mb_stand.usda'),skeleton=str(out/'prepared_base_rig.usda'))
 (snap/'configs/custom_actions.json').write_text(json.dumps(registry,indent=2)+'\n');(snap/'configs/custom_action_acceptance.json').write_text('{}\n')
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n')
(out/'probe_config.json').write_text(json.dumps(vars(args),indent=2)+'\n')
sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
engine=journal=recorder=stream=bridge=None;code=0
try:
 import carb,carb.settings,omni.kit.app,omni.usd
 manager=omni.kit.app.get_app().get_extension_manager()
 for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:assert manager.set_extension_enabled_immediate(ext,True)
 settings=carb.settings.get_settings();idle_key='/exts/omni.anim.behavior.core/idleAnimationTags';original_idle=settings.get(idle_key)
 response_keys=['/exts/omni.anim.behavior.core/'+n for n in ['agentResponseTime','agentResponseTimeMaxRandomOffset','navBlockedTimeout']];original_response={k:settings.get(k) for k in response_keys}
 if args.diagnostic_response_profile=='fixed30' or args.idle_profile=='basic':
  for key,value in zip(response_keys,[1/30,0.,3.]):settings.set(key,value)
 if args.diagnostic_idle_tags!='default':settings.set(idle_key,['Idle'] if args.diagnostic_idle_tags=='basic' else ['']*len(original_idle or range(7)))
 startup_profile=None
 if args.idle_profile=='basic':
  from simpeople.backends.native.idle_profile import configure_idle_profile
  startup_profile=configure_idle_profile(settings,'basic')
 (out/'sdk_idle_settings.json').write_text(json.dumps({'mode':args.idle_profile if startup_profile else args.diagnostic_idle_tags,'startup_profile':startup_profile,'original_tags':original_idle,'active_tags':settings.get(idle_key),'response_profile':'fixed30' if startup_profile else args.diagnostic_response_profile,'original_response':original_response,'active_response':{k:settings.get(k) for k in response_keys},'requested_api_seed':42 if startup_profile else args.diagnostic_seed,'scope':'Dedicated process before agents/Play. Product startup profile is distinct from diagnostic overrides; accepted domains still require exact-revision catalog evidence. A seed is not a deterministic-native guarantee.'},indent=2)+'\n')
 import omni.anim.behavior.core as bh
 from pxr import UsdGeom,UsdSkel,Usd,Gf
 from simpeople.backends.native.scene import build_scene
 from simpeople.backends.native.reservations import ReservationNativeBackend
 from simpeople.backends.native.recording import Recorder
 from simpeople.core.engine import Engine
 from simpeople.core.journal import Journal
 from simpeople.tools.bridge import Bridge
 from simpeople.tools.runtime_contract import capture_runtime_contract
 omni.usd.get_context().new_stage();sem=build_scene(False)
 backend=ReservationNativeBackend(ROOT,sem,not args.strict,config_dir=snap/'configs',capability_file=snap/'reports/capability_matrix.json');backend.enable_corridor_profile();backend.quality_sampling=True
 if startup_profile:backend.native_idle_profile=startup_profile
 if startup_profile:backend.api.set_random_seed(42)
 if args.diagnostic_seed is not None:backend.api.set_random_seed(args.diagnostic_seed)
 if args.experimental_base_clips:
  from simpeople.backends.native.motion_import import prepare_soma_rig
  from simpeople.backends.native.custom_actions import register
  (out/'prepared_base_rig.json').write_text(json.dumps(prepare_soma_rig(snap/'base_inputs/soma_native.usda',out/'prepared_base_rig.usda'),indent=2)+'\n')
  register(backend,out/'custom_actions');backend.experimental_gesture_base='mb_stand'
 journal=Journal(out,{'scenario':'native_gestures_exploration','gpu':args.gpu,'width':1920,'height':1080,'warmup_wall_s':30});engine=Engine(backend,journal)
 bridge=Bridge(engine,args.port)
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
 baseline={aid:dict(backend.observe(engine.actors[aid]['handle'])) for aid in ['operator','second']};pose_joints={};pose_windows={}
 for aid,obs in baseline.items():
  skel=next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(backend.stage.GetPrimAtPath(engine.actors[aid]['handle'])) if p.IsA(UsdSkel.Skeleton))
  index=backend.agent(engine.actors[aid]['handle']).get_joint_index('Head');names=list(skel.GetJointsAttr().Get())
  pose_joints[aid]=list(map(str,names))
  assert names[index].rsplit('/',1)[-1].rsplit(':',1)[-1]=='Head'
  bind=skel.GetBindTransformsAttr().Get()[index]*UsdGeom.XformCache().GetLocalToWorldTransform(skel.GetPrim())
  local=bind.GetInverse().TransformDir(Gf.Vec3d(0,-1,0));local.Normalize();obs['head_local_forward']=list(local)
 from simpeople.core.errors import SimPeopleError
 phases=[];outcomes=[];negative=[]
 def frame(name,targets=None,ids=None):
  bridge.drain()
  recorder.step(1/30);engine.tick(timeline.get_current_time());identity={'source_tick':journal.frames,'relative_sim_time':timeline.get_current_time()-origin}
  recorder.capture(timeline.get_current_time(),identity);journal.sample(engine,identity)
  for aid in ['operator','second']:
   task=engine.tasks.get(ids.get(aid) if ids else engine.actors[aid]['task_id'],{});obs=backend.observe(engine.actors[aid]['handle'])
   stream.write(json.dumps({'phase':name,'actor_id':aid,'target_m':(targets or {}).get(aid),'task':engine.public(task) if task else None,**obs})+'\n')
   if args.pose_contexts and task.get('step_phase')=='gesture_holding':
    agent=backend.agent(engine.actors[aid]['handle']);world=[]
    for index in range(len(pose_joints[aid])):
     point=carb.Float3(0,0,0);q=carb.Float4(0,0,0,1);assert agent.get_joint_world_transform(index,point,q)
     world.append([*backend.to_public(point),q.x,q.y,q.z,q.w])
    window=pose_windows.setdefault((aid,name),deque(maxlen=4));sample_time=timeline.get_current_time()
    if window and abs(sample_time-window[-1]['sim_time']-1/30)>1e-6:window.clear()
    window.append({'phase':name,'actor_id':aid,'actor_instance_id':engine.actors[aid]['actor_instance_id'],'sim_time':sample_time,'joint_paths':pose_joints[aid],'world_pose':world,'actual_observation':obs,'task':engine.public(task)})
 def recover(name,duration=1):
  for aid in ['operator','second']:backend.stop(engine.actors[aid]['handle'])
  for _ in range(round(duration*30)):frame(name)
 # Invalid replacements must not steal the old controller/actor plan.
 old=call('run_activity',{'request_id':'old','actor_id':'operator','steps':[{'action':'wait','duration_s':2}]})['task_id']
 for label,spec in [('far',{'action':'reach_hand','hand':'right','target':[0,-5,1.1],'duration_s':.6}),('behind',{'action':'head_look','target':[0,1,1.6],'duration_s':.6})]:
  before=(engine.controller_epoch,engine.actors['operator']['control_epoch'],engine.actors['operator']['task_id'],len(engine.tasks))
  try:call('run_activity',{'request_id':'bad_'+label,'actor_id':'operator','steps':[spec]})
  except SimPeopleError as error:
   negative.append({'case':label,'error':error.as_dict(),'old_task_preserved':before==(engine.controller_epoch,engine.actors['operator']['control_epoch'],engine.actors['operator']['task_id'],len(engine.tasks))})
  else:raise AssertionError('invalid replacement was accepted')
 assert all(r['old_task_preserved'] and r['error']['code']=='TARGET_UNREACHABLE' for r in negative),negative
 call('cancel',{'request_id':'old_cancel','task_id':old});recover('initial_settle')
 witness=call('move_to',{'request_id':'witness_move','actor_id':'witness','target':[-5,5,0],'timeout_s':20})['task_id']
 trials=[('look_left','head_look',None,(-.8,-1,1.55)),('look_right','head_look',None,(.8,-1,1.55)),
  ('look_high','head_look',None,(0,-1,2.1)),('look_low','head_look',None,(0,-1,1.0)),
  ('left_low','reach_hand','left',(1.15,.32)),('right_low','reach_hand','right',(1.15,.32)),
  ('left_high','reach_hand','left',(1.45,.32)),('right_high','reach_hand','right',(1.45,.32)),
  ('left_edge','reach_hand','left',(1.3,.48)),('right_edge','reach_hand','right',(1.3,.48)),('cancel_reach','reach_hand','right',(1.25,.32))]
 for name,action,hand,config in trials:
  ids={};targets={};began=timeline.get_current_time();phase_base={}
  for aid in ['operator','second']:
   obs=backend.observe(engine.actors[aid]['handle']);root=obs['position_m'];phase_base[aid]=obs
   if action=='head_look':
    head=obs['joints_m']['Head'];f=obs['facing_direction'];right=[-f[1],f[0]]
    target=[head[0]+f[0]+right[0]*config[0],head[1]+f[1]+right[1]*config[0],root[2]+config[2]]
   else:
    shoulder=obs['joints_m'][hand.title()+'Arm'];f=obs['facing_direction']
    if name.endswith('_edge'):
     elbow=obs['joints_m'][hand.title()+'ForeArm'];wrist=obs['joints_m'][hand.title()+'Hand'];length=math.dist(shoulder,elbow)+math.dist(elbow,wrist)
     target=[shoulder[0]+f[0]*length*.85,shoulder[1]+f[1]*length*.85,shoulder[2]]
    else:target=[shoulder[0]+f[0]*config[1],shoulder[1]+f[1]*config[1],root[2]+config[0]]
   targets[aid]=target;spec={'action':action,'target':target,'duration_s':args.hold_seconds,'timeout_s':8}
   if hand:spec['hand']=hand
   ids[aid]=call('run_activity',{'request_id':name+'_'+aid,'actor_id':aid,'steps':[spec]})['task_id']
  print('MANAGED_GESTURE',name,flush=True);cancelled=False
  for _ in range(300):
   if name=='cancel_reach' and not cancelled and timeline.get_current_time()-began>=.4:
    for aid,tid in ids.items():call('cancel',{'request_id':'cancel_'+aid,'task_id':tid})
    cancelled=True
   frame(name,targets,ids)
   if all(engine.tasks[tid]['status'] in {'succeeded','failed','cancelled'} for tid in ids.values()):break
  rows=[{'actor_id':aid,**engine.public(engine.tasks[tid])} for aid,tid in ids.items()];outcomes.extend(rows)
  phases.append({'name':name,'action':action,'targets_m':targets,'baseline':phase_base,'tasks':rows,'start_s':began-origin,'duration_s':timeline.get_current_time()-began})
  recover('recover_'+name)
 # A target moving during execution must fail explicitly and finish its native
 # return even after the high-level task has become terminal.
 obs=backend.observe(engine.actors['operator']['handle']);head=obs['joints_m']['Head'];f=obs['facing_direction'];moving_position=[head[i]+f[i] for i in range(3)]
 moving=UsdGeom.Xform.Define(backend.stage,'/World/GestureProbe/MovingLook');moving.AddTranslateOp().Set(Gf.Vec3d(*moving_position))
 moved_task=call('run_activity',{'request_id':'moving_target','actor_id':'operator','steps':[{'action':'head_look','target':str(moving.GetPath()),'duration_s':.6,'timeout_s':8}]})['task_id']
 for index in range(210):
  if index==12:
   moving_position[0]+=.15;moving.GetOrderedXformOps()[0].Set(Gf.Vec3d(*moving_position))
  frame('target_moved')
  if index>12 and engine.tasks[moved_task]['status']=='failed' and not backend.instances[engine.actors['operator']['handle']].get('gesture'):break
 moved_state=engine.public(engine.tasks[moved_task]);moved_cleanup=not backend.instances[engine.actors['operator']['handle']].get('gesture')
 resume={}
 for aid in ['operator','second']:
  root=backend.observe(engine.actors[aid]['handle'])['position_m'];resume[aid]=call('move_to',{'request_id':'resume_'+aid,'actor_id':aid,'target':[root[0]+(-2 if aid=='operator' else 2),root[1],0],'timeout_s':15})['task_id']
 for _ in range(450):
  frame('walk_resume')
  if all(engine.tasks[t]['status'] in {'succeeded','failed','cancelled'} for t in resume.values()):break
 if args.host_probe:
  import time
  (out/'host_ready.json').write_text(json.dumps({'endpoint':f'http://127.0.0.1:{args.port}'}));until=time.monotonic()+120
  while not (out/'mcp_gesture_probe.json').exists() and time.monotonic()<until:frame('mcp_host')
  assert (out/'mcp_gesture_probe.json').exists(),'MCP host probe did not finish'
  assert json.loads((out/'mcp_gesture_probe.json').read_text())['passed']
 overlay_states=[];base_states=[]
 for line in (out/'events.jsonl').open():
  event=json.loads(line)
  if event['kind'] not in {'native_gesture_started','native_gesture_return_started'}:continue
  status=backend.agent(event['agent']).get_task_status(int(event['native_task_id']))
  overlay_states.append({'agent':event['agent'],'native_task_id':event['native_task_id'],'status':str(status),'ended':status!=bh.BehaviorTaskStatus.RUNNING})
  if event.get('base_task_id') is not None:
   status=backend.agent(event['agent']).get_task_status(int(event['base_task_id']))
   base_states.append({'agent':event['agent'],'native_task_id':event['base_task_id'],'status':str(status),'ended':status!=bh.BehaviorTaskStatus.RUNNING})
 stream.close();stream=None
 if args.pose_contexts:
  with (out/'native_pose_contexts.jsonl').open('w') as context_file:
   for window in pose_windows.values():
    for sample in window:context_file.write(json.dumps(sample,allow_nan=False)+'\n')
 checks={'negative_replacements_preserved':all(r['old_task_preserved'] for r in negative),'holds_and_releases_succeeded':all(t['status']=='succeeded' for p in phases if p['name']!='cancel_reach' for t in p['tasks']),
  'explicit_cancellation_settled':all(t['status']=='cancelled' and t.get('physical_stop_verified') for p in phases if p['name']=='cancel_reach' for t in p['tasks']),
  'walk_resume_succeeded':all(engine.tasks[t]['status']=='succeeded' for t in resume.values()),'witness_succeeded':engine.tasks[witness]['status']=='succeeded',
  'moved_target_failed_and_released':moved_state['status']=='failed' and (moved_state.get('error') or {}).get('code')=='TARGET_STALE' and moved_cleanup,
  'owned_overlays_ended':bool(overlay_states) and all(row['ended'] for row in overlay_states) and all(not a.get('gesture') for a in backend.instances.values()),
  'owned_experimental_bases_ended':not args.experimental_base_clips or bool(base_states) and all(row['ended'] for row in base_states)}
 journal.write('gesture_runtime_acceptance.json',{'passed':all(checks.values()),'strict_catalog':args.strict,'checks':checks,'negative_requests':negative,'phases':phases,'owned_overlay_states':overlay_states,'owned_base_states':base_states,'moved_target_task':moved_state,'resume_tasks':[engine.public(engine.tasks[t]) for t in resume.values()],'witness_task':engine.public(engine.tasks[witness])})
 journal.write('asset_manifest.json',backend.assets);journal.write('measurement_end_state.json',engine.cmd_get_state({}))
 journal.write('completed.json',{'harness_completed':True,'functional_expected_matched':all(checks.values()),'duration_s':timeline.get_current_time()-origin,'frames':recorder.frames})
 print('MANAGED_GESTURE_DONE',checks,flush=True)
 code=0 if all(checks.values()) else 2
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if bridge:bridge.close()
 if stream:stream.close()
 if recorder:recorder.close()
 if engine:
  for aid in list(engine.actors):engine.abort_actor(aid,'process_shutdown')
  engine.backend.close();journal.finish(engine,exit_code=code)
 app.close(exit_code=code)
raise SystemExit(code)
