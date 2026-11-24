"""Preloaded official-generated SOMA clips on real native Human actors."""
import argparse,hashlib,json,math,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--run-id',required=True)
p.add_argument('--workspace-root',default=str(ROOT))
p.add_argument('--source-root')
p.add_argument('--clip-dir',required=True)
p.add_argument('--gpu',type=int,default=3)
p.add_argument('--cases',nargs='+')
p.add_argument('--capture-idle',action='store_true')
p.add_argument('--model-rig')
p.add_argument('--diagnostic-root-mode',choices=['USE_ROOT_ANIMATION','APPLY_ROOT_ANIMATION_TO_HIPS'])
p.add_argument('--diagnostic-face-before-base',choices=['current','positive_y'])
p.add_argument('--diagnostic-current-facing-vector',action='store_true')
p.add_argument('--diagnostic-imported-y-up-cm',action='store_true')
p.add_argument('--diagnostic-face-vector-steps',type=int,choices=range(1,61))
p.add_argument('--diagnostic-face-vector-direction',choices=['current','positive_y'],default='current')
p.add_argument('--diagnostic-approach-distance',type=float,default=1.2)
p.add_argument('--diagnostic-idle-tags',choices=['default','basic','disabled'],default='default')
p.add_argument('--diagnostic-motion-playinfo',action='store_true')
p.add_argument('--diagnostic-idle-duration',type=float,default=2)
p.add_argument('--diagnostic-skip-approach',action='store_true')
p.add_argument('--diagnostic-response-profile',choices=['default','fixed30'],default='default')
p.add_argument('--diagnostic-seed',type=int)
args=p.parse_args()
ROOT=Path(args.workspace_root).resolve();source=Path(args.source_root or ROOT).resolve()
if not .5<=args.diagnostic_approach_distance<=4:p.error('diagnostic approach distance must be between .5 and 4 metres inside this probe NavMesh')
if not .5<=args.diagnostic_idle_duration<=60:p.error('diagnostic idle duration must be between .5 and 60 seconds')
if args.diagnostic_seed is not None and not 0<=args.diagnostic_seed<2**31:p.error('diagnostic seed must be a nonnegative 31-bit integer')
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir()
for name in ['src','configs','schemas']:shutil.copytree(source/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.egg-info'))
shutil.copytree(Path(args.clip_dir).resolve(),snap/'inputs');registry=json.loads((snap/'inputs/actions.json').read_text())
if args.model_rig:shutil.copy2(args.model_rig,snap/'inputs/model_rig.json')
for name,entry in registry['actions'].items():
 entry['clip']=str(snap/'inputs'/(name+'.usda'))
 if (snap/'inputs/soma_native.usda').is_file():entry['skeleton']=str(out/'prepared_rig.usda')
(snap/'configs/custom_actions.json').write_text(json.dumps(registry,indent=2)+'\n');(snap/'configs/custom_action_acceptance.json').write_text('{}\n')
(snap/'reports').mkdir();shutil.copy2(source/'reports/capability_matrix.json',snap/'reports/capability_matrix.json');shutil.copy2(__file__,snap/Path(__file__).name)
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n')
(out/'probe_config.json').write_text(json.dumps(vars(args),indent=2)+'\n');sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
engine=journal=recorder=stream=play_info_file=None;play_info_logger=None;play_info_messages=[];code=0;converters={};pose_histories={};contexts={}
try:
 import omni.kit.app,omni.usd,carb
 import carb.settings,carb.logging
 from pxr import Usd,UsdGeom,UsdSkel,Gf
 manager=omni.kit.app.get_app().get_extension_manager()
 for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:assert manager.set_extension_enabled_immediate(ext,True)
 settings=carb.settings.get_settings();idle_key='/exts/omni.anim.behavior.core/idleAnimationTags';original_idle_tags=settings.get(idle_key)
 response_keys=['/exts/omni.anim.behavior.core/'+n for n in ['agentResponseTime','agentResponseTimeMaxRandomOffset','navBlockedTimeout']];original_response={k:settings.get(k) for k in response_keys}
 if args.diagnostic_response_profile=='fixed30':
  for key,value in zip(response_keys,[1/30,0.,3.]):settings.set(key,value)
 if args.diagnostic_idle_tags!='default':settings.set(idle_key,['Idle'] if args.diagnostic_idle_tags=='basic' else ['']*len(original_idle_tags or range(7)))
 (out/'sdk_idle_settings.json').write_text(json.dumps({'mode':args.diagnostic_idle_tags,'original_tags':original_idle_tags,'active_tags':settings.get(idle_key),'response_profile':args.diagnostic_response_profile,'original_response':original_response,'active_response':{k:settings.get(k) for k in response_keys},'requested_api_seed':args.diagnostic_seed,'scope':'Probe process only, configured before agents/Play; product defaults unchanged. A fixed API seed does not prove deterministic native execution.'},indent=2)+'\n')
 if args.diagnostic_motion_playinfo:settings.set_bool('/exts/omni.anim.behavior.core/outputMotionMatchingPlayInfo',True)
 from simpeople.backends.native.scene import build_scene
 from simpeople.backends.native.reservations import ReservationNativeBackend
 from simpeople.backends.native.custom_actions import register
 from simpeople.backends.native.recording import Recorder
 from simpeople.core.engine import Engine
 from simpeople.core.journal import Journal
 from simpeople.tools.runtime_contract import capture_runtime_contract
 omni.usd.get_context().new_stage();sem=build_scene(False);stage=omni.usd.get_context().get_stage()
 backend=ReservationNativeBackend(ROOT,sem,True,config_dir=snap/'configs',capability_file=snap/'reports/capability_matrix.json');backend.enable_corridor_profile();backend.quality_sampling=True
 if args.diagnostic_seed is not None:backend.api.set_random_seed(args.diagnostic_seed)
 if args.diagnostic_root_mode or args.diagnostic_current_facing_vector:
  # Probe-only SDK policy comparison. The product adapter and accepted action
  # defaults remain unchanged. Only Behavior writes the actor and its skeleton.
  from omni.anim.behavior.core import BehaviorRootAnimation
  root_mode=getattr(BehaviorRootAnimation,args.diagnostic_root_mode) if args.diagnostic_root_mode else None;native_agent=backend.agent;root_receipts=[]
  class RootPolicyAgent:
   def __init__(self,agent):self._agent=agent
   def __getattr__(self,name):return getattr(self._agent,name)
   def custom_action(self,*a,**kw):
    direction=self._agent.get_facing_direction();facing=[float(v) for v in direction];idle_tid=None
    if args.diagnostic_current_facing_vector:
     # A same-controller native command, with no intervening world step.
     # This tests the SDK's desired-facing state, not a transform correction.
     idle_tid=self._agent.idle(facing=carb.Float3(*facing))
    if root_mode is not None:kw['root_animation']=root_mode
    tid=self._agent.custom_action(*a,**kw)
    root_receipts.append({'action':a[0] if a else kw.get('action'),'mode':args.diagnostic_root_mode or 'default','observed_facing_before':facing,'current_facing_vector_requested':args.diagnostic_current_facing_vector,'preparatory_idle_native_task_id':int(idle_tid) if idle_tid is not None else None,'native_task_id':int(tid)})
    (out/'root_policy_receipts.json').write_text(json.dumps(root_receipts,indent=2)+'\n');return tid
  backend.agent=lambda handle:RootPolicyAgent(native_agent(handle))
 # Prepare an explicit SOMA derivative before native SDK import. No live actor
 # pose writes; no edits to the official model/source rig.
 if (snap/'inputs/soma_native.usda').is_file():
  from simpeople.backends.native.motion_import import prepare_soma_rig
  (out/'prepared_rig_tags.json').write_text(json.dumps(prepare_soma_rig(snap/'inputs/soma_native.usda',out/'prepared_rig.usda'),indent=2))
 register(backend,out/'custom_actions')
 if args.diagnostic_imported_y_up_cm:
  # A metadata-only counterfactual, on fresh file URIs before any agents or
  # timeline Play. Preserve every pose, annotation and imported original.
  from pxr import Sdf
  def authored_values(clip):
   return [(str(prim.GetPath()),[(str(a.GetName()),str(a.GetTypeName()),a.Get(),[(t,a.Get(t)) for t in a.GetTimeSamples()]) for a in prim.GetAttributes()],[(str(r.GetName()),list(map(str,r.GetTargets()))) for r in prim.GetRelationships()]) for prim in clip.Traverse()]
  directory=out/'metadata_derivatives';directory.mkdir();receipts=[]
  for name,entry in backend.custom_actions.items():
   originals=list((out/'custom_actions/clips'/name).glob('*.usd'));assert len(originals)==1
   original=originals[0];source=Usd.Stage.Open(str(original));values=authored_values(source)
   destination=directory/(name+'.usd');assert source.GetRootLayer().Export(str(destination))
   derivative=Usd.Stage.Open(str(destination));before={'up_axis':str(UsdGeom.GetStageUpAxis(source)),'meters_per_unit':UsdGeom.GetStageMetersPerUnit(source)}
   UsdGeom.SetStageUpAxis(derivative,'Y');UsdGeom.SetStageMetersPerUnit(derivative,.01);derivative.GetRootLayer().Save()
   assert authored_values(derivative)==values
   references=[]
   for path in entry['prim_paths']:
    prim=stage.GetPrimAtPath(path);payloads=prim.GetMetadata('payload').GetAppliedItems();assert len(payloads)==1,(path,payloads)
    reference=payloads[0];references.append({'prim_path':str(path),'original_payload':reference.assetPath,'prim_path_in_asset':str(reference.primPath)})
    prim.GetPayloads().SetPayloads([Sdf.Payload(str(destination),reference.primPath,reference.layerOffset)])
   receipts.append({'name':name,'original':str(original),'original_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),'derivative':str(destination),'derivative_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'before':before,'after':{'up_axis':'Y','meters_per_unit':.01},'all_authored_values_identical':True,'references':references})
  journal_path=out/'metadata_derivatives.json';journal_path.write_text(json.dumps(receipts,indent=2)+'\n')
 journal=Journal(out,{'scenario':'generated_native_preload','gpu':args.gpu,'width':1920,'height':1080,'warmup_wall_s':30});engine=Engine(backend,journal)
 def call(method,params):return engine.call(method,{'controller_id':'generated-native-probe',**params})
 for aid,asset,position in [('operator','default',[-3,-5.8-args.diagnostic_approach_distance,0]),('second','female_adult_business_02',[3,-5.8-args.diagnostic_approach_distance,0]),('witness','default',[-7,-3,0])]:
  call('spawn',{'request_id':aid,'actor_id':aid,'asset_id':asset,'spawn_anchor':position})
 for _ in range(6):app.update()
 journal.write('actor_motion_libraries.json',{aid:{'instance':backend.instances[a['handle']],'actual_relationship':[str(p) for p in stage.GetPrimAtPath(a['handle']).GetRelationship('behavior:motionLibrary').GetTargets()]} for aid,a in engine.actors.items()})
 assert backend.nav.start_navmesh_baking_and_wait()
 timeline=backend.timeline;timeline.set_time_codes_per_second(30);timeline.set_end_time(100000);timeline.set_auto_update(False);timeline.set_play_every_frame(True);timeline.play()
 for _ in range(120):
  timeline.forward_one_frame();app.update()
  if all(backend.observe(a['handle']).get('ready') for a in engine.actors.values()):break
 assert all(backend.observe(a['handle']).get('ready') for a in engine.actors.values())
 spawn_checks={}
 for aid,actor in engine.actors.items():
  expected=backend.instances[actor['handle']]['spawn_position_m'];actual=backend.observe(actor['handle'])['position_m'];error=math.dist(expected[:2],actual[:2])
  spawn_checks[aid]={'requested_position_m':expected,'actual_native_position_m':actual,'horizontal_error_m':error,'passed':math.isfinite(error) and error<=.3}
 (out/'actual_spawn_checks.json').write_text(json.dumps(spawn_checks,indent=2)+'\n')
 assert all(c['passed'] for c in spawn_checks.values()),'native fixture root differs from requested spawn: '+json.dumps(spawn_checks)
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
 agent_contract=backend.agent(engine.actors['operator']['handle'])
 journal.write('native_custom_action_contract.json',{'custom_action':str(agent_contract.custom_action.__doc__),'task_methods':[n for n in dir(agent_contract) if 'task' in n.lower()]})
 if args.model_rig:
  from simpeople.backends.native.pose_bridge import NativePoseConverter,capture_actual_pose
  from simpeople.motion.pose_bridge import ExecutedPoseHistory,PoseBridge,identity as execution_identity
  model_rig=json.loads((snap/'inputs/model_rig.json').read_text())
  for aid in ['operator','second']:
   asset_id=backend.instances[engine.actors[aid]['handle']]['asset_id'];asset=next(a for a in backend.assets if a['asset_id']==asset_id)
   active=next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(stage.GetPrimAtPath(engine.actors[aid]['handle'])) if p.IsA(UsdSkel.Skeleton))
   converters[aid]=NativePoseConverter(backend,asset['source_uri'],snap/'inputs/soma_native.usda',model_rig,out/('pose_bridge_'+aid),active_skeleton=active);pose_histories[aid]=ExecutedPoseHistory()
 if registry.get('roundtrip_cases') or registry.get('generated_cases') or registry.get('canonical_cases'):
  cycles=1 if args.cases and len(args.cases)==1 else 4 if registry.get('canonical_cases') else 5
  witness=call('run_activity',{'request_id':'witness_patrol','actor_id':'witness','steps':[{'action':'move_to','target':[-7,y,0],'timeout_s':25} for y in [3,-3]*cycles]})['task_id']
 else:witness=call('move_to',{'request_id':'witness_walk','actor_id':'witness','target':[-7,3,0],'timeout_s':20})['task_id']
 phases=[];framing=[];comparisons=[];phase_origin=timeline.get_current_time();rt_targets={};latest_poses={};admissions=[]
 if args.diagnostic_motion_playinfo:
  def capture_play_info(_source,_level,_filename,_line_number,message):
   if message.startswith(('PLAYINFO','TagINFO:')):play_info_messages.append(message)
  play_info_logger=carb.logging.acquire_logging().add_logger(capture_play_info);play_info_file=(out/'native_play_info.jsonl').open('w')
 def frame(label):
  play_info_messages.clear()
  recorder.step(1/30);engine.tick(timeline.get_current_time());identity={'source_tick':journal.frames,'relative_sim_time':timeline.get_current_time()-origin};recorder.capture(timeline.get_current_time(),identity);journal.sample(engine,identity)
  for aid,names in joint_paths.items():
   handle=engine.actors[aid]['handle'];agent=backend.agent(handle);pose=[]
   for index in range(len(names)):
    point=carb.Float3(0,0,0);q=carb.Float4(0,0,0,1);assert agent.get_joint_world_transform(index,point,q)
    pose.append([*backend.to_public(point),q.x,q.y,q.z,q.w])
   obs=backend.observe(handle)
   latest_poses[aid]={'world_pose':pose,'actual_observation':obs}
   if label in {'mb_stand','mb_arm','cancel_generated','idle_context'} or label.startswith(('rt_','generated_','canonical_')):
    frustum=camera.GetCamera().frustum;projection=frustum.ComputeViewMatrix()*frustum.ComputeProjectionMatrix()
    points=[projection.Transform(Gf.Vec3d(*obs['position_m'])),projection.Transform(Gf.Vec3d(*obs['joints_m']['Head']))]
    framing.append({'actor_id':aid,'sim_time':timeline.get_current_time(),'visible':all(abs(p[0])<.95 and abs(p[1])<.95 for p in points),'ndc':[list(p) for p in points]})
   if label.startswith('rt_') and 1<=timeline.get_current_time()-phase_origin<=2.5 and obs['action']==rt_targets.get(aid):
    import numpy as np,math
    from simpeople.motion.rig import rotate,multiply
    source_key=registry['actions'][rt_targets[aid]]['actor_source'];reference=registry['roundtrip_sources'][source_key];assert list(map(str,names))==reference['joint_paths']
    def body_frame(values,facing):
     values=np.array(values);yaw=math.atan2(facing[0],-facing[1]);q=np.array([0,0,math.sin(-yaw/2),math.cos(-yaw/2)])
     points=rotate(q,values[:,:3]-values[0,:3]);rotations=multiply(q,values[:,3:]);return points,rotations
    wanted,wanted_q=body_frame(reference['world_pose'],reference['actual_observation']['facing_direction']);actual,actual_q=body_frame(pose,obs['facing_direction'])
    error=np.linalg.norm(wanted-actual,axis=-1);angles=np.degrees(2*np.arccos(np.clip(np.abs(np.sum(wanted_q*actual_q,axis=-1)),0,1)));worst=int(np.argmax(error))
    comparisons.append({'actor_id':aid,'phase':label,'source_key':source_key,'sim_time':timeline.get_current_time(),'max_joint_position_error_m':float(error.max()),'max_joint_angle_error_deg':float(angles.max()),'worst_joint':str(names[worst]),'per_joint_position_errors_m':error.tolist()})
   task=engine.tasks.get(engine.actors[aid].get('task_id'),{})
   fence={k:task[k] for k in ['session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id','status'] if k in task}
   if aid in converters and label=='idle_context' and task.get('status')=='running':
    actual=capture_actual_pose(backend,engine,aid,pose_histories[aid],journal.frames)
    if aid not in contexts and timeline.get_current_time()-phase_origin>=1.5:
     context=PoseBridge(model_rig,converters[aid]).to_model_context(pose_histories[aid],converters[aid].profile,execution_identity(task),timeline.get_current_time());contexts[aid]=context
     journal.write(aid+'_model_context.json',context);journal.write(aid+'_actual_context.json',pose_histories[aid].window(execution_identity(task),timeline.get_current_time()))
     journal.write(aid+'_pose_bridge_diagnostic.json',converters[aid].diagnose_roundtrip(context['conversion']))
   stream.write(json.dumps({'actor_id':aid,'actor_instance_id':engine.actors[aid]['actor_instance_id'],'phase':label,'source_tick':journal.frames,'sim_time':timeline.get_current_time(),'phase_time_s':timeline.get_current_time()-phase_origin,'joint_paths':names,'world_pose':pose,'actual_observation':obs,'activity_task_id':task.get('task_id'),'step_index':task.get('step_index'),'task':fence})+'\n')
  if play_info_file:play_info_file.write(json.dumps({'source_tick':journal.frames,'sim_time':timeline.get_current_time(),'phase':label,'messages':list(play_info_messages),'actual_actor_tasks':{aid:{'action':row['actual_observation']['action'],'native_task_id':row['actual_observation']['native_task_id']} for aid,row in latest_poses.items()},'scope':'SDK log messages lack actor IDs. Do not treat a nearest source pose or an unassigned log as a native playback cursor.'})+'\n')
 def admit_canonical(case):
  from simpeople.motion.entry import entry_error
  if args.diagnostic_face_vector_steps:
   receipt={'case':case,'world_steps':args.diagnostic_face_vector_steps,'direction_mode':args.diagnostic_face_vector_direction,'actors':{}}
   for aid in ['operator','second']:
    handle=engine.actors[aid]['handle'];agent=backend.agent(handle);direction=agent.get_facing_direction();facing=[float(v) for v in direction];wanted=facing if args.diagnostic_face_vector_direction=='current' else backend.to_stage([0,1,0])
    tid=agent.idle(facing=carb.Float3(*wanted));receipt['actors'][aid]={'before_facing_stage':facing,'requested_direction_stage':list(wanted),'native_idle_task_id':int(tid)}
   for _ in range(args.diagnostic_face_vector_steps):frame('canonical_vector_prelude_'+case)
   for aid in receipt['actors']:receipt['actors'][aid]['after_observation']=backend.observe(engine.actors[aid]['handle'])
   with (out/'facing_vector_preludes.jsonl').open('a') as f:f.write(json.dumps(receipt)+'\n')
  if args.diagnostic_face_before_base:
   import math
   receipt={'case':case,'mode':args.diagnostic_face_before_base,'actors':{}}
   face_tasks={}
   for aid in ['operator','second']:
    obs=backend.observe(engine.actors[aid]['handle']);direction=obs['facing_direction'] if args.diagnostic_face_before_base=='current' else [0,1,0]
    length=math.hypot(*direction[:2]);direction=[direction[0]/length,direction[1]/length,0]
    target='/World/CanonicalFacing/'+aid;prim=UsdGeom.Xform.Define(stage,target);ops=prim.GetOrderedXformOps();op=ops[0] if ops else prim.AddTranslateOp()
    op.Set(Gf.Vec3d(*backend.to_stage([obs['position_m'][i]+5*direction[i] for i in range(3)])))
    face_tasks[aid]=call('run_activity',{'request_id':'face_'+case+'_'+aid+'_'+str(len(admissions)),'actor_id':aid,'steps':[{'action':'look_at','target':target,'duration_s':2,'timeout_s':5}]})['task_id']
    receipt['actors'][aid]={'before_facing':obs['facing_direction'],'requested_direction':direction,'task_id':face_tasks[aid]}
   face_history={aid:[] for aid in face_tasks};facing_ready=False
   for _ in range(180):
    frame('canonical_facing_'+case)
    aligned=True
    for aid in face_tasks:
     f=backend.observe(engine.actors[aid]['handle'])['facing_direction'];wanted=receipt['actors'][aid]['requested_direction'];yaw=math.atan2(f[0],-f[1]);face_history[aid].append(yaw);window=face_history[aid][-4:]
     error=math.degrees(math.acos(max(-1,min(1,sum(a*b for a,b in zip(f[:2],wanted[:2]))))))
     stable=len(window)==4 and max(abs(math.degrees(math.atan2(math.sin(x-window[-1]),math.cos(x-window[-1])))) for x in window)<=.1
     aligned=aligned and error<=2 and stable
    if any(engine.tasks[t]['status'] in {'failed','cancelled'} for t in face_tasks.values()):break
    if all(engine.tasks[t]['status']=='succeeded' for t in face_tasks.values()) and aligned:facing_ready=True;break
   for aid,tid in face_tasks.items():
    obs=backend.observe(engine.actors[aid]['handle']);wanted=receipt['actors'][aid]['requested_direction'];actual=obs['facing_direction'];error=math.degrees(math.acos(max(-1,min(1,sum(a*b for a,b in zip(actual[:2],wanted[:2]))))))
    receipt['actors'][aid].update(after_facing=actual,error_deg=error,status=engine.tasks[tid]['status'],observed_samples=len(face_history[aid]))
   receipt['observed_facing_ready']=facing_ready
   with (out/'facing_preconditions.jsonl').open('a') as f:f.write(json.dumps(receipt)+'\n')
   assert facing_ready and all(r['status']=='succeeded' and r['error_deg']<=2 for r in receipt['actors'].values()),receipt
   # A normal native look_at task establishes this diagnostic precondition.
   # It does not write actor transforms/bones or alter product defaults.
  tids={aid:call('run_activity',{'request_id':'entry_wait_'+case+'_'+aid+'_'+str(len(admissions)),'actor_id':aid,'steps':[{'action':'custom_action','target':registry['canonical_bases'][aid],'duration_s':12,'timeout_s':14}] if registry.get('canonical_bases') else [{'action':'wait','duration_s':12,'timeout_s':14}]})['task_id'] for aid in ['operator','second']}
  streak=0;checks={};began=timeline.get_current_time()
  for _ in range(240):
   frame('canonical_admission_'+case)
   checks={aid:entry_error(latest_poses[aid]['world_pose'],latest_poses[aid]['actual_observation']['facing_direction'],registry['actions']['canonical_'+aid+'__'+case]['canonical_entry']) for aid in tids}
   ready=all(c['passed'] and latest_poses[aid]['actual_observation']['speed_mps']<.15 for aid,c in checks.items());streak=streak+1 if ready else 0
   if streak>=4:break
  row={'case':case,'passed':streak>=4,'consecutive_actual_samples':streak,'wait_sim_s':timeline.get_current_time()-began,'entry_errors':checks,'precondition_task_ids':tids};admissions.append(row);journal.write('canonical_admissions.json',admissions)
  if not row['passed']:raise RuntimeError('canonical entry was not reached through native Idle: '+json.dumps(row))
 def run(label,make_steps,cancel=False,cancel_after=.4):
  global phase_origin,rt_targets
  if registry.get('canonical_cases'):
   case=label.removeprefix('canonical_') if label.startswith('canonical_') else (args.cases or registry['canonical_cases'])[0] if label=='cancel_generated' else None
   if case:admit_canonical(case)
  steps={aid:make_steps(aid) for aid in ['operator','second']}
  if label.startswith('rt_'):rt_targets={aid:s[0]['target'] for aid,s in steps.items()}
  tids={aid:call('run_activity',{'request_id':label+'_'+aid,'actor_id':aid,'steps':steps[aid]})['task_id'] for aid in ['operator','second']};began=timeline.get_current_time();requested=False
  phase_origin=began
  for _ in range(max(900,math.ceil((args.diagnostic_idle_duration+9)*30)) if label=='idle_context' else 900):
   if cancel and not requested and timeline.get_current_time()-began>=cancel_after:
    for aid,tid in tids.items():call('cancel',{'request_id':'cancel_'+aid,'task_id':tid})
    requested=True
   frame(label)
   if all(engine.tasks[tid]['status'] in {'succeeded','failed','cancelled'} for tid in tids.values()):break
  phases.append({'name':label,'tasks':[engine.public(engine.tasks[t]) for t in tids.values()]})
 if not args.diagnostic_skip_approach:run('walk_in',lambda aid:[{'action':'move_to','target':[-3 if aid=='operator' else 3,-5.8,0],'timeout_s':15}])
 if args.capture_idle:
  run('idle_context',lambda aid:[{'action':'wait','duration_s':args.diagnostic_idle_duration,'timeout_s':args.diagnostic_idle_duration+8}])
  if args.model_rig:
   from simpeople.core.errors import SimPeopleError
   guards=[]
   def rejected_history(aid):
    task=engine.tasks[engine.actors[aid]['task_id']]
    assert capture_actual_pose(backend,engine,aid,pose_histories[aid],journal.frames) is None
    try:pose_histories[aid].window(execution_identity(task),timeline.get_current_time())
    except SimPeopleError:return True
    raise AssertionError('ineligible actual task retained a usable context')
   for aid in converters:guards.append({'actor_id':aid,'case':'task_already_ended','passed':rejected_history(aid)})
   tids={aid:call('run_activity',{'request_id':'context_cancel_'+aid,'actor_id':aid,'steps':[{'action':'wait','duration_s':10,'timeout_s':12}]})['task_id'] for aid in converters}
   for _ in range(12):frame('idle_context')
   for aid,tid in tids.items():
    pose_histories[aid].window(execution_identity(engine.tasks[tid]),timeline.get_current_time())
    call('cancel',{'request_id':'cancel_context_'+aid,'task_id':tid})
    guards.append({'actor_id':aid,'case':'cancel_before_next_world_step','passed':rejected_history(aid)})
   for _ in range(150):
    frame('context_cancel_settlement')
    if all(engine.tasks[tid]['status']=='cancelled' for tid in tids.values()):break
   assert all(engine.tasks[tid]['status']=='cancelled' for tid in tids.values())
   phases.append({'name':'cancel_pose_context','tasks':[engine.public(engine.tasks[tid]) for tid in tids.values()]});journal.write('capture_guard_checks.json',guards)
 elif registry.get('canonical_cases'):
  selected=args.cases or registry['canonical_cases'];assert set(selected)<=set(registry['canonical_cases'])
  for case in selected:
   run('canonical_'+case,lambda aid,case=case:[{'action':'custom_action','target':f'canonical_{aid}__{case}','duration_s':registry['actions'][f'canonical_{aid}__{case}'].get('native_loop_duration_s',2.5 if registry['actions'][f'canonical_{aid}__{case}']['playback_mode']=='out_and_back' else 1),'timeout_s':20}])
  first=selected[0]
  run('cancel_generated',lambda aid:[{'action':'custom_action','target':f'canonical_{aid}__{first}','duration_s':4,'timeout_s':20}],True,cancel_after=registry['canonical_sequences']['operator__'+first]['prefix_frames']/30+.4)
 elif registry.get('generated_cases'):
  selected=args.cases or registry['generated_cases']
  assert set(selected)<=set(registry['generated_cases'])
  for case in selected:
   run('generated_'+case,lambda aid,case=case:[
    {'action':'custom_action','target':f'gen_{aid}__{case}_entry','duration_s':2,'timeout_s':15},
    {'action':'custom_action','target':f'gen_{aid}__{case}_motion','duration_s':registry['generated_sequences'][aid+'__'+case]['motion_seconds']+.2,'timeout_s':15},
    {'action':'custom_action','target':f'gen_{aid}__{case}_target','duration_s':3,'timeout_s':15}])
  first=registry['generated_cases'][0]
  run('cancel_generated',lambda aid:[{'action':'custom_action','target':f'gen_{aid}__{first}_motion','duration_s':4,'timeout_s':15}],True)
 elif registry.get('roundtrip_sources'):
  for case in registry.get('roundtrip_cases',[None]):
   for variant in ['full','reference']:
    run('rt_'+(case+'_' if case else '')+variant,lambda aid,variant=variant,case=case:[{'action':'custom_action','target':f'rt_{aid}'+('__'+case if case else '')+'_'+variant,'duration_s':3,'timeout_s':10}])
  run('cancel_generated',lambda aid:[{'action':'custom_action','target':f'rt_{aid}'+('__'+registry['roundtrip_cases'][0] if registry.get('roundtrip_cases') else '')+'_full','duration_s':4,'timeout_s':10}],True)
 else:
  for clip in ['mb_stand','mb_arm']:run(clip,lambda aid,clip=clip:[{'action':'custom_action','target':clip,'duration_s':1,'timeout_s':10}])
  run('cancel_generated',lambda aid:[{'action':'custom_action','target':'mb_arm','duration_s':4,'timeout_s':10}],True)
 run('walk_resume',lambda aid:[{'action':'move_to','target':[-5 if aid=='operator' else 5,-5.8,0],'timeout_s':15}])
 for _ in range(900):
  if engine.tasks[witness]['status'] in {'succeeded','failed','cancelled'}:break
  frame('witness_finish')
 stream.close();stream=None
 expected=all(t['status']==('cancelled' if ph['name'] in {'cancel_generated','cancel_pose_context'} else 'succeeded') for ph in phases for t in ph['tasks'])
 passed=expected and engine.tasks[witness]['status']=='succeeded' and bool(framing) and all(f['visible'] for f in framing)
 if args.model_rig:passed=passed and set(contexts)=={'operator','second'}
 journal.write('framing_checks.json',framing)
 if registry.get('roundtrip_sources'):
  roundtrip={}
  for aid in ['operator','second']:
   for phase in [p['name'] for p in phases if p['name'].startswith('rt_')]:
    rows=[c for c in comparisons if c['actor_id']==aid and c['phase']==phase];position=max((r['max_joint_position_error_m'] for r in rows),default=None);angle=max((r['max_joint_angle_error_deg'] for r in rows),default=None)
    roundtrip[aid+'_'+phase]={'passed':bool(rows) and position<=.03 and angle<=5,'samples':len(rows),'max_joint_position_error_m':position,'max_joint_angle_error_deg':angle,'worst':max(rows,key=lambda r:r['max_joint_position_error_m']) if rows else None}
  journal.write('actual_roundtrip.json',{'native_lifecycle_passed':passed,'variants':roundtrip,'samples':comparisons,'scope':'Actual native readback compared in actor-heading/root frame; reference decoder is lossy, no online or model inference claim.'})
  passed=passed and all(r['passed'] for r in roundtrip.values())
 journal.write('generated_native_acceptance.json',{'passed':passed,'preloaded_only':True,'allow_unverified_probe':True,'phases':phases,'witness_task':engine.public(engine.tasks[witness]),'registered_clips':backend.custom_actions,'joint_layouts':joint_paths,'limits':'First retarget/preload exploration. Task terminals alone do not certify retarget quality or arbitrary native-to-SOMA pose bridging.'})
 journal.write('asset_manifest.json',backend.assets);journal.write('measurement_end_state.json',engine.cmd_get_state({}));journal.write('completed.json',{'harness_completed':True,'functional_expected_matched':passed,'frames':recorder.frames,'duration_s':timeline.get_current_time()-origin})
 print('GENERATED_NATIVE_PRELOAD_DONE',passed,flush=True)
 code=0 if passed else 2
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if play_info_logger is not None:carb.logging.acquire_logging().remove_logger(play_info_logger)
 if play_info_file:play_info_file.close()
 if stream:stream.close()
 if recorder:recorder.close()
 for converter in converters.values():converter.close()
 if engine:
  for aid in list(engine.actors):engine.abort_actor(aid,'process_shutdown')
  engine.backend.close();journal.finish(engine,exit_code=code)
 app.close(exit_code=code)
raise SystemExit(code)
