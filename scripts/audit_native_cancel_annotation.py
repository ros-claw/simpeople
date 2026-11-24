"""Read-only measurement of the raw SDK cancellation annotation experiment."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


def measure(trial, aid, rows):
    before=trial['before_cancel'][aid];anchor=trial['anchors'][aid];old=trial['retired_native_ids'][aid]
    if type(old) is not int or old<=0:raise ValueError('positive retired SDK task required')
    begin,end=trial['cancel_sim_time'],trial['end_sim_time']
    if (not all(type(t) in (int,float) and math.isfinite(t) for t in [begin,end,trial['started_sim_time']])
            or not 0<end-begin<=15+1e-7 or abs(begin-trial['started_sim_time']-trial['requested_elapsed_s'])>1e-6):
        raise ValueError('original trial/cancellation clock changed')
    selected=[r for r in rows if r['trial_id']==trial['trial_id'] and r['actor_id']==aid and begin-1e-7<=r['sim_time']<=end+1e-7]
    if (len(selected)<2 or selected[0]!=before or abs(selected[0]['sim_time']-begin)>1e-7
            or abs(selected[-1]['sim_time']-end)>1e-7):raise ValueError('actual cancellation boundaries missing')
    if before['actual_observation']['action']!=aid or before['actual_observation']['native_task_id']!=old:
        raise ValueError('cancel did not target the actual playing SDK action')
    keys=['actor_id','actor_instance_id','session_id','episode_id','traffic_body_instance_id','native_actor_prim_path','control_epoch']
    identity=tuple(before[k] for k in keys)
    if any(not isinstance(v,str) or not v for v in identity[:-1]) or type(identity[-1]) is not int or identity[-1]<0:
        raise ValueError('actual body identity missing')
    if tuple(anchor[k] for k in keys)!=identity:raise ValueError('anchor belongs to another actual body')
    names=before['joint_paths']
    if len(names)!=81 or len(set(names))!=81:raise ValueError('all81 actual joints required')
    idle=[]
    for index,row in enumerate(selected):
        obs=row['actual_observation'];tick=row['frame_identity']['source_tick']
        if (tuple(row[k] for k in keys)!=identity or row['joint_paths']!=names or row['retired_native_task_id']!=old
                or obs.get('ready') is not True or obs.get('position_source')!='BehaviorAgent.get_world_translation'
                or type(obs.get('observation_sim_time')) not in (int,float)
                or not math.isfinite(obs['observation_sim_time']) or abs(obs['observation_sim_time']-row['sim_time'])>1e-7
                or type(tick) is not int or type(obs.get('native_task_id')) is not int
                or row['retired_native_status'] not in {'running','failed','succeeded'}):
            raise ValueError('stale, recreated or unbound actual SDK body')
        if index and (tick!=selected[index-1]['frame_identity']['source_tick']+1
                      or abs(row['sim_time']-selected[index-1]['sim_time']-1/30)>1e-6):
            raise ValueError('actual world samples are not continuous30Hz')
        speed=obs.get('speed_mps')
        if type(speed) not in (int,float) or not math.isfinite(speed) or speed<0:raise ValueError('invalid actual root speed')
        if index:
            if row['retired_native_status']!='running' and obs['action']=='Idle' and obs['native_task_id']!=old and speed<.15:
                idle.append(row['sim_time'])
            else:idle.clear()
    if idle!=trial['actual_idle_times'][aid]:raise ValueError('reported idle interval differs from actual SDK rows')
    poses=np.asarray([r['world_pose'] for r in selected],dtype=float);ref=np.asarray(anchor['world_pose'],dtype=float)
    if poses.shape!=(len(selected),81,7) or ref.shape!=(81,7) or not np.isfinite(poses).all() or not np.isfinite(ref).all():
        raise ValueError('finite complete actual world poses required')
    for values in [poses[:,:,3:],ref[:,3:]]:
        if np.max(np.abs(np.linalg.norm(values,axis=-1)-1))>1e-3:raise ValueError('invalid SDK quaternion norm')
    position=np.linalg.norm(poses[1:,:,:3]-poses[:-1,:,:3],axis=-1)
    angle=np.degrees((Rotation.from_quat(poses[:-1,:,3:].reshape(-1,4)).inv()*Rotation.from_quat(poses[1:,:,3:].reshape(-1,4))).magnitude())
    gap=float(np.linalg.norm(poses[0,:,:3]-ref[:,:3],axis=-1).max())
    gap_angle=float(np.degrees((Rotation.from_quat(ref[:,3:]).inv()*Rotation.from_quat(poses[0,:,3:])).magnitude()).max())
    stop=bool(len(idle)>=16 and idle[-1]-idle[0]>=.5-1e-7)
    return {'actor_id':aid,'trial_id':trial['trial_id'],'actual_samples':len(selected),'physical_stop_observed':stop,
            'max_all_joint_position_step_m':float(position.max()),'max_all_joint_angle_step_deg':float(angle.max()),
            'world_continuity_passed':bool(position.max()<=.02 and angle.max()<=2),
            'actual_gap_from_own_idle_anchor_m':gap,'actual_gap_from_own_idle_anchor_deg':gap_angle,
            'non_neutral_at_cancel':gap>.05 or gap_angle>10,
            'idle_window_s':idle[-1]-idle[0] if idle else 0.,'requested_elapsed_s':trial['requested_elapsed_s']}


def sha_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def audit(folder):
    folder=Path(folder);errors=[];results=[];hashes={};comparable=False;witness_ok=False
    try:
        read=lambda n:json.loads((folder/n).read_text());done=read('completed.json');spec=read('source_snapshot/spec.json')
        if done.get('harness_completed') is not True:raise ValueError('Native diagnostic unclosed')
        if spec['cancel_elapsed_s']!=[1.5,13.,27.7] or spec['cancel_budget_s']!=15:raise ValueError('diagnostic matrix/budget changed')
        manifest=read('source_manifest.json');snap=folder/'source_snapshot'
        for name,digest in manifest.items():
            path=snap/name
            if not path.resolve().is_relative_to(snap.resolve()) or sha_file(path)!=digest:raise ValueError('frozen source changed')
        imports=read('actual_imported_annotations.json');raw_arrays={}
        if set(imports['actions'])!={'neutral_end','zero_end'}:raise ValueError('both annotation variants required')
        for name in ['neutral_end','zero_end']:
            item=imports['actions'][name]
            if sha_file(item['file'])!=item['sha256']:raise ValueError('imported clip changed')
            if sha_file(item['authored_pose_arrays_file'])!=item['authored_pose_arrays_sha256']:raise ValueError('imported pose arrays changed')
            with np.load(item['authored_pose_arrays_file'],allow_pickle=False) as data:
                if set(data.files)!={k+s for k in ['translations','rotations','scales'] for s in ['', '_times']}:
                    raise ValueError('incomplete imported pose arrays')
                raw_arrays[name]={k:data[k].copy() for k in data.files}
                if any(not np.isfinite(v).all() for v in raw_arrays[name].values()):raise ValueError('nonfinite imported pose arrays')
            ann={r['tag']:[r['start'],r['end']] for r in item['annotations']}
            expected=spec['actions'][name].get('native_phase_ranges',{'ActionStart':[0,0],'ActionLoop':[0,1462],'ActionEnd':[0,0]})
            if any(ann.get(k)!=v for k,v in expected.items()):raise ValueError('actual phase annotations differ from experimental spec')
        comparable=(imports['actions']['neutral_end']['joint_paths']==imports['actions']['zero_end']['joint_paths']
                    and all(np.array_equal(v,raw_arrays['zero_end'][k]) for k,v in raw_arrays['neutral_end'].items()))
        capture=[json.loads(x) for x in (folder/'video_timestamps.jsonl').open()];metrics=read('recording_metrics.json')
        if (len(capture)!=done['frames'] or len(capture)!=metrics['frames_written'] or metrics['empty_rgb_frames'] or metrics['dropped_frames']):
            raise ValueError('actual RGB incomplete')
        for i,stamp in enumerate(capture):
            if stamp['frame']!=i or stamp['frame_identity']['source_tick']!=i or (i and abs(stamp['sim_time']-capture[i-1]['sim_time']-1/30)>1e-6):
                raise ValueError('RGB identities/clock changed')
        rows=[json.loads(x) for x in (folder/'native_cancel_history.jsonl').open()]
        for aid in ['neutral_end','zero_end']:
            own=[row for row in rows if row['actor_id']==aid]
            if len(own)!=len(capture):raise ValueError('actual body frame denominator mismatch')
            for row,stamp in zip(own,capture):
                if row['frame_identity']!=stamp['frame_identity'] or abs(row['sim_time']-stamp['sim_time'])>1e-7:
                    raise ValueError('actual body/RGB frame binding mismatch')
        trials=read('cancel_trials.json')['trials']
        if len({t['trial_id'] for t in trials})!=len(trials) or any(t['trial_id']!=i for i,t in enumerate(trials)):
            raise ValueError('trial ID duplicated or changed')
        for trial_id,delay in enumerate(spec['cancel_elapsed_s']):
            for aid in ['neutral_end','zero_end']:
                try:
                    trial=next(t for t in trials if t['trial_id']==trial_id)
                    if trial['requested_elapsed_s']!=delay:raise ValueError('cancel timing changed')
                    result=measure(trial,aid,rows);results.append({'verified':True,'measurement':result,'errors':[]})
                except (ValueError,KeyError,TypeError,IndexError,StopIteration) as error:
                    results.append({'verified':False,'actor_id':aid,'trial_id':trial_id,'measurement':{},'errors':[str(error) or 'trial not exercised']})
        witnesses=[]
        for line in (folder/'trajectories.jsonl').open():
            row=json.loads(line)
            if row['actor_id']=='witness':witnesses.append(row)
        task=read('cancel_trials.json')['witness_task']
        if not witnesses or task['status']!='running':raise ValueError('witness did not retain its active task')
        if any(any(row.get(k)!=task[k] for k in ['task_id','actor_instance_id','session_id','episode_id','control_epoch']) for row in witnesses):
            raise ValueError('witness owner changed')
        if len(witnesses)!=len(capture):raise ValueError('witness capture incomplete')
        for row,stamp in zip(witnesses,capture):
            position=row.get('position_m')
            if (row.get('ready') is not True or row.get('position_source')!='BehaviorAgent.get_world_translation'
                    or row.get('frame_identity')!=stamp['frame_identity'] or row.get('observation_sim_time')!=row['sim_time']
                    or abs(row['sim_time']-stamp['sim_time'])>1e-7 or not isinstance(position,list) or len(position)!=3
                    or not all(type(v) in (int,float) and math.isfinite(v) for v in position)):
                raise ValueError('witness actual body/RGB binding missing')
        witness_ok=max(math.dist(row['position_m'][:2],witnesses[0]['position_m'][:2]) for row in witnesses)>1
        for name in ['native_cancel_history.jsonl','cancel_trials.json','actual_imported_annotations.json','source_manifest.json','completed.json','video_timestamps.jsonl','trajectories.jsonl','recording_metrics.json']:
            hashes[name]=sha_file(folder/name)
    except (OSError,ValueError,KeyError,TypeError,IndexError) as error:errors.append(str(error))
    verified=not errors and len(results)==6 and all(r['verified'] for r in results)
    non_neutral=all(any(r['verified'] and r['measurement']['actor_id']==aid and r['measurement']['non_neutral_at_cancel']
                        and r['measurement']['requested_elapsed_s']>1.5 for r in results) for aid in ['neutral_end','zero_end'])
    return {'run_id':folder.name,'measurement_verified':verified,'errors':errors,'expected_comparisons':6,'results':results,
            'imported_pose_arrays_identical':comparable,'witness_participation_verified':witness_ok,'inputs_sha256':hashes,
            'both_variants_non_neutral_exercised':non_neutral,
            'all_raw_sdk_cases_quality_passed':bool(verified and comparable and witness_ok and non_neutral and all(r['measurement']['physical_stop_observed'] and r['measurement']['world_continuity_passed'] for r in results)),
            'production_source_installed':False,'qualified_generated_native_rigs':[],
            'scope':'Raw SDK annotation counterfactual only. Elapsed clock is not actual source playhead. No public cancellation, canonical admission, natural tempo, generated rig or catalog qualification. Prefix cases alone cannot establish non-neutral cancellation.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);args=p.parse_args()
    result=audit(args.run);Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['run_id','measurement_verified','errors','all_raw_sdk_cases_quality_passed']}))
    raise SystemExit(0 if result['measurement_verified'] else 2)
