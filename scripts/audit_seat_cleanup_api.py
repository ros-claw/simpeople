"""Independent raw-frame checks of the Native public seat-cleanup query."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def finite(value):return type(value) in (int,float) and math.isfinite(value)
def point(value):return isinstance(value,list) and len(value)==3 and all(finite(v) for v in value)


def independent_sdk_sample(record,aid,actor,expected):
    """Distinguish this frame's pose from a command submitted after the step.

    A cached same-time pose cannot certify the new command's output. Accept
    that one-frame distinction only with independent before/after SDK reads.
    """
    before=record.get('sdk_reads_before');after=record.get('sdk_reads_after')
    if not isinstance(before,dict) or set(before)!={'operator','witness'} or before!=after:
        raise ValueError('independent SDK query fences missing or changed')
    raw=before[aid];obs=actor['observation'];binding=record['body_bindings'][aid]
    if (raw.get('sim_time')!=record['sim_time'] or raw.get('actor_instance_id')!=actor['actor_instance_id']
            or raw.get('native_actor_prim_path')!=binding['native_actor_prim_path']
            or raw.get('traffic_body_instance_id')!=binding['traffic_body_instance_id']
            or not point(raw.get('position_m')) or math.dist(raw['position_m'],obs['position_m'])>1e-5
            or type(raw.get('current_native_task_id')) is not int
            or raw['current_native_task_id']!=expected['native_task_id']):
        raise ValueError('public pose/current SDK task differs from independent readback')
    joints=raw.get('joints_m')
    if not isinstance(joints,dict) or not joints or set(joints)!=set(obs.get('joints_m',{})):
        raise ValueError('all recorded SDK joints required')
    if any(not point(p) or not point(obs['joints_m'][n]) or math.dist(p,obs['joints_m'][n])>1e-5 for n,p in joints.items()):
        raise ValueError('public joints differ from independent readback')
    if obs['native_task_id']!=raw['current_native_task_id']:
        elapsed=raw.get('current_native_task_elapsed_s')
        if (raw['current_native_task_id']<=0 or not finite(elapsed) or not 0<=elapsed<1e-5
                or not isinstance(raw.get('current_native_task_name'),str) or not raw['current_native_task_name']):
            raise ValueError('SDK/pose task mismatch is not a just-submitted command')
    return raw


def frame(record,stamp):
    now=record['sim_time'];before=record['before'];after=record['after'];state=record['crowd_state']
    if (before!=after or record['read_only_internal_unchanged'] is not True or before['sim_time']!=now
            or record['frame_identity']!=stamp['frame_identity'] or now!=stamp['sim_time']):
        raise ValueError('read changed native/task/lease/clock state or RGB identity')
    if state['session_id']!=before['session_id'] or state['episode_id']!=before['episode_id'] or state['sim_time']!=now:
        raise ValueError('public query belongs to another world/clock')
    actors={a['actor_id']:a for a in state['actors']}
    if set(actors)!={'operator','witness'} or len(state['actors'])!=2:raise ValueError('two exact actors required')
    for aid,actor in actors.items():
        expected=before['actors'][aid]
        if any(actor[k]!=expected[k] for k in ['actor_instance_id','task_id','seat']):raise ValueError('public actor fence changed')
        if actor.get('task')!=before['tasks'].get(actor['task_id']) or actor.get('status')!=actor['task']['status']:
            raise ValueError('public task differs from actual task record')
        # crowd_state exposes the activity epoch inside task, not on the actor row.
        if actor['task']['control_epoch']!=expected['control_epoch']:raise ValueError('public task control generation changed')
        obs=actor['observation']
        if (obs.get('ready') is not True or obs.get('position_source')!='BehaviorAgent.get_world_translation'
                or obs.get('observation_sim_time')!=now or not point(obs.get('position_m'))
                or not finite(obs.get('speed_mps')) or obs['speed_mps']<0):raise ValueError('public observation is stale or borrowed')
        if 'sdk_reads_before' in record or obs['native_task_id']!=expected['native_task_id']:
            independent_sdk_sample(record,aid,actor,expected)
    actor=actors['operator'];raw=record['operator_cleanup_raw'];snapshot=actor['seat_cleanup'];obs=record['operator_observation']
    if obs!=actor['observation']:raise ValueError('public observation differs from actual same-tick SDK sample')
    if snapshot['pending']!=bool(raw['release_seat_when_standing']):raise ValueError('pending cleanup differs from actor')
    if snapshot['pending']:
        if (snapshot['actor_instance_id']!=actor['actor_instance_id'] or snapshot['control_epoch']!=before['actors']['operator']['control_epoch']
                or snapshot['seat_id']!=raw['seat'] or snapshot['actual_observation_ready'] is not True
                or snapshot['since_sim_time']!=raw['cleanup_started'] or snapshot['budget_s']!=15
                or abs(snapshot['deadline_sim_time']-raw['cleanup_started']-15)>1e-7
                or abs(snapshot['remaining_sim_s']-max(0,raw['cleanup_started']+15-now))>1e-7
                or snapshot['exit_backend_task_id']!=raw['cleanup_task'] or snapshot['exit_target']!=raw['cleanup_target']):
            raise ValueError('reported cleanup owner/target/budget differs from original state')
        route=record.get('exit_route_raw')
        if route:
            if route['handle']!=raw['handle'] or snapshot['route_status']!=route['status'] or snapshot['movement_native_task_id']!=route['native_task_id']:
                raise ValueError('cleanup borrowed a different route or SDK task')
            expected=('exit_route_failed' if route['status'] in {'failed','cancelled'} else 'exit_wait' if route['status']=='blocked'
                      else 'settling_exit' if route['status']=='succeeded' else 'exit_route_pending' if route['native_task_id'] is None else 'exit_route_running')
            if snapshot['phase']!=expected:raise ValueError('reported phase differs from actual route state')
            if snapshot['route_goal_m']!=route['goals'][-1]:raise ValueError('original route goal changed in query')
        if snapshot['exit_position_m'] is not None:
            if abs(snapshot['exit_distance_m']-math.dist(obs['position_m'][:2],snapshot['exit_position_m'][:2]))>1e-7:
                raise ValueError('reported exit distance differs from actual root')
    return actors


def sha_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def audit(folder):
    folder=Path(folder);errors=[];hashes={};blocked_rows=[];functional=False;frames=0;switches=[]
    try:
        read=lambda n:json.loads((folder/n).read_text());done=read('completed.json');snap=folder/'source_snapshot'
        if not done['harness_completed'] or done['frames']!=1350 or abs(done['duration_s']-45)>1e-6:raise ValueError('45s/1350frame native probe incomplete')
        manifest=read('source_manifest.json')
        for name,digest in manifest.items():
            p=snap/name
            if not p.resolve().is_relative_to(snap.resolve()) or sha_file(p)!=digest:raise ValueError('frozen source changed')
        case=read('source_snapshot/case.json');acceptance=read('seat_cleanup_api_acceptance.json')
        if case['duration_s']!=45 or case['blocked_hold_s']!=.5 or case['operator_steps'][2]!={'action':'leave_seat'}:
            raise ValueError('case cleanup window/step contract changed')
        if acceptance['operator_task']['steps']!=case['operator_steps'] or acceptance['witness_task']['steps']!=case['witness_steps']:
            raise ValueError('original actor steps changed')
        capture=[json.loads(x) for x in (folder/'video_timestamps.jsonl').open()];metrics=read('recording_metrics.json')
        if len(capture)!=1350 or metrics['frames_written']!=1350 or metrics['empty_rgb_frames'] or metrics['dropped_frames']:
            raise ValueError('native RGB capture incomplete')
        for i,stamp in enumerate(capture):
            if type(stamp['frame']) is not int or stamp['frame']!=i or stamp['frame_identity']['source_tick']!=i or (i and abs(stamp['sim_time']-capture[i-1]['sim_time']-1/30)>1e-6):
                raise ValueError('native RGB clock/identity changed')
        records=[json.loads(x) for x in (folder/'cleanup_api_frames.jsonl').open()]
        if len(records)!=1350:raise ValueError('API record denominator mismatch')
        bindings=None;first={};distance={'operator':0.,'witness':0.};native_generations={};task_ids={}
        for record,stamp in zip(records,capture):
            actors=frame(record,stamp);frames+=1
            for aid,actor in actors.items():
                current=record['before']['actors'][aid]['native_task_id'];observed=actor['observation']['native_task_id']
                if current!=observed:
                    switches.append({'actor_id':aid,'sim_time':record['sim_time'],
                                     'pose_observation_sdk_id':observed,'just_submitted_sdk_id':current})
            current=record['body_bindings']
            if bindings is None:
                bindings=current
                for aid,v in bindings.items():
                    if not all(isinstance(v.get(k),str) and v[k] for k in ['native_actor_prim_path','traffic_body_instance_id']):raise ValueError('native body binding missing')
                    native_generations[aid]=v['traffic_body_instance_id'];task_ids[aid]=actors[aid]['task_id']
                if len(set(native_generations.values()))!=2 or len({v['native_actor_prim_path'] for v in bindings.values()})!=2:raise ValueError('witness shares physical body')
            if current!=bindings:raise ValueError('native body recreated during probe')
            for aid,actor in actors.items():
                expected=acceptance[aid+'_task']
                if (any(actor[k]!=expected[k] for k in ['task_id','actor_instance_id'])
                        or actor['task']['control_epoch']!=expected['control_epoch']
                        or record['before']['session_id']!=expected['session_id'] or record['before']['episode_id']!=expected['episode_id']):
                    raise ValueError('frame borrowed another activity/world')
                if actor['task_id']!=task_ids[aid]:raise ValueError('public query switched activities')
                position=actor['observation']['position_m'];first.setdefault(aid,position)
                distance[aid]=max(distance[aid],math.dist(first[aid][:2],position[:2]))
            snapshot=actors['operator']['seat_cleanup']
            if snapshot.get('phase')=='exit_wait':
                raw=record['operator_cleanup_raw'];obs=record['operator_observation']
                if record['before']['resources']['owners'].get('chair_01')!='operator':raise ValueError('seat released before exit cleared')
                if not point(obs.get('joints_m',{}).get('Hips')):raise ValueError('actual standing hips unavailable')
                if obs['action'] in {'Idle',''} and obs['joints_m']['Hips'][2]-obs['position_m'][2]>.75 and obs['speed_mps']<.15:
                    blocked_rows.append(record)
        controls=acceptance['controls'];clears=[c for c in controls if c['kind']=='clear_exit'];installed=[c for c in controls if c['kind']=='obstruct_exit']
        interval_good=False
        if len(clears)==len(installed)==1:
            times=clears[0]['observed_blocked_times'];interval_good=(len(times)>=16 and times[-1]-times[0]>=.5-1e-7
                and all(abs(b-a-1/30)<1e-6 for a,b in zip(times,times[1:])) and clears[0]['sim_time']<clears[0]['cleanup_deadline_sim_time'])
            actual_times={r['sim_time'] for r in blocked_rows}
            interval_good=interval_good and all(t in actual_times for t in times)
        last=acceptance['final_crowd_state'];op=next(a for a in last['actors'] if a['actor_id']=='operator')
        functional=bool(done['functional_expected_matched'] and acceptance['functional_expected_matched'] and interval_good
                        and acceptance['operator_task']['status']=='succeeded' and acceptance['witness_task']['status']=='running'
                        and not op['seat_cleanup']['pending'] and op['seat'] is None and distance['witness']>1)
        for name in ['completed.json','source_manifest.json','seat_cleanup_api_acceptance.json','cleanup_api_frames.jsonl',
                     'video_timestamps.jsonl','recording_metrics.json','trajectories.jsonl','events.jsonl']:
            hashes[name]=sha_file(folder/name)
    except (OSError,ValueError,KeyError,TypeError,IndexError) as error:errors.append(str(error))
    return {'run_id':folder.name,'measurement_verified':not errors and frames==1350,'errors':errors,'verified_api_frames':frames,
            'native_api_functional_verified':bool(not errors and functional),'standing_exit_wait_samples':len(blocked_rows),
            'pre_execution_sdk_switch_samples':switches,
            'inputs_sha256':hashes,'production_source_installed':False,'qualified_generated_native_rigs':[],
            'scope':'Native/public Engine crowd-state read-only phase/budget/lease test with temporary ownstage obstacle and witness. No actual stdio MCP/host natural language, fullT2matrix, motion/rig/catalog or exact contact qualification.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);args=p.parse_args();result=audit(args.run)
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps({k:result[k] for k in ['run_id','measurement_verified','native_api_functional_verified','errors']}))
    raise SystemExit(0 if result['measurement_verified'] else 2)
