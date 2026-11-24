"""Independent source/frame/owner checks supplement the unchanged old proxy audit."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


def custom_step_bindings(tasks, cast, events, prims):
    """Bind the custom step, rather than every SDK task in its activity."""
    result = {}
    cursors = [e.get('cursor') for e in events]
    if (any(type(c) is not int for c in cursors)
            or any(a >= b for a, b in zip(cursors, cursors[1:]))):
        raise ValueError('ordered unique journal cursors required')
    for actor in cast:
        aid = actor['actor_id']; task = tasks[aid]
        relevant = [e for e in events if e.get('actor_id') == aid and e.get('task_id') == task['task_id']]
        starts = [e for e in relevant if e['kind'] == 'step_started' and e.get('index') == 0]
        ends = [e for e in relevant if e['kind'] == 'step_ended' and e.get('index') == 0]
        if len(starts) != 1 or len(ends) != 1:
            raise ValueError('one original custom step start/end required')
        start, end = starts[0], ends[0]
        expected = {'action': 'custom_action', 'target': actor['action'], 'duration_s': 25, 'timeout_s': 40}
        if (task['steps'][0] != expected or start.get('step') != expected
                or start.get('native_kind') != 'custom_action' or end.get('action') != 'custom_action'
                or not finite_time(start.get('sim_time')) or not finite_time(end.get('sim_time'))
                or not 0 < end['sim_time'] - start['sim_time'] <= 40 + 1e-7
                or start['cursor'] >= end['cursor']):
            raise ValueError('original custom step or deadline changed')
        fields = ['session_id', 'episode_id', 'actor_instance_id']
        if any(e.get(k) != task[k] for e in [start, end] for k in fields):
            raise ValueError('custom step belongs to another owner')
        sid = start.get('native_task_id')
        if type(sid) is not int or start.get('backend_task_id') != sid:
            raise ValueError('actual SDK custom task required')
        bound = [e for e in relevant if e['kind'] == 'native_task_bound'
                 and start['sim_time']-1e-7 <= e['sim_time'] <= end['sim_time']+1e-7]
        if (len(bound) != 1 or bound[0].get('native_task_id') != sid
                or bound[0].get('backend_task_id') != sid or bound[0]['cursor'] != start['cursor']-1
                or abs(bound[0]['sim_time']-start['sim_time']) > 1e-7
                or any(bound[0].get(k) != task[k] for k in fields + ['control_epoch'])):
            raise ValueError('one same-owner SDK binding for the custom step required')
        reserved = [e for e in events if e['kind'] == 'custom_action_space_reserved'
                    and e.get('native_task_id') == sid]
        if (len(reserved) != 1 or reserved[0].get('agent') != prims[aid]
                or reserved[0].get('clip') != actor['action']
                or reserved[0]['cursor'] != bound[0]['cursor']-1
                or not finite_time(reserved[0].get('sim_time'))
                or abs(reserved[0]['sim_time']-start['sim_time']) > 1e-7
                or any(reserved[0].get(k) != task[k] for k in ['session_id', 'episode_id'])):
            raise ValueError('custom space reservation belongs to another body or clip')
        result[aid] = {sid}
    return result


def finite3(value):
    return isinstance(value,list) and len(value)==3 and all(type(x) in (int,float) and math.isfinite(x) for x in value)


def finite_time(value):
    return type(value) in (int,float) and math.isfinite(value)


def coherent_streams(tasks,cast,witness,rows,timestamps,cameras,clip_bindings):
    actors={r['actor_id']:r for r in cast};expected=set(actors)|{witness}
    if len(actors)!=len(cast) or set(tasks)!=expected or not timestamps or len(cameras)!=len(timestamps):
        raise ValueError('cast/task/frame denominator mismatch')
    if set(clip_bindings)!=set(actors) or any(len(ids)!=1 for ids in clip_bindings.values()):
        raise ValueError('one actual SDK custom task binding per actor required')
    for aid,task in tasks.items():
        if task['actor_id']!=aid or task['status']!='succeeded':raise ValueError('actual activity did not succeed')
        if any(not isinstance(task.get(k),str) or not task[k] for k in ['session_id','episode_id','task_id','actor_instance_id']):
            raise ValueError('logical owner fences missing')
        if type(task.get('control_epoch')) is not int or task['control_epoch']<1:raise ValueError('invalid control epoch')
    if len({(t['session_id'],t['episode_id']) for t in tasks.values()})!=1:raise ValueError('tasks borrowed another session')
    count=len(timestamps);seen={aid:set() for aid in expected};body={};prims={};previous={};initial={};movement={aid:0. for aid in expected}
    streak={aid:0 for aid in actors};longest={aid:0 for aid in actors}
    for index,stamp in enumerate(timestamps):
        ident=stamp.get('frame_identity',{})
        if (type(stamp.get('frame')) is not int or stamp['frame']!=index
                or type(ident.get('source_tick')) is not int or ident['source_tick']!=index
                or type(ident.get('video_frame')) is not int or ident['video_frame']!=index
                or not finite_time(stamp.get('sim_time'))):
            raise ValueError('RGB frame identity is incomplete or reordered')
        if index and abs(stamp['sim_time']-timestamps[index-1]['sim_time']-1/30)>1e-6:raise ValueError('RGB clock gap')
        if (cameras[index]['frame_identity']!=ident or not finite_time(cameras[index].get('sim_time'))
                or abs(cameras[index]['sim_time']-stamp['sim_time'])>1e-7):
            raise ValueError('camera/RGB frame mismatch')
    for row in rows:
        aid=row.get('actor_id');ident=row.get('frame_identity',{});index=ident.get('source_tick')
        if aid not in expected or type(index) is not int or not 0<=index<count or index in seen[aid]:
            raise ValueError('unknown actor, duplicate or extra body frame')
        task=tasks[aid];stamp=timestamps[index]
        if (ident!=stamp['frame_identity'] or not finite_time(row.get('sim_time')) or not finite_time(row.get('observation_sim_time'))
                or abs(row['sim_time']-stamp['sim_time'])>1e-7
                or abs(row.get('observation_sim_time',-999)-row['sim_time'])>1e-7 or row.get('ready') is not True
                or row.get('position_source')!='BehaviorAgent.get_world_translation' or not finite3(row.get('position_m'))
                or any(row.get(k)!=task[k] for k in ['session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id'])):
            raise ValueError('actual body/RGB/owner mismatch')
        generation=row.get('traffic_body_instance_id');prim=row.get('native_actor_prim_path')
        if not isinstance(generation,str) or not generation or not isinstance(prim,str) or not prim:
            raise ValueError('Native body/prim binding missing')
        if aid in body and (generation!=body[aid] or prim!=prims[aid]):raise ValueError('Native body recreated during regression')
        body[aid]=generation;prims[aid]=prim;seen[aid].add(index)
        if aid in previous and index!=previous[aid]+1:raise ValueError('body stream not ordered/continuous')
        previous[aid]=index;initial.setdefault(aid,row['position_m'])
        movement[aid]=max(movement[aid],math.dist(initial[aid][:2],row['position_m'][:2]))
        if aid in actors:
            joints=row.get('joints_m',{})
            if not all(f in joints for f in ['LeftFoot','RightFoot']) or any(not finite3(p) for p in joints.values()):
                raise ValueError('recorded joint evidence missing/nonfinite')
            matches=(cameras[index]['shot_actor_id']==aid and row.get('action')==actors[aid]['action']
                     and type(row.get('native_task_id')) is int and row['native_task_id'] in clip_bindings[aid])
            streak[aid]=streak[aid]+1 if matches else 0;longest[aid]=max(longest[aid],streak[aid])
    if any(len(frames)!=count for frames in seen.values()):raise ValueError('actor missing from actual capture frames')
    if len(set(body.values()))!=len(expected) or len(set(prims.values()))!=len(expected):raise ValueError('actors borrowed the same physical body')
    if movement[witness]<=1:raise ValueError('witness had no measured participation')
    if any(n<61 for n in longest.values()):raise ValueError('two seconds of continuous close-view clip samples missing')
    return {'frames_per_actor':count,'actor_count':len(expected),'max_displacement_from_first_actual_m':movement,
            'continuous_close_view_clip_frames':longest,'body_generations':body,'native_prims':prims,
            'limits':'Camera metadata, actual SDK roots, source frames and logical/body identity only. Actual footage still needs visual review; no mesh/contact-force or generated-rig certificate.'}


def review(folder,legacy_auditor):
    folder=Path(folder);errors=[];proxy=None;coherence=None
    try:
        read=lambda n:json.loads((folder/n).read_text());done=read('completed.json')
        if done.get('harness_completed') is not True or done.get('functional_expected_matched') is not True:
            raise ValueError('Native legacy harness did not finish successfully')
        snapshot=folder/'source_snapshot';manifest=read('source_manifest.json')
        for name,digest in manifest.items():
            path=snapshot/name
            if not path.resolve().is_relative_to(snapshot.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError('frozen source/input changed: '+name)
        case=read('source_snapshot/case.json');cast=read('cinematic_cast.json')
        if cast!=case['cast'] or len(cast)!=8:raise ValueError('original eight clip/asset combinations changed')
        tasks=read('legacy_regression_tasks.json');final_tasks={t['actor_id']:t for t in read('tasks.json')}
        if any(final_tasks.get(aid,{}).get('task_id')!=t['task_id'] or final_tasks[aid]['status']!='succeeded' for aid,t in tasks.items()):
            raise ValueError('stored final task differs from successful measurement')
        for actor in cast:
            expected=[{'action':'custom_action','target':actor['action'],'duration_s':25,'timeout_s':40},
                      {'action':'move_to','target':actor['move_target_m'],'gait':'walk','timeout_s':15},
                      {'action':'wait','duration_s':.2}]
            if tasks[actor['actor_id']]['steps']!=expected:raise ValueError('legacy activity budget/target changed')
        expected_witness=[{'action':'move_to','target':p,'gait':'walk','timeout_s':75} for p in case['witness']['targets_m']]
        if tasks[case['witness']['actor_id']]['steps']!=expected_witness:raise ValueError('witness route/budget changed')
        metrics=read('recording_metrics.json');timestamps=[json.loads(line) for line in (folder/'video_timestamps.jsonl').open()]
        if metrics['frames_written']!=done['frames'] or len(timestamps)!=done['frames'] or metrics['empty_rgb_frames'] or metrics['dropped_frames']:
            raise ValueError('recording incomplete')
        cameras=[json.loads(line) for line in (folder/'camera_frames.jsonl').open()]
        events=[json.loads(line) for line in (folder/'events.jsonl').open()]
        rows=[json.loads(line) for line in (folder/'trajectories.jsonl').open()]
        prims={r['actor_id']:r['native_actor_prim_path'] for r in rows if r['actor_id'] in tasks}
        clip_bindings=custom_step_bindings(tasks,cast,events,prims)
        coherence=coherent_streams(tasks,cast,case['witness']['actor_id'],rows,timestamps,cameras,clip_bindings)
        spec=importlib.util.spec_from_file_location('frozen_legacy_proxy',legacy_auditor)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.ROOT=folder.parent.parent;proxy=module.audit(folder.name,accept=False)
        if proxy['passed'] is not True or len(proxy['actions'])!=8:raise ValueError('unchanged old eight-action proxy failed')
    except (OSError,ValueError,KeyError,TypeError,IndexError) as error:errors.append(str(error))
    return {'run_id':folder.name,'verified':not errors,'errors':errors,'legacy_proxy_passed':bool(proxy and proxy['passed']),
            'coherence':coherence,'production_source_installed':False,'qualified_generated_native_rigs':[],
            'gesture_catalog_verified':False,'scope':'Fresh legacy eight-action regression only. No old proof transfer or automatic catalog publication.'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('run');parser.add_argument('--legacy-auditor',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();folder=Path(args.run);result=review(folder,Path(args.legacy_auditor))
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'run_id':result['run_id'],'verified':result['verified'],'errors':result['errors']}))
    raise SystemExit(0 if result['verified'] else 2)
