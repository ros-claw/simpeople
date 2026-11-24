"""Audit yield -> measured stop -> wait -> actual route resume independently.

The first phase uses the existing frozen wait criteria. The second phase reads
real roots/SDK IDs under the third logical owner; acceptance is never arrival.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from audit_local_yield import FENCES
from audit_local_yield_wait import review as review_wait
from audit_local_yield_replacement import KINDS
from audit_local_yield_faults import gate_results


def owned(row, task):
    return all(row.get(k) == task.get(k) for k in FENCES)


def valid_row(row):
    position=row.get('position_m');speed=row.get('speed_mps');time=row.get('sim_time');stamp=row.get('observation_sim_time')
    return (isinstance(position,list) and len(position)==3 and all(type(v) in (float,int) and math.isfinite(v) for v in position)
            and type(speed) in (float,int) and math.isfinite(speed) and speed>=0
            and type(time) in (float,int) and math.isfinite(time)
            and type(stamp) in (float,int) and math.isfinite(stamp) and abs(stamp-time)<=1e-7)


def review_resume(start, wait_fault, resume_fault, events, rows, tasks, expected):
    errors=[]
    try:
        wait=tasks[wait_fault['result']['task_id']];new=tasks[resume_fault['result']['task_id']]
        proof=resume_fault.get('trigger_evidence',{});current=proof.get('current',{});receipt=proof.get('predecessor_receipt',{})
        time=resume_fault['sim_time'];resolved=json.loads(json.dumps(expected['params']))
        via_mode=expected.get('trigger',{}).get('resume_via');continuation=proof.get('continuation')
        if via_mode is not None:
            endpoint=start['points_m'][-1]
            if (via_mode!='observed_yield_exit' or not isinstance(continuation,dict)
                    or continuation.get('kind')!='observed_yield_exit'
                    or continuation.get('source_yield_path_m')!=start['points_m']
                    or continuation.get('source_yield_native_task_id')!=start['native_task_id']
                    or continuation.get('source_body_instance_id')!=start['body_instance_id']
                    or continuation.get('via')!=[endpoint]):
                errors.append('resume waypoint did not come from the original actual yield path')
            resolved['steps'][0]['via']=[endpoint]
        elif continuation is not None:errors.append('undeclared continuation waypoint added')
        requested=resolved['steps']
        if (resume_fault['method']!='run_activity' or resume_fault['resolved_params']!=resolved
                or proof.get('kind')!='activity_succeeded' or proof.get('predecessor_event_id')!=wait_fault['event_id']
                or any(receipt.get(k)!=wait.get(k) or current.get(k)!=wait.get(k) for k in FENCES)
                or current.get('task_status')!='succeeded' or current.get('cancel_requested') is not False
                or wait['status']!='succeeded' or wait['finished_sim_time']>time+1e-7
                or current.get('agent')!=start['agent'] or current.get('body_instance_id')!=start['body_instance_id']):
            errors.append('resume not bound to this exact successful wait/body')
        at=next((r for r in rows if abs(r['sim_time']-time)<1e-7),None)
        observation=current.get('actual_observation',{})
        if (at is None or not owned(at,wait) or at.get('native_actor_prim_path')!=start['agent']
                or at.get('traffic_body_instance_id')!=start['body_instance_id'] or not at.get('ready')
                or at.get('action')!='Idle' or at.get('speed_mps',99)>=.15
                or type(at.get('native_task_id')) is not int or current.get('sdk_task_id')!=at.get('native_task_id')
                or observation.get('native_task_id')!=at.get('native_task_id')
                or abs(observation.get('observation_sim_time',-1)-time)>1e-7
                or math.dist(at['position_m'],current.get('position_m',[999]*3))>1e-5):
            errors.append('resume lacks the actual same-tick stationary wait body')
        normalized=[{**s,'gait':s.get('gait','walk')} for s in requested]
        owner_valid=not (len(requested)!=1 or requested[0].get('action')!='move_to' or new.get('steps')!=normalized
                or new['task_id']==wait['task_id']
                or any(new.get(k)!=wait.get(k) for k in FENCES if k not in {'control_epoch','task_id'})
                or new['control_epoch']!=wait['control_epoch']+1
                or abs(new['accepted_sim_time']-time)>1e-7)
        if not owner_valid:
            errors.append('resume did not create the requested new logical owner')
        if new['status']!='succeeded':
            errors.append('resume task did not succeed: '+str(new['status']))
        ended=[e for e in events if e['kind']=='task_ended' and e.get('task',{}).get('task_id')==wait['task_id']]
        if len(ended)!=1 or ended[0]['cursor']>=resume_fault['cursor'] or ended[0]['task']['status']!='succeeded':
            errors.append('wait success was not journaled before resume dispatch')
        steps=[e for e in events if e['kind']=='step_started' and e.get('task_id')==new['task_id']]
        if len(steps)!=1 or steps[0]['cursor']<=resume_fault['cursor']:
            return {'verified':False,'errors':[*errors,'one actual resume step required']}
        step=steps[0];route=step['backend_task_id'];deadline=step['sim_time']+requested[0]['timeout_s']
        if new['finished_sim_time']>deadline+1e-7 or step['step']!=normalized[0]:errors.append('resume exceeded or changed its original step deadline')
        starts=[e for e in events if e['kind']=='traffic_native_started' and e.get('route_id')==route]
        natives={e['native_task_id'] for e in starts if owned(e,new) and e.get('agent',start['agent'])==start['agent'] and type(e.get('native_task_id')) is int}
        if not starts or len(natives)!=len({e['native_task_id'] for e in starts}):errors.append('resume lacks its own actual SDK movement lineage')
        stream=sorted([r for r in rows if time-1e-7<=r['sim_time']<=new['finished_sim_time']+1e-7],key=lambda r:r['sim_time'])
        if (not stream or abs(stream[0]['sim_time']-time)>1e-7
                or abs(stream[-1]['sim_time']-new['finished_sim_time'])>1e-7
                or any(abs(b['sim_time']-a['sim_time']-1/30)>1e-6 for a,b in zip(stream,stream[1:]))):
            errors.append('resume actual body stream is not continuous30Hz')
        for row in stream:
            owner=wait if row['sim_time']<=time+1e-7 else new
            if (not valid_row(row) or not row.get('ready') or not owned(row,owner) or row.get('native_actor_prim_path')!=start['agent']
                    or row.get('traffic_body_instance_id')!=start['body_instance_id']):
                errors.append('resume borrowed another actor/body/generation');break
        moved=[r for r in stream if owned(r,new) and r.get('native_task_id') in natives]
        distance=max((math.dist(at['position_m'][:2],r['position_m'][:2]) for r in moved),default=0) if at else 0
        if distance<=.3:errors.append('resume acceptance did not produce measured SDK movement')
        if any(r.get('speed_mps',0)>=.15 and not r.get('traffic_claim_cells') for r in moved):errors.append('moving resume lost its current reservation')
        end=stream[-1] if stream else {};goal=requested[0]['target']
        if (not owned(end,new) or math.dist(end.get('position_m',[999]*3)[:2],goal[:2])>.3 or end.get('speed_mps',99)>=.15):
            errors.append('resume task terminal does not match actual stopped goal')
        hold=[r for r in stream if r['sim_time']>=new['finished_sim_time']-.5-1e-7]
        hold_valid=not (len(hold)!=16 or not all(valid_row(r) and owned(r,new) and r['speed_mps']<.15
                and math.dist(r['position_m'][:2],goal[:2])<=.3 for r in hold)
                or any(b['sim_time']<=a['sim_time'] or math.dist(a['position_m'][:2],b['position_m'][:2])/(b['sim_time']-a['sim_time'])>=.15 for a,b in zip(hold,hold[1:])))
        if not hold_valid:
            errors.append('actual resumed goal did not remain stopped for16 real samples/0.5s')
        waypoint_distance = None
        if via_mode is not None:
            waypoint_distance=min((math.dist(r['position_m'][:2],endpoint[:2]) for r in moved if valid_row(r)),default=math.inf)
            if waypoint_distance>.3:errors.append('actual SDK body never visited the declared observed yield exit')
        # Old settlement may never clear claims held by this new movement.
        if any(e['kind']=='traffic_cancelled_yield_settlement_stale' and e.get('route_id')==start['route_id'] for e in events):
            errors.append('old cleanup changed body ownership during resume')
        return {'verified':not errors,'errors':errors,'wait_task_id':wait['task_id'],'resume_task_id':new['task_id'],
                'new_owner_identity_verified':owner_valid,'resume_task_status':new['status'],'goal_hold_verified':hold_valid,
                'wait_finished_sim_time':wait['finished_sim_time'],'resume_dispatched_sim_time':time,
                'resume_step_started_sim_time':step['sim_time'],'original_deadline_sim_time':deadline,
                'resume_finished_sim_time':new['finished_sim_time'],'max_actual_resume_displacement_m':distance,
                'resume_native_task_ids':sorted(natives),'actual_goal_hold_samples':len(hold),'observed_exit_visit_error_m':waypoint_distance if waypoint_distance is None or math.isfinite(waypoint_distance) else None}
    except (KeyError,ValueError,TypeError,IndexError) as error:
        return {'verified':False,'errors':[*errors,str(error)]}


def audit(folder):
    folder=Path(folder);read=lambda n:json.loads((folder/n).read_text());errors=[]
    if not read('completed.json')['harness_completed']:raise ValueError('native harness did not close')
    for n,h in read('source_manifest.json').items():
        p=folder/'source_snapshot'/n
        if not p.resolve().is_relative_to((folder/'source_snapshot').resolve()) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:errors.append('frozen input changed: '+n)
    cutoff=read('benchmark_done.json')['event_cursor'];events=[]
    kinds=KINDS|{'task_ended','traffic_wait_budget_exceeded'}
    for raw in (folder/'events.jsonl').open():
        if not any(('"'+k+'"') in raw[:140] for k in kinds):continue
        event=json.loads(raw)
        if event['cursor']<=cutoff:events.append(event)
    starts=[e for e in events if e['kind']=='traffic_native_started' and e.get('action')=='local_yield']
    faults=[e for e in events if e['kind']=='benchmark_fault_applied'];case=read('workload.json');tasks={t['task_id']:t for t in read('tasks.json')}
    if len(starts)!=1 or len(faults)!=2 or len(case['events'])!=2:raise ValueError('one actual yield and two explicit applied faults required; missing scope is unverified')
    if case!=read('source_snapshot/harness/case.json'):errors.append('runtime workload differs from frozen diagnostic case')
    start=starts[0];wait_fault,resume_fault=sorted(faults,key=lambda e:e['cursor']);expected_wait,expected_resume=case['events']
    if wait_fault['event_id']!=expected_wait['event_id'] or resume_fault['event_id']!=expected_resume['event_id']:errors.append('diagnostic event order changed')
    snaps=[e for e in events if e['kind']=='traffic_local_yield_snapshot' and e['route_id']==start['route_id']];times={round(e['sim_time'],7) for e in snaps};roots_at={t:{} for t in times};rows=[];witness_rows=[]
    w=wait_fault['trigger_evidence']['current']['witness'];witness=tasks[w['task_id']]
    for raw in (folder/'trajectories.jsonl').open():
        row=json.loads(raw);time=round(row['sim_time'],7)
        if time in roots_at:roots_at[time][row['actor_id']]=row
        if row['actor_id']==start['actor_id']:rows.append(row)
        if row['actor_id']==w['actor_id'] and row['sim_time']>=wait_fault['sim_time']-1e-7 and owned(row,witness):witness_rows.append(row)
    outcome=next(r for r in read('outcomes.json')['requests'] if r.get('task_id')==start['task_id']);spec=next(r for r in case['requests'] if r['request_case_id']==outcome['request_case_id'])
    wait=review_wait(start,{e['phase']:e for e in snaps},[e for e in events if e['kind']=='traffic_local_yield_motion_observed' and e['route_id']==start['route_id']],wait_fault,events,rows,roots_at,tasks,spec,expected_wait)
    resume=review_resume(start,wait_fault,resume_fault,events,rows,tasks,expected_resume)
    later=resume_fault['trigger_evidence']['current'].get('witness',{})
    if (any(later.get(k)!=w.get(k) for k in ['actor_id','actor_instance_id','task_id','control_epoch'])
            or witness['status']!='succeeded' or w['status'] not in {'running','blocked'} or later.get('status') not in {'running','blocked'}
            or not witness['started_sim_time']<=wait_fault['sim_time']<=resume_fault['sim_time']<witness['finished_sim_time']
            or not witness_rows or abs(witness_rows[0]['sim_time']-wait_fault['sim_time'])>1e-7
            or max(math.dist(witness_rows[0]['position_m'],r['position_m']) for r in witness_rows)<=.3):errors.append('same independent witness did not remain active, moving and successful')
    capture=read('recording_metrics.json');done=read('completed.json');geometry=read('acceptance_summary.json')['trajectory_proxies'];runtime=read('runtime_audit.json')
    if capture['frames_written']!=done['frames'] or capture['empty_rgb_frames'] or capture['dropped_frames'] or not (folder/'raw_video.mp4').is_file():errors.append('continuous RGB incomplete')
    if geometry['sustained_overlap_segments'] or geometry['root_discontinuities']:errors.append('root geometry regression')
    key_times={wait_fault['sim_time'],tasks[wait_fault['result']['task_id']]['finished_sim_time'],
               resume_fault['sim_time'],tasks[resume_fault['result']['task_id']]['finished_sim_time']-.5,
               tasks[resume_fault['result']['task_id']]['finished_sim_time']}
    rgb={time:[] for time in key_times}
    for raw in (folder/'video_timestamps.jsonl').open():
        frame=json.loads(raw)
        for time in key_times:
            if abs(frame['sim_time']-time)<=1e-7:rgb[time].append(frame)
    for time,frames in rgb.items():
        row=next((r for r in rows if abs(r['sim_time']-time)<=1e-7),None)
        if (len(frames)!=1 or row is None or frames[0].get('frame_identity')!=row.get('frame_identity')
                or not isinstance(frames[0].get('frame_identity'),dict)
                or type(frames[0].get('frame')) is not int
                or frames[0]['frame_identity'].get('source_tick')!=frames[0].get('frame')):
            errors.append('critical wait/resume/goal readback lacks its matching RGB source frame')
    actual_wait_violations=sum(e['kind']=='traffic_wait_budget_exceeded' for e in events)
    if actual_wait_violations!=runtime['wait_budget_violations']:errors.append('derived wait count differs from actual journal')
    waits=['fair waiting budget violation'] if actual_wait_violations else []
    return {'run_id':folder.name,'method_version':'simpeople.local-yield-wait-resume.v1',**gate_results([wait,resume],errors,waits),
            'errors':errors+waits+['wait: '+e for e in wait['errors']]+['resume: '+e for e in resume['errors']],'wait':wait,'resume':resume,'waiting_budget_violations':actual_wait_violations,
            'critical_sim_to_rgb':{str(t):v[0]['frame'] for t,v in rgb.items() if len(v)==1},
            'inputs_sha256':{n:hashlib.sha256((folder/n).read_bytes()).hexdigest() for n in ['source_manifest.json','workload.json','events.jsonl','trajectories.jsonl','tasks.json','outcomes.json','completed.json','recording_metrics.json','video_timestamps.jsonl','runtime_audit.json','acceptance_summary.json']},
            'runtime_outcome_counts':runtime['outcome_counts'],'full_release_passed':False,'production_source_installed':False,
            'scope':'New diagnostic90s yield->whole retained claim/16stopped samples->full actual wait->exact wait success->samebody native movement to goal. OriginalAX failure retained; no whole release, generated rig, or production qualification.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);args=p.parse_args();out=Path(args.output)
    if out.exists():raise FileExistsError('preserve previous grade')
    try:result=audit(args.run)
    except (OSError,ValueError,KeyError,TypeError,IndexError) as error:result={'qualification_passed':False,'errors':[str(error)],'full_release_passed':False,'production_source_installed':False}
    out.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps(result,indent=2));raise SystemExit(0 if result['qualification_passed'] else 1)
