"""V2: actual world holds and all-frame continuity, without a source playhead.

Creates a separate result. Never changes prior task-clock audit results.
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--output',required=True);p.add_argument('--workspace-root',default=str(ROOT));p.add_argument('--source-root');args=p.parse_args()
ROOT=Path(args.workspace_root).resolve();source_root=Path(args.source_root or ROOT).resolve()
run=ROOT/'runs'/args.run_id;out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False);snap=out/'source_snapshot';snap.mkdir()
shutil.copytree(source_root/'src',snap/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.egg-info'));shutil.copy2(__file__,snap/Path(__file__).name);sys.path.insert(0,str(snap/'src'))
import numpy as np
from pxr import Usd,UsdGeom,UsdSkel,Gf
from simpeople.backends.native.foot_geometry import FootGeometry
from simpeople.motion.executed_quality import angles,bounded_world_steps,continuous_world_goal,world_goal
from simpeople.motion.quality import support_quality

sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
registry=json.load(open(run/'source_snapshot/inputs/actions.json'));lifecycle=json.load(open(run/'generated_native_acceptance.json'));assets={a['asset_id']:a for a in json.load(open(run/'asset_manifest.json'))};rows={'operator':[],'second':[]}
events=list(map(json.loads,(run/'events.jsonl').open()))
for r in map(json.loads,(run/'native_pose_history.jsonl').open()):
 if r['actor_id'] in rows:rows[r['actor_id']].append(r)
selected=[p['name'].removeprefix('canonical_') for p in lifecycle['phases'] if p['name'].startswith('canonical_')];results=[];asset_checks=[]
for actor,asset_id in [('operator','default'),('second','female_adult_business_02')]:
 source=Path(assets[asset_id]['source_uri']);assert sha(source)==assets[asset_id]['content_hash'];original=Usd.Stage.Open(str(source));stage=Usd.Stage.CreateInMemory();UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z');model=UsdGeom.Xform.Define(stage,'/World/Model');model.GetPrim().GetReferences().AddReference(str(source));matrix=Gf.Matrix4d().SetScale(UsdGeom.GetStageMetersPerUnit(original))
 if UsdGeom.GetStageUpAxis(original)=='Y':matrix*=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1,0,0),90))
 UsdGeom.Xformable(model).MakeMatrixXform().Set(matrix);root=next(UsdSkel.Root(x) for x in Usd.PrimRange(model.GetPrim()) if x.IsA(UsdSkel.Root));sk=next(UsdSkel.Skeleton(x) for x in Usd.PrimRange(root.GetPrim()) if x.IsA(UsdSkel.Skeleton));names=list(map(str,sk.GetJointsAttr().Get()));assert all(r['joint_paths']==names for r in rows[actor]);leaves=[n.rsplit('/',1)[-1] for n in names];feet={side:leaves.index(short) for side,short in [('left','L_Ankle' if 'L_Ankle' in leaves else 'L_Foot'),('right','R_Ankle' if 'R_Ankle' in leaves else 'R_Foot')]};geometry=FootGeometry(stage,str(root.GetPath()),feet);asset_checks.append({'actor_id':actor,'asset_sha256':sha(source),'patches':geometry.describe()})
 def seam(first,second):
  assert second['actor_instance_id']==first['actor_instance_id'] and second['source_tick']==first['source_tick']+1 and abs(second['sim_time']-first['sim_time']-1/30)<1e-7
  a=np.array(first['world_pose']);b=np.array(second['world_pose']);position=float(np.linalg.norm(b[:,:3]-a[:,:3],axis=-1).max());angle=float(angles(a[:,3:],b[:,3:]).max());return {'from_source_tick':first['source_tick'],'to_source_tick':second['source_tick'],'max_all_joint_position_step_m':position,'max_all_joint_angle_step_deg':angle,'passed':position<=.02 and angle<=2}
 for goal in selected:
  key=actor+'__'+goal;clip='canonical_'+key;entry=registry['actions'][clip];positions=[i for i,r in enumerate(rows[actor]) if r['phase']=='canonical_'+goal];samples=[rows[actor][i] for i in positions];active_positions=[i for i in positions if rows[actor][i]['actual_observation']['action']==clip];assert active_positions and all(b==a+1 for a,b in zip(active_positions,active_positions[1:]));first,last=active_positions[0],active_positions[-1];assert first>0 and last+1<len(rows[actor]);active=[rows[actor][i] for i in active_positions]
  task=next(t for p in lifecycle['phases'] if p['name']=='canonical_'+goal for t in p['tasks'] if t['actor_id']==actor)
  assert all(r['task']['task_id']==task['task_id'] and r['actor_instance_id']==task['actor_instance_id'] and r['task']['session_id']==task['session_id'] and r['task']['episode_id']==task['episode_id'] and r['task']['control_epoch']==task['control_epoch'] for r in active)
  assert any(e['kind']=='native_task_bound' and e.get('actor_id')==actor and e.get('task_id')==task['task_id'] and e.get('native_task_id')==active[0]['actual_observation']['native_task_id'] for e in events)
  reference=registry['canonical_sources'][key];assert reference['entry']['joint_paths']==reference['goal']['joint_paths']==names;assert entry['canonical_entry']['source_asset_sha256']==assets[asset_id]['content_hash'];wanted=world_goal(reference['entry'],reference['goal'],rows[actor][first-1]);hold=continuous_world_goal(active,wanted,2);continuity=bounded_world_steps(active);seams={'entry':seam(rows[actor][first-1],rows[actor][first]),'exit':seam(rows[actor][last],rows[actor][last+1])};soles=[geometry.evaluate(r['world_pose']) for r in samples];times=np.array([r['sim_time'] for r in samples]);assert np.allclose(np.diff(times),1/30,atol=1e-7,rtol=0);foot_results={}
  for side in feet:
   points=np.array([s[side] for s in soles]);foot_results[side],contact=support_quality(times,points);np.savez_compressed(out/(key+'_'+side+'_sole.npz'),sim_time=times,points_world_m=points,estimated_contact=contact)
  passed=hold['passed'] and continuity['passed'] and all(s['passed'] for s in seams.values()) and all(f['passed'] for f in foot_results.values());is_generated='official_generated' in entry.get('motion_kind','') and bool(entry.get('source_model_artifact_sha256'));results.append({'actor_id':actor,'goal':goal,'clip':clip,'motion_kind':entry.get('motion_kind'),'generated_motion':is_generated,'passed':passed,'actual_clip_samples':len(active),'world_goal_hold':hold,'all_active_world_steps':continuity,'seams':seams,'feet':foot_results,'goal_world_pose':wanted.tolist()});print(key,'PASS' if passed else 'FAIL','generated' if is_generated else 'STATIC/OTHER',flush=True)
result={'method_version':'simpeople.actual-world-goal-continuity.v2','run_id':args.run_id,'passed':bool(results) and lifecycle['passed'] and all(r['passed'] for r in results),'native_lifecycle_passed':lifecycle['passed'],'cases':results,'assets':asset_checks,'generated_cases':sum(r['generated_motion'] for r in results),'generated_cases_passed':sum(r['generated_motion'] and r['passed'] for r in results),'qualified_generated_native_rigs':[],'single_case_screen_only':len(selected)==1,'inputs_sha256':{n:sha(run/n) for n in ['source_manifest.json','native_pose_history.jsonl','generated_native_acceptance.json','asset_manifest.json']},'scope':'Separate v2 audit: >=2s continuous actual full-joint world goal within one owned native task, anchored once at entry; original2cm/2deg applied to EVERY actual clip frame and native entry/exit; unchanged3cm/2s skinned sole gate. Does not assume a native source playhead or rewrite v1 grades. One goal or a static control never qualifies an entire generated rig.'}
(out/'actual_pose_goal_quality_v2.json').write_text(json.dumps(result,indent=2)+'\n');(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):sha(f) for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n');raise SystemExit(0 if result['passed'] else 2)
