"""Offline heading/pose decomposition of a recorded canonical native failure.

Nearest source pose is a diagnostic, never a claimed native playback cursor.
Body-frame sole measurements remove world motion and cannot qualify foot support.
The original acceptance files and their failures are left unchanged.
"""
import argparse, hashlib, json, math, shutil, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--run-id',required=True)
p.add_argument('--output',required=True)
args=p.parse_args()
run=ROOT/'runs'/args.run_id
out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
snap=out/'source_snapshot';snap.mkdir()
shutil.copytree(ROOT/'src',snap/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copy2(__file__,snap/Path(__file__).name)
sys.path.insert(0,str(snap/'src'))
import numpy as np
from pxr import Usd,UsdGeom,UsdSkel,Gf
from simpeople.motion.rig import forward_kinematics,rotate,multiply
from simpeople.motion.quality import support_quality
from simpeople.backends.native.foot_geometry import FootGeometry

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(name,data):(out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def angle(facing):return math.atan2(facing[0],-facing[1])
def angular_delta(a,b):return math.degrees(math.atan2(math.sin(b-a),math.cos(b-a)))
def normalized_points(row):
    v=np.array(row['world_pose']);a=angle(row['actual_observation']['facing_direction'])
    return rotate(np.array([0,0,math.sin(-a/2),math.cos(-a/2)]),v[:,:3]-v[0,:3])
def normalized_rotations(row):
    v=np.array(row['world_pose']);a=angle(row['actual_observation']['facing_direction'])
    q=multiply(np.array([0,0,math.sin(-a/2),math.cos(-a/2)]),v[:,3:])
    return q/np.linalg.norm(q,axis=-1,keepdims=True)

registry=json.loads((run/'source_snapshot/inputs/actions.json').read_text())
assets={a['asset_id']:a for a in json.loads((run/'asset_manifest.json').read_text())}
rows={'operator':[],'second':[]}
for line in (run/'native_pose_history.jsonl').open():
    row=json.loads(line)
    if row['actor_id'] in rows:rows[row['actor_id']].append(row)
inputs={n:sha(run/n) for n in ['native_pose_history.jsonl','events.jsonl','source_manifest.json','generated_native_acceptance.json','asset_manifest.json']}
results=[]
for actor,asset_id in [('operator','default'),('second','female_adult_business_02')]:
    source=Path(assets[asset_id]['source_uri']);assert sha(source)==assets[asset_id]['content_hash']
    original=Usd.Stage.Open(str(source));stage=Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z')
    model=UsdGeom.Xform.Define(stage,'/World/Model');model.GetPrim().GetReferences().AddReference(str(source))
    matrix=Gf.Matrix4d().SetScale(UsdGeom.GetStageMetersPerUnit(original))
    if UsdGeom.GetStageUpAxis(original)=='Y':matrix*=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1,0,0),90))
    UsdGeom.Xformable(model).MakeMatrixXform().Set(matrix)
    root=next(UsdSkel.Root(x) for x in Usd.PrimRange(model.GetPrim()) if x.IsA(UsdSkel.Root))
    skeleton=next(UsdSkel.Skeleton(x) for x in Usd.PrimRange(root.GetPrim()) if x.IsA(UsdSkel.Skeleton))
    names=list(map(str,skeleton.GetJointsAttr().Get()));assert names==rows[actor][0]['joint_paths']
    leaves=[n.rsplit('/',1)[-1] for n in names]
    feet={side:leaves.index(short) for side,short in [('left','L_Ankle' if 'L_Ankle' in leaves else 'L_Foot'),('right','R_Ankle' if 'R_Ankle' in leaves else 'R_Foot')]}
    geometry=FootGeometry(stage,str(root.GetPath()),feet)
    for goal in [g for g in registry['canonical_cases'] if any(r['phase']=='canonical_'+g for r in rows[actor])]:
        clip='canonical_'+actor+'__'+goal
        samples=[r for r in rows[actor] if r['phase']=='canonical_'+goal]
        times=np.array([r['sim_time'] for r in samples])
        active=np.array([r['actual_observation']['action']==clip for r in samples])
        indices=np.flatnonzero(active);assert len(indices)>3 and np.all(np.diff(indices)==1)
        first=int(indices[0]);assert first>0
        yaws=np.unwrap([angle(r['actual_observation']['facing_direction']) for r in samples])
        points=[geometry.evaluate(r['world_pose']) for r in samples]
        admission=[r for r in rows[actor] if r['phase']=='canonical_admission_'+goal and r['sim_time']<samples[0]['sim_time']][-5:]
        speeds=[abs(angular_delta(angle(a['actual_observation']['facing_direction']),angle(b['actual_observation']['facing_direction'])))/(b['sim_time']-a['sim_time']) for a,b in zip(admission,admission[1:])]
        foot_results={}
        for side in feet:
            world=np.array([v[side] for v in points])
            whole,_=support_quality(times,world)
            active_world,_=support_quality(times[active],world[active])
            body=[]
            for row,value in zip(samples,world):
                a=angle(row['actual_observation']['facing_direction']);q=np.array([0,0,math.sin(-a/2),math.cos(-a/2)])
                # Retain floor-relative Z; factor only planar root/yaw for diagnosis.
                origin=np.array([*row['world_pose'][0][:2],0])
                body.append(rotate(q,value-origin))
            factored,_=support_quality(times[active],np.array(body)[active])
            foot_results[side]={'whole_phase_including_later_idle':whole,'actual_clip_active_only':active_world,'root_and_heading_factored_diagnostic_only':factored}
        source_matching=None
        source_file=run/f'custom_actions/clips/{clip}/{clip}.usd'
        cs=Usd.Stage.Open(str(source_file));anim=UsdSkel.Animation(cs.GetDefaultPrim());clip_names=list(map(str,anim.GetJointsAttr().Get()))
        inputs[str(source_file.relative_to(run))]=sha(source_file)
        if clip_names==names:
            # ImportCustomActionCommand scales retarget data to cm, regardless
            # of the output file's carried-over source metadata. The binding is
            # to the Human motion library's Y-up/cm skeleton, not this metadata.
            library=Usd.Stage.Open(assets[asset_id]['motion_library'])
            assert UsdGeom.GetStageUpAxis(library)=='Y' and abs(UsdGeom.GetStageMetersPerUnit(library)-.01)<1e-12
            frames=anim.GetRotationsAttr().GetTimeSamples()
            local=np.array([[[*t,*q.GetImaginary(),q.GetReal()] for t,q in zip(anim.GetTranslationsAttr().Get(f),anim.GetRotationsAttr().Get(f))] for f in frames])
            parents=[names.index(n.rsplit('/',1)[0]) if '/' in n else -1 for n in names]
            expected=forward_kinematics(local,parents)
            q=np.array([math.sqrt(.5),0,0,math.sqrt(.5)])
            expected[:,:,:3]=rotate(q,expected[:,:,:3]*.01);expected[:,:,3:]=multiply(q,expected[:,:,3:])
            source_soles=[geometry.evaluate(frame) for frame in expected]
            source_feet={side:support_quality(np.array(frames)/30,np.array([x[side] for x in source_soles]))[0] for side in feet}
            source_points=expected[:,:,:3]-expected[:,0:1,:3]
            matches=[]
            for row in samples:
                actual=normalized_points(row);dist=np.linalg.norm(source_points-actual,axis=-1)
                frame=int(np.argmin(np.mean(dist**2,axis=-1)))
                matches.append({'sim_time':row['sim_time'],'native_action':row['actual_observation']['action'],'closest_source_frame':frames[frame],'all_joint_rmse_m':float(np.sqrt(np.mean(dist[frame]**2))),'max_joint_error_m':float(dist[frame].max())})
            write(actor+'__'+goal+'_nearest_poses.json',matches)
            source_matching={'all_joints':len(names),'samples':len(matches),'source_fixed_root_sole_checks':source_feet,'native_active_max_nearest_position_error_m':max(m['max_joint_error_m'] for m,a in zip(matches,active) if a),'not_a_native_phase_cursor':True}
        else:
            source_matching={'unavailable':'shared Human source clip and actual actor have different joint layouts; no partial-bone match used','source_joint_count':len(clip_names),'actual_joint_count':len(names)}
        # Search every actually active sample, independently of the scheduled
        # source-frame bands. A bad best sample rules out clock offset alone;
        # a good one is still not a sustained, certified goal hold.
        reference=registry['canonical_sources'][actor+'__'+goal]['goal']
        assert len(reference['world_pose'])==len(names)
        wanted=normalized_points(reference);wanted_q=normalized_rotations(reference)
        actual=np.array([normalized_points(r) for r,a in zip(samples,active) if a])
        actual_q=np.array([normalized_rotations(r) for r,a in zip(samples,active) if a])
        positions=np.linalg.norm(actual-wanted,axis=-1)
        angles=np.degrees(2*np.arccos(np.clip(np.abs(np.sum(actual_q*wanted_q,axis=-1)),0,1)))
        scores=np.maximum((positions/.03).max(axis=-1),(angles/5).max(axis=-1))
        best=int(np.argmin(scores));worst=np.maximum(positions[best]/.03,angles[best]/5)
        goal_good=scores<=1;edges=np.diff(np.r_[False,goal_good,False].astype(int));active_times=times[active]
        intervals=[{'start_sim_time':float(active_times[a]),'duration_s':float(active_times[b-1]-active_times[a]),'samples':int(b-a)} for a,b in zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1))]
        goal_search={'all_actual_joints':len(names),'best_sim_time':float(active_times[best]),'best_max_position_error_m':float(positions[best].max()),'best_max_rotation_error_deg':float(angles[best].max()),'best_sample_within_goal_tolerances':bool(goal_good[best]),'observed_matching_intervals':intervals,
            'worst_joints_at_best_sample':[{'joint':names[i],'position_error_m':float(positions[best,i]),'rotation_error_deg':float(angles[best,i])} for i in np.argsort(worst)[-10:][::-1]],'not_acceptance':'All-active diagnostic search, not a native phase cursor, scheduled hold validation or full quality certificate.'}
        result={'actor_id':actor,'goal':goal,'clip':clip,'phase_samples':len(samples),'actual_clip_samples':int(active.sum()),'entry_heading_step_deg':angular_delta(angle(samples[first-1]['actual_observation']['facing_direction']),angle(samples[first]['actual_observation']['facing_direction'])),'phase_heading_range_deg':[float(np.degrees(yaws).min()),float(np.degrees(yaws).max())],'admission_last_four_max_angular_speed_deg_s':max(speeds,default=None),'feet':foot_results,'source_matching':source_matching,'all_joint_goal_search':goal_search,'foot_patch_description':geometry.describe()}
        results.append(result)
        print(actor,goal,'entry_heading_step_deg',round(result['entry_heading_step_deg'],4),'active_foot_drifts',[(side,round(v['actual_clip_active_only']['worst_support']['max_selected_vertex_drift_m'],4)) for side,v in foot_results.items()],flush=True)
write('diagnosis.json',{'run_id':args.run_id,'inputs_sha256':inputs,'cases':results,'scope':'Offline decomposition, not acceptance or a root correction. All actual joints and fixed sole patches retained. Factoring heading/root is explanatory only, never a replacement for the world-space 3cm support gate. Later Idle is reported separately; original audit/failed runs remain unchanged.'})
write('source_manifest.json',{str(f.relative_to(snap)):sha(f) for f in sorted(snap.rglob('*')) if f.is_file()})
