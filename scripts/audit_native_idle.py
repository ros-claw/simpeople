"""Actual SDK root stability within an explicitly owned, closed wait task.

These are root/clock/control screens. They are not skinned-sole, whole-mesh,
contact-force or generated-motion quality certificates.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def evaluate(rows,task,joint_paths,duration_s):
    wanted=[r for r in rows if r['phase']=='idle_context' and r['actor_id']==task['actor_id'] and r['activity_task_id']==task['task_id']]
    errors=[]
    if len(wanted)<4:return {'passed':False,'errors':['insufficient_actual_samples'],'samples':len(wanted)}
    first=wanted[0];origin=first['actual_observation']['position_m'];times=[r['sim_time'] for r in wanted]
    if any(not math.isfinite(t) for t in times) or any(abs(b-a-1/30)>1e-5 for a,b in zip(times,times[1:])):errors.append('noncontinuous_simulation_samples')
    if any(b['source_tick']-a['source_tick']!=1 for a,b in zip(wanted,wanted[1:])):errors.append('noncontinuous_source_ticks')
    if times[-1]-times[0]<duration_s-.1:errors.append('requested_wait_duration_not_observed')
    if task.get('status')!='succeeded':errors.append('native_wait_activity_not_succeeded')
    if any(r['actor_instance_id']!=task['actor_instance_id'] for r in wanted):errors.append('actor_instance_changed')
    if not joint_paths or len(set(joint_paths))!=len(joint_paths) or any(r['joint_paths']!=joint_paths or len(r['world_pose'])!=len(joint_paths) for r in wanted):errors.append('actual_joint_layout_changed_or_truncated')
    if any(len(p)!=7 or not all(math.isfinite(v) for v in p) for r in wanted for p in r['world_pose']):errors.append('nonfinite_or_malformed_joint_pose')
    if any(r['actual_observation'].get('position_source')!='BehaviorAgent.get_world_translation' for r in wanted):errors.append('not_actual_sdk_roots')
    if any(r['actual_observation'].get('action')!='Idle' for r in wanted):errors.append('non_idle_action_in_wait')
    interlopers=[r for r in rows if r['actor_id']==task['actor_id'] and times[0]<=r['sim_time']<=times[-1] and r['activity_task_id']!=task['task_id']]
    if interlopers:errors.append('different_task_inside_measurement_window')
    drift=[math.dist(origin[:2],r['actual_observation']['position_m'][:2]) for r in wanted]
    speeds=[r['actual_observation']['planar_speed_mps'] if 'planar_speed_mps' in r['actual_observation'] else r['actual_observation']['speed_mps'] for r in wanted]
    if not all(math.isfinite(v) for v in drift+speeds):errors.append('nonfinite_root_or_speed')
    i=max(range(len(drift)),key=drift.__getitem__);j=max(range(len(speeds)),key=speeds.__getitem__)
    max_drift=drift[i];max_speed=speeds[j]
    return {'passed':not errors and max_drift<=.15 and max_speed<.15,'valid_measurement':not errors,'errors':errors,'samples':len(wanted),'all_actual_joints':len(joint_paths),
            'observed_duration_s':times[-1]-times[0],'start_sim_time':times[0],'end_sim_time':times[-1],
            'max_planar_root_displacement_m':max_drift,'max_planar_speed_mps':max_speed,
            'worst_displacement_sample':{'source_tick':wanted[i]['source_tick'],'sim_time':times[i],'position_m':wanted[i]['actual_observation']['position_m']},
            'worst_speed_sample':{'source_tick':wanted[j]['source_tick'],'sim_time':times[j]},
            'observed_native_task_ids':sorted({r['actual_observation']['native_task_id'] for r in wanted}),
            'scope':'Full measured wait relative to its first SDK root; .15m/.15mps screens retained separately from full motion/contact quality.'}


def audit(directory):
    directory=Path(directory);read=lambda n:json.loads((directory/n).read_text())
    if not (directory/'completed.json').is_file() or not (directory/'generated_native_acceptance.json').is_file():return {'passed':False,'measurement_closed':False,'reason':'NATIVE_RUN_NOT_CLOSED'}
    config=read('probe_config.json');acceptance=read('generated_native_acceptance.json');phases=[p for p in acceptance['phases'] if p['name']=='idle_context']
    if len(phases)!=1:return {'passed':False,'measurement_closed':True,'reason':'EXACT_OWNED_IDLE_PHASE_NOT_FOUND'}
    rows=[json.loads(l) for l in (directory/'native_pose_history.jsonl').open()];duration=config.get('diagnostic_idle_duration',2)
    result={t['actor_id']:evaluate(rows,t,acceptance['joint_layouts'][t['actor_id']],duration) for t in phases[0]['tasks']}
    events=list(map(json.loads,(directory/'events.jsonl').open()))
    fences={};fence_errors=[]
    for task in phases[0]['tasks']:
        aid=task['actor_id'];bound={}
        for kind,key in [('task_accepted','accepted'),('task_ended','ended')]:
            matches=[e for e in events if e['kind']==kind and e.get('task',{}).get('task_id')==task['task_id']]
            if len(matches)!=1 or matches[0]['task'].get('actor_instance_id')!=task['actor_instance_id']:
                fence_errors.append({'actor_id':aid,'reason':'exact_wait_event_fence_missing','kind':kind});continue
            bound[key]=matches[0]
        if len(bound)!=2:continue
        start,end=bound['accepted'],bound['ended'];measurement=result[aid]
        if start['cursor']>=end['cursor'] or start['sim_time']>measurement.get('start_sim_time',-float('inf'))+1e-7 or end['sim_time']<measurement.get('end_sim_time',float('inf'))-1e-7:
            fence_errors.append({'actor_id':aid,'reason':'wait_event_clock_or_order_mismatch'});continue
        fences[aid]={'accepted_cursor':start['cursor'],'ended_cursor':end['cursor'],'accepted_sim_time':start['sim_time'],'ended_sim_time':end['sim_time']}
    writes=[];global_methods={'batch','reset','populate','pause','resume','control_session','signal_event','move_prop'}
    methods=global_methods|{'run_activity','move_to','perform','cancel','despawn'}
    task_ids={t['actor_id']:t['task_id'] for t in phases[0]['tasks']}
    for event in events:
        params=event.get('params',{})
        if event['kind']=='tool_call' and event.get('method') in methods:
            for actor,value in result.items():
                fence=fences.get(actor,{})
                if fence.get('accepted_cursor',float('inf'))<event['cursor']<fence.get('ended_cursor',-float('inf')) and (params.get('actor_id')==actor or params.get('task_id')==task_ids[actor] or event['method'] in global_methods):writes.append({'actor_id':actor,'cursor':event['cursor'],'method':event['method']})
    names=['probe_config.json','source_manifest.json','native_pose_history.jsonl','events.jsonl','generated_native_acceptance.json','completed.json']
    return {'run_id':directory.name,'measurement_closed':True,'passed':acceptance['passed'] and bool(result) and not fence_errors and not writes and all(v['passed'] for v in result.values()),
            'native_lifecycle_passed':acceptance['passed'],'actors':result,'new_control_requests_during_measured_wait':writes,
            'wait_event_fences':fences,'wait_event_fence_errors':fence_errors,
            'sdk_idle_settings':read('sdk_idle_settings.json') if (directory/'sdk_idle_settings.json').exists() else None,
            'inputs_sha256':{n:hashlib.sha256((directory/n).read_bytes()).hexdigest() for n in names},
            'scope':'Closed native wait/control/clock/root screening, not an exact industrial c13 replay or foot/mesh/contact certification. Initial and terminal samples remain included. Event cursors separate post-completion requests sharing the final simulation timestamp.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('--output',required=True);args=parser.parse_args()
    result=audit(args.directory);Path(args.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 2)
