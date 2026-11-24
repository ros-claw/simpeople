"""Offline native-space upper-body goals from recorded actual poses."""
import argparse, hashlib, json, shutil, sys, threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--native-run',required=True);p.add_argument('--targets-run',required=True);p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);args=p.parse_args()
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir();shutil.copytree(ROOT/'src',snap/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,snap/Path(__file__).name)
native=ROOT/'runs'/args.native_run;targets=ROOT/'runs'/args.targets_run;(snap/'native').mkdir()
for actor in ['operator','second']:
 for name in ['actual_context','model_context']:shutil.copy2(native/(actor+'_'+name+'.json'),snap/'native')
 active=native/('pose_bridge_'+actor)/'active_skeleton.json'
 if active.is_file():shutil.copy2(active,snap/'native'/(actor+'_active_skeleton.json'))
for name in ['model_rig.json','soma_native.usda']:shutil.copy2(native/'source_snapshot/inputs'/name,snap/name)
shutil.copy2(native/'asset_manifest.json',snap/'asset_manifest.json');shutil.copy2(targets/'source_snapshot/executed_samples.json',snap/'measured_ik.json')
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n');sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'disable_viewport_updates':True,'limit_cpu_threads':8});code=0;converters={}
try:
 import numpy as np,omni.usd,omni.kit.app
 from pxr import UsdGeom
 from types import SimpleNamespace
 from simpeople.backends.native.pose_bridge import NativePoseConverter
 from simpeople.motion.pose_bridge import ExecutedPoseHistory,PoseBridge,identity
 from simpeople.motion.goals import standing_upper_body_goal
 from simpeople.motion.rig import forward_kinematics
 from simpeople.motion.contracts import digest
 manager=omni.kit.app.get_app().get_extension_manager();assert manager.set_extension_enabled_immediate('omni.anim.behavior.core',True)
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z');main_thread=threading.get_ident()
 def assert_thread():assert threading.get_ident()==main_thread
 runtime={e['id'].split('-')[0]:e['id'] for e in manager.get_extensions() if e.get('enabled') and any(n in e['id'] for n in ['omni.anim.behavior.core','omni.anim.retarget.core'])};facade=SimpleNamespace(stage=stage,namespace='/World/StandingGoals',assert_thread=assert_thread,runtime_revision=runtime)
 rig=json.loads((snap/'model_rig.json').read_text());assets=json.loads((snap/'asset_manifest.json').read_text());measured=json.loads((snap/'measured_ik.json').read_text());results=[]
 for actor,asset_id in [('operator','default'),('second','female_adult_business_02')]:
  source=json.loads((snap/'native'/(actor+'_actual_context.json')).read_text());asset=next(a for a in assets if a['asset_id']==asset_id);active_path=snap/'native'/(actor+'_active_skeleton.json');active=json.loads(active_path.read_text()) if active_path.is_file() else None;converter=NativePoseConverter(facade,asset['source_uri'],snap/'soma_native.usda',rig,out/(actor+'_calibration'),active_descriptor=active);converters[actor]=converter
  history=ExecutedPoseHistory()
  for row in source:history.record(row)
  context=PoseBridge(rig,converter).to_model_context(history,converter.profile,identity(source[-1]['task']),source[-1]['sim_time']);prior=json.loads((snap/'native'/(actor+'_model_context.json')).read_text());assert context['context']==prior['context']
  (out/(actor+'_model_context.json')).write_text(json.dumps(context,indent=2)+'\n');idle=np.array(source[-1]['world_pose'])[None];idle_soma=np.array(context['context']['local_poses'])[-1:];idle_world=forward_kinematics(idle_soma,rig['parents'])
  for goal,chain in [('idle_cycle','idle'),('left_low','left_arm'),('look_left','head')]:
   target=source[-1] if chain=='idle' else measured[actor+'__'+goal][-1];assert target['joint_paths']==source[-1]['joint_paths']
   native_goal,construction=standing_upper_body_goal(idle,np.array(target['world_pose'])[None],converter.parents,converter.tags,chain)
   soma_goal,conversion=converter.convert_authored_goal(native_goal);world=forward_kinematics(soma_goal,rig['parents']);feet=[rig['joint_names'].index(n) for n in ['LeftFoot','RightFoot']];change=float(np.linalg.norm(world[:,feet,:3]-idle_world[:,feet,:3],axis=-1).max());passed=change<=.005
   reference={'sample_source':'authored_goal','world_pose':native_goal[0].tolist(),'joint_paths':source[-1]['joint_paths'],'actual_observation':{'facing_direction':source[-1]['actual_observation']['facing_direction']},'provenance':{'actual_idle_sha256':digest(source[-1]),'measured_ik_sha256':digest(target),'construction':construction}}
   result={'case_id':actor+'__'+goal,'actor_id':actor,'goal':goal,'passed':passed,'soma_support_position_change_m':change,'soma_goal':soma_goal.tolist(),'native_goal_reference':reference,'construction':construction,'conversion':conversion,'source_context_sha256':digest(context['context'])};results.append(result);print('STANDING_GOAL',result['case_id'],passed,change,flush=True)
 (out/'standing_goals.json').write_text(json.dumps({'passed':all(r['passed'] for r in results),'cases':results,'scope':'Offline authored upper-body targets preserving the currently observed native support. Targets have not executed; do not treat them as observed history.'},indent=2)+'\n')
 code=0 if all(r['passed'] for r in results) else 2
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 for converter in converters.values():converter.close()
 app.close(exit_code=code)
raise SystemExit(code)
