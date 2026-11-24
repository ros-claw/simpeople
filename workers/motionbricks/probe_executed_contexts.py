"""Official inference from actual native IK histories to an observed neutral pose."""
import argparse,hashlib,json,math,shutil,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--contexts-run',required=True);p.add_argument('--canonical-run',required=True);p.add_argument('--upstream',required=True);p.add_argument('--output',required=True);p.add_argument('--device',default='cuda:3');args=p.parse_args()
out=Path(args.output).resolve();out.mkdir(exist_ok=False,parents=True);snap=out/'source_snapshot';snap.mkdir()
for name in ['src','workers','schemas']:shutil.copytree(ROOT/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
source=ROOT/'runs'/args.contexts_run;canonical=ROOT/'runs'/args.canonical_run
shutil.copytree(source,snap/'contexts',ignore=shutil.ignore_patterns('source_snapshot','*.log','*_sdk_raw*.npy'))
shutil.copy2(source/'source_snapshot/executed_samples.json',snap/'contexts/executed_samples.json');shutil.copy2(source/'source_snapshot/rig.json',out/'rig.json');shutil.copy2(source/'source_snapshot/soma_native.usda',out/'soma_native.usda')
(snap/'canonical').mkdir();shutil.copy2(canonical/'source_snapshot/executed_samples.json',snap/'canonical/executed_samples.json')
for file in canonical.glob('*_roundtrip.npz'):shutil.copy2(file,snap/'canonical'/file.name)
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n')
sys.path.insert(0,str(snap/'src'));sys.path.insert(0,str(snap/'workers/motionbricks'))
import numpy as np
from worker import ArtifactBackend
from simpeople.motion.contracts import validate_spec,digest
from simpeople.motion.rig import convert_root,forward_kinematics
from simpeople.motion.validation import validate_artifact
rig=json.loads((out/'rig.json').read_text());histories=json.loads((snap/'contexts/executed_samples.json').read_text());neutral=json.loads((snap/'canonical/executed_samples.json').read_text())
args.rig=str(out/'rig.json');args.cache_dir=str(Path(args.upstream).resolve()/'.trt-cache');args.fault_before_publish_s=0
backend=ArtifactBackend(args);results=[]
try:
 for key,rows in histories.items():
  actor=rows[-1]['actor_id'];case=out/key;case.mkdir();source_path=snap/'contexts'/(key+'_roundtrip.npz')
  with np.load(source_path,allow_pickle=False) as data:context=data['soma_local']
  with np.load(snap/'canonical'/(actor+'_roundtrip.npz'),allow_pickle=False) as data:target=data['soma_local'][-1:].copy()
  def heading(row):
   f=row['actual_observation']['facing_direction'];return math.atan2(f[0],-f[1])
  target[:,0,:3]-=np.array(neutral[actor][-1]['world_pose'][0][:3]);angle=heading(rows[-1])-heading(neutral[actor][-1]);target=convert_root(target,[0,0,math.sin(angle/2),math.cos(angle/2)]);target[:,0,:3]+=np.array(rows[-1]['world_pose'][0][:3])
  ctx={'source':'executed_history','sample_times_s':[r['sim_time'] for r in rows],'local_poses':context.tolist()};task=rows[-1]['task']
  binding={k:task[k] for k in ['session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id']};binding['context_revision']=digest(ctx)
  spec={'schema_version':'simpeople.motion-spec.v1','request_id':'ctx_'+key,'rig_sha256':rig['rig_sha256'],'context':ctx,'target':{'local_poses':target.tolist()},'binding':binding};validate_spec(spec,rig)
  (case/'spec.json').write_text(json.dumps(spec,indent=2)+'\n');np.savez(case/'context.npz',local_poses=context);np.savez(case/'target.npz',local_poses=target)
  artifact=backend.generate(spec,case/'generated');quality=validate_artifact(artifact,rig,case)
  with np.load(artifact['corrected']['path'],allow_pickle=False) as archive:poses=archive['local_poses']
  world=forward_kinematics(poses,rig['parents']);start=forward_kinematics(context[-1:],rig['parents'])[0];end=forward_kinematics(target[:1],rig['parents'])[0]
  start_error=float(np.linalg.norm(world[0,:,:3]-start[:,:3],axis=-1).max());end_error=float(np.linalg.norm(world[-1,:,:3]-end[:,:3],axis=-1).max());passed=start_error<=.005 and end_error<=.005
  row={'case_id':key,'actor_id':actor,'frames':len(poses),'passed':passed,'start_world_joint_error_m':start_error,'end_world_joint_error_m':end_error,'artifact_validation':quality,'artifact_sha256':hashlib.sha256((case/'generated/artifact.json').read_bytes()).hexdigest()};results.append(row)
  (case/'result.json').write_text(json.dumps(row,indent=2)+'\n');print('ACTUAL_CONTEXT_GENERATED',key,passed,len(poses),flush=True)
 (out/'actual_context_generation.json').write_text(json.dumps({'passed':bool(results) and all(r['passed'] for r in results),'cases':results,'scope':'Offline asset production from previously executed native IK observations; source execution fences do not authorize applying a late result to another live task.'},indent=2)+'\n')
finally:backend.close()
raise SystemExit(0 if results and all(r['passed'] for r in results) else 2)
