"""Locate a first-use seat revision change, retaining the actual USD fields.

Run after other GPU measurements close. All scene access stays on Kit's thread.
"""
import argparse,hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);p.add_argument('--expect',choices=['stable','stale'],default='stale');args=p.parse_args()
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir()
for name in ['src','configs','schemas']:shutil.copytree(ROOT/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(snap/'reports').mkdir();shutil.copy2(ROOT/'reports/capability_matrix.json',snap/'reports/capability_matrix.json');shutil.copy2(__file__,snap/Path(__file__).name)
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n')
(out/'probe_config.json').write_text(json.dumps(vars(args),indent=2)+'\n');sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'disable_viewport_updates':True,'limit_cpu_threads':8});engine=journal=recorder=None;code=0
try:
 import omni.kit.app,omni.usd
 from pxr import Usd,UsdGeom,Gf
 manager=omni.kit.app.get_app().get_extension_manager()
 for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:assert manager.set_extension_enabled_immediate(ext,True)
 from simpeople.backends.native.environments import industrial_scene
 from simpeople.backends.native.reservations import ReservationNativeBackend
 from simpeople.backends.native.recording import Recorder
 from simpeople.core.engine import Engine
 from simpeople.core.errors import SimPeopleError
 from simpeople.core.journal import Journal
 from simpeople.tools.runtime_contract import capture_runtime_contract
 omni.usd.get_context().new_stage();sem=industrial_scene();stage=omni.usd.get_context().get_stage()
 backend=ReservationNativeBackend(ROOT,sem,False,config_dir=snap/'configs',capability_file=snap/'reports/capability_matrix.json');backend.enable_corridor_profile()
 journal=Journal(out,{'scenario':'seat_revision_stability','gpu':args.gpu,'width':1920,'height':1080,'warmup_wall_s':0});engine=Engine(backend,journal)
 def call(method,params=None):return engine.call(method,{'controller_id':'seat-revision-probe',**(params or {})})
 call('spawn',{'request_id':'a','actor_id':'a','spawn_anchor':[7.5,-11,0]});call('spawn',{'request_id':'witness','actor_id':'witness','spawn_anchor':[-17,-6,0]})
 for _ in range(6):app.update()
 assert backend.nav.start_navmesh_baking_and_wait()
 timeline=backend.timeline;timeline.set_time_codes_per_second(30);timeline.set_end_time(100000);timeline.set_auto_update(False);timeline.set_play_every_frame(True);timeline.play()
 for _ in range(120):
  timeline.forward_one_frame();app.update()
  if all(backend.observe(a['handle']).get('ready') for a in engine.actors.values()):break
 assert all(backend.observe(a['handle']).get('ready') for a in engine.actors.values())
 capture_runtime_contract(ROOT,out,backend=backend,engine=engine,extensions=[e for e in manager.get_extensions() if e.get('enabled') and 'omni.anim.' in e['id']])
 recorder=Recorder(out,(1920,1080),gpu_index=args.gpu);backend.recorder=recorder
 for _ in range(5):recorder.step(0)
 recorder.control({'mode':'start'});origin=timeline.get_current_time();engine.tick(origin)
 def target():return call('list_interactions',{'target':'seat_00'})['interactions'][0]
 def raw_fields():
  time=Usd.TimeCode(timeline.get_current_time()*stage.GetTimeCodesPerSecond());result={}
  for prim in Usd.PrimRange(stage.GetPrimAtPath(sem['seat_00']['prim_path'])):
   attrs={str(a.GetName()):str(a.Get(time)) for a in prim.GetAttributes() if str(a.GetName()).startswith('xformOp') or str(a.GetName()) in {'points','faceVertexCounts','faceVertexIndices','extent'}}
   if attrs:result[str(prim.GetPath())]=attrs
  return result
 first=target();first_raw=raw_fields();journal.write('before_target.json',first);journal.write('before_raw_fields.json',first_raw);revision=first['geometry_revision']
 steps=[{'action':'move_to','target':'seat_00_approach','timeout_s':20},{'action':'sit','target':'seat_00','duration_s':1,'timeout_s':20,'interaction_revision':revision},{'action':'leave_seat','timeout_s':15},{'action':'move_to','target':[10,-11,0],'timeout_s':15}]
 call('validate_activity',{'actor_id':'a','steps':steps});tid=call('run_activity',{'request_id':'seat','actor_id':'a','steps':steps})['task_id'];witness=call('move_to',{'request_id':'witness_walk','actor_id':'witness','target':[-17,2,0],'timeout_s':20})['task_id'];changes=[];revisions=[]
 for _ in range(1800):
  recorder.step(1/30);engine.tick(timeline.get_current_time());identity={'source_tick':journal.frames,'relative_sim_s':timeline.get_current_time()-origin};recorder.capture(timeline.get_current_time(),identity);journal.sample(engine,identity)
  current=target();revisions.append({'sim_time':timeline.get_current_time(),'revision':current['geometry_revision']})
  if current['geometry_revision']!=revision and not changes:
   raw=raw_fields();journal.write('changed_target.json',current);journal.write('changed_raw_fields.json',raw)
   for path in sorted(set(first_raw)|set(raw)):
    for key in sorted(set(first_raw.get(path,{}))|set(raw.get(path,{}))):
     before=first_raw.get(path,{}).get(key);after=raw.get(path,{}).get(key)
     if before!=after:changes.append({'prim_path':path,'attribute':key,'before':before,'after':after})
   journal.write('changed_usd_fields.json',changes)
  if all(engine.tasks[t]['status'] in {'succeeded','failed','cancelled'} for t in [tid,witness]):break
 actor_task=engine.public(engine.tasks[tid]);witness_task=engine.public(engine.tasks[witness]);stable=all(r['revision']==revision for r in revisions)
 # A real edit of this probe's own empty seat must still invalidate a plan.
 baseline=(engine.actors['a']['task_id'],engine.actors['a']['control_epoch'],len(engine.tasks));seat=UsdGeom.Xformable(stage.GetPrimAtPath(sem['seat_00']['prim_path']));op=seat.GetOrderedXformOps()[0];now=Usd.TimeCode(timeline.get_current_time()*stage.GetTimeCodesPerSecond())
 journal.write('edit_layer_diagnostic.json',{'edit_target':stage.GetEditTarget().GetLayer().identifier,'property_stack':[{'layer':s.layer.identifier,'path':str(s.path),'default':str(s.default)} for s in op.GetAttr().GetPropertyStack(now)]})
 # Behavior's stronger session opinion can shadow an edit of the root layer.
 # Edit this diagnostic seat in the strongest local layer and verify it moved.
 before_position=list(current['position_m']);value=op.Get(now)
 with Usd.EditContext(stage,stage.GetSessionLayer()):assert op.Set(value+Gf.Vec3d(.2,0,0),now)
 edited=target();assert edited['position_m'][0]-before_position[0]>.199
 assert edited['geometry_revision']!=revisions[-1]['revision']
 edit_rejected=False
 try:call('run_activity',{'request_id':'old_after_edit','actor_id':'a','steps':[{'action':'sit','target':'seat_00','duration_s':1,'interaction_revision':revisions[-1]['revision']}]})
 except SimPeopleError as e:edit_rejected=e.code=='TARGET_STALE'
 assert baseline==(engine.actors['a']['task_id'],engine.actors['a']['control_epoch'],len(engine.tasks))
 observed=actor_task['status']=='failed' and actor_task.get('error',{}).get('code')=='TARGET_STALE' and bool(changes)
 expected=observed if args.expect=='stale' else stable and actor_task['status']=='succeeded'
 result={'expected':args.expect,'expected_result_matched':expected and witness_task['status']=='succeeded' and edit_rejected,'stale_reproduced':observed,'revision_stable_during_native_use':stable,'actual_task':actor_task,'witness_task':witness_task,'changed_usd_fields':changes,'real_edit_changed_revision':edited['geometry_revision']!=revisions[-1]['revision'],'real_edit_rejected_old_binding':edit_rejected,'frames':recorder.frames,'duration_s':timeline.get_current_time()-origin,'scope':'First-use native chair interaction, raw USD field diagnosis and actual task/continuous RGB; stale reproduction is failure evidence, not functional acceptance.'}
 journal.write('seat_revision_probe.json',result);journal.write('revision_history.json',revisions);journal.write('completed.json',{'harness_completed':True,'expected_result_matched':result['expected_result_matched']});print('SEAT_REVISION_PROBE',result['expected_result_matched'],changes,flush=True);code=0 if result['expected_result_matched'] else 2
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if recorder:recorder.close()
 if engine:
  for aid in list(engine.actors):engine.abort_actor(aid,'process_shutdown')
  engine.backend.close()
 if journal and engine:journal.finish(engine,process_exit_code=code)
 app.close(exit_code=code)
raise SystemExit(code)
