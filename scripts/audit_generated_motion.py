"""Audit actual native readback of short standing generated-action probes."""
import argparse,json,hashlib,math
from collections import defaultdict
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('run_id');args=p.parse_args();directory=ROOT/'runs'/args.run_id
records=defaultdict(list)
for line in (directory/'native_pose_history.jsonl').open():
    row=json.loads(line);records[row['actor_id']].append(row)
profiles={
    81:{'left_arm':['L_UpArm','L_LoArm','L_Wrist'],'right_arm':['R_UpArm','R_LoArm','R_Wrist'],'left_leg':['L_UpLeg','L_LoLeg','L_Ankle'],'right_leg':['R_UpLeg','R_LoLeg','R_Ankle']},
    101:{'left_arm':['L_Upperarm','L_Forearm','L_Hand'],'right_arm':['R_Upperarm','R_Forearm','R_Hand'],'left_leg':['L_Thigh','L_Calf','L_Foot'],'right_leg':['R_Thigh','R_Calf','R_Foot']}}
actors={}
for actor,rows in records.items():
    names=[n.rsplit('/',1)[-1] for n in rows[0]['joint_paths']];profile=profiles[len(names)];poses=np.array([r['world_pose'] for r in rows]);roots=np.array([r['actual_observation']['position_m'] for r in rows])
    lengths={}
    for limb,chain in profile.items():
        for a,b in zip(chain,chain[1:]):lengths[a+'_'+b]=np.linalg.norm(poses[:,names.index(a),:3]-poses[:,names.index(b),:3],axis=-1)
    worst=max(float(np.max(np.abs(v/np.median(v)-1))) for v in lengths.values())
    root_step=float(np.max(np.linalg.norm(np.diff(roots,axis=0),axis=-1)));clips={}
    for name in ['mb_stand','mb_arm']:
        indices=np.array([i for i,r in enumerate(rows) if r['phase']==name and r['actual_observation']['action']==name],dtype=int)
        if not len(indices):clips[name]={'passed':False,'reason':'no actual native clip samples'};continue
        positions=poses[indices,:,:3];base=roots[indices];drift=float(np.linalg.norm(base-base[0],axis=-1).max());feet=[names.index(profile[limb][-1]) for limb in ['left_leg','right_leg']]
        foot_span=max(float(np.linalg.norm(positions[:,j,:2]-positions[0,j,:2],axis=-1).max()) for j in feet);floor=float(np.min(positions[:,feet,2]))
        wrist=names.index(profile['left_arm'][-1]);wrist_range=float(np.linalg.norm(np.ptp(positions[:,wrist,:]-base,axis=0)))
        gates={'actual_frames':len(indices)>=10,'root_drift_le_5cm':drift<=.05,'standing_foot_span_le_5cm':foot_span<=.05,'ankle_joint_floor_proxy':floor>=-.02}
        clips[name]={'passed':all(gates.values()),'gates':gates,'actual_frames':len(indices),'root_drift_m':drift,'standing_foot_horizontal_span_m':foot_span,'min_ankle_z_m':floor,'left_wrist_root_relative_range_m':wrist_range}
    gates={'finite_actual_world_poses':bool(np.isfinite(poses).all()),'bone_length_variation_le_2pct':worst<=.02,'root_frame_step_le_15cm':root_step<=.15,'both_clips_proxy_passed':all(c['passed'] for c in clips.values())}
    actors[actor]={'passed':all(gates.values()),'gates':gates,'joint_count':len(names),'max_bone_relative_variation':worst,'max_actual_root_step_m':root_step,'clips':clips}
lifecycle=json.loads((directory/'generated_native_acceptance.json').read_text());result={'run_id':args.run_id,'passed':lifecycle['passed'] and all(a['passed'] for a in actors.values()),'actors':actors,
 'source_history_sha256':hashlib.sha256((directory/'native_pose_history.jsonl').read_bytes()).hexdigest(),
 'scope':'Short standing-clip proxy audit plus native lifecycle. Not skin/sole contact, source-target retarget error, canonical entry or arbitrary PoseBridge certification.'}
(directory/'generated_motion_quality.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
