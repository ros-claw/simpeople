"""Probe live native action visibility without restarting the world."""
import argparse,hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--clip-dir',required=True);p.add_argument('--gpu',type=int,default=3);args=p.parse_args()
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir()
for name in ['src','configs','schemas']:shutil.copytree(ROOT/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copytree(Path(args.clip_dir).resolve(),snap/'inputs');registry=json.loads((snap/'inputs/actions.json').read_text())
for name,entry in registry['actions'].items():
 entry['clip']=str(snap/'inputs'/(name+'.usda'))
 if (snap/'inputs/soma_native.usda').is_file():entry['skeleton']=str(out/'prepared_rig.usda')
(snap/'configs/custom_actions.json').write_text(json.dumps(registry,indent=2)+'\n');(snap/'configs/custom_action_acceptance.json').write_text('{}\n')
(snap/'reports').mkdir();shutil.copy2(ROOT/'reports/capability_matrix.json',snap/'reports/capability_matrix.json');shutil.copy2(__file__,snap/Path(__file__).name)
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n')
(out/'probe_config.json').write_text(json.dumps(vars(args),indent=2)+'\n');sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
engine=journal=recorder=stream=None;code=0
try:
 import omni.kit.app,omni.usd,carb
 from pxr import Usd,UsdGeom,UsdSkel,Gf
 manager=omni.kit.app.get_app().get_extension_manager()
 for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:assert manager.set_extension_enabled_immediate(ext,True)
 from simpeople.backends.native.scene import build_scene
 from simpeople.backends.native.reservations import ReservationNativeBackend
 from simpeople.backends.native.custom_actions import register
 from simpeople.backends.native.recording import Recorder
 from simpeople.core.engine import Engine
 from simpeople.core.journal import Journal
 from simpeople.tools.runtime_contract import capture_runtime_contract
 omni.usd.get_context().new_stage();sem=build_scene(False);stage=omni.usd.get_context().get_stage()
 backend=ReservationNativeBackend(ROOT,sem,True,config_dir=snap/'configs',capability_file=snap/'reports/capability_matrix.json');backend.enable_corridor_profile();backend.quality_sampling=True
 # Prepare an explicit SOMA derivative before native SDK import. No live actor
 # pose writes; no edits to the official model/source rig.
 if (snap/'inputs/soma_native.usda').is_file():
  from simpeople.backends.native.motion_import import prepare_soma_rig
  (out/'prepared_rig_tags.json').write_text(json.dumps(prepare_soma_rig(snap/'inputs/soma_native.usda',out/'prepared_rig.usda'),indent=2))
 register(backend,out/'custom_actions')
 journal=Journal(out,{'scenario':'generated_native_preload','gpu':args.gpu,'width':1920,'height':1080,'warmup_wall_s':30});engine=Engine(backend,journal)
 def call(method,params):return engine.call(method,{'controller_id':'generated-native-probe',**params})
 for aid,asset,position in [('operator','default',[-3,-7,0]),('second','female_adult_business_02',[3,-7,0]),('witness','default',[-7,-3,0])]:
  call('spawn',{'request_id':aid,'actor_id':aid,'asset_id':asset,'spawn_anchor':position})
 for _ in range(6):app.update()
 assert backend.nav.start_navmesh_baking_and_wait()
 timeline=backend.timeline;timeline.set_time_codes_per_second(30);timeline.set_end_time(100000);timeline.set_auto_update(False);timeline.set_play_every_frame(True);timeline.play()
 for _ in range(120):
  timeline.forward_one_frame();app.update()
  if all(backend.observe(a['handle']).get('ready') for a in engine.actors.values()):break
 assert all(backend.observe(a['handle']).get('ready') for a in engine.actors.values())
 for a in engine.actors.values():backend.agent(a['handle']).idle()
 for _ in range(30):timeline.forward_one_frame();app.update()
 capture_runtime_contract(ROOT,out,backend=backend,engine=engine,extensions=[e for e in manager.get_extensions() if e.get('enabled') and 'omni.anim.' in e['id']])
 camera=UsdGeom.Camera(stage.GetPrimAtPath('/World/Camera'));camera.CreateFocalLengthAttr(24);camera.CreateHorizontalApertureAttr(36);camera.CreateVerticalApertureAttr(20.25)
 UsdGeom.Xformable(camera).GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(0,-15.5,3),Gf.Vec3d(0,-5.8,1),Gf.Vec3d(0,0,1)).GetInverse())
 recorder=Recorder(out,(1920,1080),gpu_index=args.gpu);backend.recorder=recorder
 for _ in range(5):recorder.step(0)
 recorder.control({'mode':'start'});origin=timeline.get_current_time();engine.tick(origin);stream=(out/'native_pose_history.jsonl').open('w');joint_paths={}
 joint_name_checks={}
 for aid in ['operator','second']:
  handle=engine.actors[aid]['handle'];sk=next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(stage.GetPrimAtPath(handle)) if p.IsA(UsdSkel.Skeleton));joint_paths[aid]=list(sk.GetJointsAttr().Get())
  head=backend.agent(handle).get_joint_index('Head');assert joint_paths[aid][head].rsplit('/',1)[-1].rsplit(':',1)[-1]=='Head'
  joint_name_checks[aid]={str(name):backend.agent(handle).get_joint_index(str(name).rsplit('/',1)[-1]) for name in joint_paths[aid]}
  for index,name in enumerate(joint_paths[aid]):
   actual=joint_name_checks[aid][str(name)]
   if 0<=actual<len(joint_paths[aid]):assert actual==index,(aid,name,index,actual)
 journal.write('joint_index_checks.json',joint_name_checks)
 import copy,math
 from simpeople.core.errors import SimPeopleError
 initial=copy.deepcopy(registry);assert {'mb_stand','mb_arm'}<=set(initial['actions'])
 runtime_configs=out/'publication_configs';shutil.copytree(snap/'configs',runtime_configs);backend.config_dir=runtime_configs
 samples=[];matrix=[]
 def frame(label):
  recorder.step(1/30);engine.tick(timeline.get_current_time());identity={'source_tick':journal.frames,'relative_sim_time':timeline.get_current_time()-origin};recorder.capture(timeline.get_current_time(),identity);journal.sample(engine,identity)
  for aid,a in engine.actors.items():
   agent=backend.agent(a['handle']);row={'phase':label,'actor_id':aid,'actor_instance_id':a['actor_instance_id'],'sim_time':timeline.get_current_time(),'native_task_id':agent.get_action_task_id(),'observation':backend.observe(a['handle']),'custom_actions':list(agent.get_custom_action_names())}
   samples.append(row);stream.write(json.dumps(row)+'\n')
 def settle(tid,label,limit=450):
  for _ in range(limit):
   frame(label)
   if engine.tasks[tid]['status'] in {'succeeded','failed','cancelled'}:return engine.tasks[tid]['status']
  return 'not_terminal'
 def snapshot(aid):
  handle=engine.actors[aid]['handle'];agent=backend.agent(handle)
  return {'actor_instance_id':engine.actors[aid]['actor_instance_id'],'native_task_id':agent.get_action_task_id(),'observation':backend.observe(handle),'custom_actions':list(agent.get_custom_action_names())}
 witness=call('run_activity',{'request_id':'witness_patrol','actor_id':'witness','steps':[{'action':'move_to','target':[-7,y,0],'timeout_s':25} for y in [3,-3]*6]})['task_id']
 for _ in range(20):frame('warmup_patrol')
 publication_safe=True
 for state in ['idle','walking','custom_action']:
  spec={'idle':{'action':'wait','duration_s':20},'walking':{'action':'move_to','target':[-3,5,0],'timeout_s':25},'custom_action':{'action':'custom_action','target':'mb_stand','duration_s':20,'timeout_s':30}}[state]
  current=call('run_activity',{'request_id':'state_'+state,'actor_id':'operator','steps':[spec]})['task_id']
  for _ in range(12):frame('before_'+state)
  before={aid:snapshot(aid) for aid in ['operator','second','witness']};old=copy.deepcopy(initial);name='reload_'+state
  initial['actions'][name]=copy.deepcopy(initial['actions']['mb_arm'])
  (runtime_configs/'custom_actions.json').write_text(json.dumps(initial,indent=2)+'\n');journal.write('publication_'+state+'.json',initial)
  error=None
  try:register(backend,out/('import_'+state))
  except Exception as exc:error=type(exc).__name__+': '+str(exc)
  for _ in range(3):frame('after_'+state)
  after={aid:snapshot(aid) for aid in before}
  witness_unchanged=before['witness']['native_task_id']==after['witness']['native_task_id'] and before['witness']['actor_instance_id']==after['witness']['actor_instance_id'] and math.dist(before['witness']['observation']['position_m'],after['witness']['observation']['position_m'])<.5
  row={'state':state,'name':name,'error':error,'before':before,'after':after,'witness_unchanged':witness_unchanged,'existing_visible':name in after['operator']['custom_actions'],'old_actions_preserved':all(n in after['operator']['custom_actions'] for n in old['actions'])}
  # Stop this branch if publication disrupts others; never rebuild their agents.
  if error or not witness_unchanged or not row['old_actions_preserved']:
   publication_safe=False;matrix.append(row);break
  call('cancel',{'request_id':'stop_state_'+state,'task_id':current});row['cancel_status']=settle(current,'cancel_'+state)
  new_aid='fresh_'+state;call('spawn',{'request_id':new_aid,'actor_id':new_aid,'asset_id':'default','spawn_anchor':[6,-2+['idle','walking','custom_action'].index(state)*3,0]})
  for _ in range(90):
   frame('new_agent_'+state)
   if backend.observe(engine.actors[new_aid]['handle']).get('ready'):break
  row['new_agent']=snapshot(new_aid);row['new_visible']=name in row['new_agent']['custom_actions']
  for aid in ['operator',new_aid]:
   trial={'actor_id':aid}
   try:
    tid=call('run_activity',{'request_id':'play_'+state+'_'+aid,'actor_id':aid,'steps':[{'action':'custom_action','target':name,'duration_s':1,'timeout_s':10}]})['task_id'];trial['task_id']=tid;trial['status']=settle(tid,'play_'+state+'_'+aid)
    trial['actual_action_observed']=any(s['phase']=='play_'+state+'_'+aid and s['actor_id']==aid and s['observation'].get('action')==name for s in samples)
   except SimPeopleError as exc:trial['status']='rejected';trial['error']=exc.as_dict()
   row.setdefault('playback_trials',[]).append(trial)
  matrix.append(row)
 failed_import=None
 if publication_safe:
  # A real SDK import failure, rather than a missing-file short circuit.
  invalid=out/'invalid_skeleton.usda';bad=Usd.Stage.CreateNew(str(invalid));prim=UsdGeom.Xform.Define(bad,'/NotASkeleton');bad.SetDefaultPrim(prim.GetPrim());bad.GetRootLayer().Save()
  failure=copy.deepcopy(initial);failure['actions']={'broken_import':{**initial['actions']['mb_arm'],'skeleton':str(invalid)}}
  (runtime_configs/'custom_actions.json').write_text(json.dumps(failure,indent=2)+'\n');before={aid:snapshot(aid) for aid in ['operator','witness']};error=None
  try:register(backend,out/'failed_import')
  except Exception as exc:error=type(exc).__name__+': '+str(exc)
  for _ in range(3):frame('failed_import')
  after={aid:snapshot(aid) for aid in before}
  failed_import={'error':error,'before':before,'after':after,'metadata_preserved':all(n in backend.custom_actions for n in initial['actions']),'native_old_actions_preserved':all(n in after['operator']['custom_actions'] for n in initial['actions'])}
 def trials_pass(row,prefix):
  trial=[t for t in row.get('playback_trials',[]) if t['actor_id'].startswith(prefix)]
  return bool(trial) and all(t['status']=='succeeded' and t.get('actual_action_observed') for t in trial)
 all_existing=len(matrix)==3 and all(r.get('existing_visible') and trials_pass(r,'operator') for r in matrix)
 all_new=len(matrix)==3 and all(r.get('new_visible') and trials_pass(r,'fresh_') for r in matrix)
 failure_safe=failed_import and failed_import['error'] and failed_import['metadata_preserved'] and failed_import['native_old_actions_preserved']
 classification='live_reload_verified' if all_existing and all_new and publication_safe and failure_safe else 'new_agent_only' if all_new and publication_safe and failure_safe else 'preload_only'
 agent=backend.agent(engine.actors['operator']['handle']);api={name:str(getattr(agent,name).__doc__) for name in dir(agent) if not name.startswith('_')}
 journal.write('native_segment_queue_discovery.json',{'native_segment_queue_verified':False,'methods':api,'reason':'Discovery only: no queue/playhead/next-segment receipts or 100-segment continuity acceptance.'})
 journal.write('reload_probe.json',{'classification':classification,'matrix':matrix,'failed_import':failed_import,'publication_safe':publication_safe,'all_existing_playback':all_existing,'all_new_playback':all_new,'limits':'No Stop/Play or live pose writes. Async apply/fencing and native queues remain independent gates.'})
 for tid,t in list(engine.tasks.items()):
  if t['status'] not in {'succeeded','failed','cancelled'}:
   call('cancel',{'request_id':'cleanup_'+tid,'task_id':tid});settle(tid,'cleanup',120)
 journal.write('completed.json',{'harness_completed':True,'classification':classification,'frames':recorder.frames,'duration_s':timeline.get_current_time()-origin});print('NATIVE_RELOAD_PROBE_DONE',classification,flush=True)
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
