"""Independent actual-body audit of a new task superseding an ongoing yield."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from audit_local_yield import FENCES, footprint, review_admission
from audit_local_yield_faults import stop_window, gate_results

KINDS={'traffic_native_started','traffic_local_yield_snapshot','traffic_local_yield_motion_observed',
       'traffic_cancelled_yield_claim_retained','traffic_cancelled_yield_claim_released',
       'traffic_cancelled_yield_settlement_stale','benchmark_fault_applied','native_task_bound',
       'step_started','recovery_attempt','traffic_local_yield_ended','action_admission_deferred'}


def review(start, phases, motions, fault, events, rows, roots_at, tasks, spec, expected):
    errors=[];old=tasks[start['task_id']];a=review_admission(start,phases,roots_at,old,spec);errors+=a['errors']
    if 'cells' not in a:return {'verified':False,'errors':errors}
    rid=start['route_id'];body=a['body'];cells=a['cells'];time=fault['sim_time']
    original_steps=[{**s,**({'gait':s.get('gait','walk')} if s['action']=='move_to' else {})} for s in spec['steps']]
    if old.get('steps')!=original_steps:errors.append('supersession changed the old logical request instead of creating a new task')
    attempts=[e for e in events if e['kind']=='recovery_attempt' and e.get('task_id')==start['task_id'] and abs(e['sim_time']-start['sim_time'])<1e-7]
    old_steps=[e for e in events if e['kind']=='step_started' and e.get('task_id')==start['task_id'] and e['sim_time']<=start['sim_time']]
    if len(attempts)!=1 or not old_steps or len(old.get('recovery_attempts',[]))>2:
        errors.append('original authorized recovery budget absent')
    else:
        step=max(old_steps,key=lambda e:e['cursor']);deadline=step['sim_time']+step['step'].get('timeout_s',120)
        if abs(attempts[0]['recovery']['deadline_sim_time']-deadline)>1e-6:
            errors.append('original recovery deadline changed before supersession')
    current=(fault.get('trigger_evidence') or {}).get('current',{});release_proof=(fault.get('trigger_evidence') or {}).get('release',{})
    new_id=(fault.get('result') or {}).get('task_id');new=tasks.get(new_id,{})
    first=motions[0] if motions else None
    if (first is None or first['cursor']>=fault['cursor'] or not -1e-7<=time-first['sim_time']<=1/30+1e-6
        or fault.get('method')!='run_activity' or fault.get('resolved_params')!=expected['params']
        or fault.get('trigger_evidence',{}).get('kind')!='native_local_yield_motion'
        or release_proof.get('route_id')!=rid or release_proof.get('native_task_id')!=start['native_task_id']
        or abs(release_proof.get('observed_sim_time',-1)-first['sim_time'])>1e-7
        or any(current.get(k)!=start.get(k) or release_proof.get('fences',{}).get(k)!=start.get(k) for k in FENCES)
        or current.get('sdk_task_id')!=start['native_task_id'] or current.get('body_instance_id')!=body):
        errors.append('replacement is not immediately bound to the first actual owned yield motion')
    if (old.get('status')!='cancelled' or old.get('physical_stop_verified') is not False
        or old.get('error',{}).get('message')!='superseded' or abs(old.get('finished_sim_time',-1)-time)>1e-7):
        errors.append('old task supersession relabelled as physically settled completion')
    if (not new or new_id==start['task_id'] or new.get('status')!='succeeded'
        or any(new.get(k)!=start.get(k) for k in FENCES if k not in {'control_epoch','task_id'})
        or new.get('control_epoch')!=start['control_epoch']+1
        or new.get('steps')!=[{**expected['params']['steps'][0],'gait':'walk'}]):
        return {'verified':False,'errors':[*errors,'new task identity, requested goal or eventual success invalid']}
    retains=[e for e in events if e['kind']=='traffic_cancelled_yield_claim_retained' and e.get('route_id')==rid]
    releases=[e for e in events if e['kind']=='traffic_cancelled_yield_claim_released' and e.get('route_id')==rid]
    if (len(retains)!=1 or len(releases)!=1 or abs(retains[0]['sim_time']-time)>1e-7
        or any(e.get('body_instance_id')!=body or set(map(tuple,e.get('cells',[])))!=cells for e in retains+releases)):
        return {'verified':False,'errors':[*errors,'old yield whole-claim retention/release evidence absent']}
    release=releases[0];stop=release['sim_time'];window,valid=stop_window(rows,stop,new)
    if not valid:errors.append('new actor generation lacks sixteen actual stopped samples before old claim release')
    bindings=[e for e in events if e['kind']=='native_task_bound' and e.get('task_id')==new_id
              and isinstance(e.get('backend_task_id'),str) and e['backend_task_id'].startswith('route-')
              and e.get('native_task_id') is None and all(e.get(k)==new.get(k) for k in FENCES)]
    if len(bindings)!=1:return {'verified':False,'errors':[*errors,'new logical task not bound to a unique new route']}
    new_route=bindings[0]['backend_task_id'];starts=[e for e in events if e['kind']=='traffic_native_started' and e.get('route_id')==new_route]
    if (not starts or any(e['cursor']<=release['cursor'] or e['sim_time']<stop-1e-7 for e in starts)):
        errors.append('replacement native movement submitted before retained stop or never submitted')
    native_ids={e['native_task_id'] for e in starts}
    if any(e['kind']=='traffic_native_started' and e.get('route_id')==rid and e['cursor']>fault['cursor'] for e in events):
        errors.append('old yield route resumed after supersession')
    if any(e['kind']=='traffic_cancelled_yield_settlement_stale' and e.get('route_id')==rid for e in events):errors.append('old claim ownership changed during settlement')
    observed=[r for r in rows if start['sim_time']-1e-7<=r['sim_time']<=stop+1e-7]
    if (not observed or abs(observed[0]['sim_time']-start['sim_time'])>1e-7 or abs(observed[-1]['sim_time']-stop)>1e-7
        or any(abs(b['sim_time']-a['sim_time']-1/30)>1e-6 for a,b in zip(observed,observed[1:]))):errors.append('actual retained-body stream is discontinuous')
    for r in observed:
        owner=start if r['sim_time']<=time+1e-7 else new
        if (not r.get('ready') or any(r.get(k)!=owner.get(k) for k in FENCES)
            or r.get('traffic_body_instance_id')!=body or r.get('native_actor_prim_path')!=start['agent']):
            errors.append('replacement borrowed a different actual task/epoch/body');break
        if r['sim_time']<stop-1e-7 and set(map(tuple,r.get('traffic_claim_cells',[])))!=cells:
            errors.append('old whole claim freed before the actual replacement stop');break
        if not footprint(r['position_m'],a['cell'],a['margin'])<=cells:errors.append('braking body left its retained claim');break
        if r['sim_time']<stop-1e-7 and r.get('native_task_id') in native_ids:errors.append('replacement SDK action active before physical stop');break
    at=next((r for r in rows if abs(r['sim_time']-time)<1e-7),None)
    if (at is None or at.get('native_task_id')!=start['native_task_id'] or math.dist(at['position_m'],current['position_m'])>1e-5
        or first is not None and (math.dist(at['position_m'],first['actual_position_m'])>1e-5 or math.dist(at['position_m'][:2],start['points_m'][0][:2])<=.1)):
        errors.append('replacement trigger lacks actual measured old SDK motion')
    moved=[r for r in rows if r['sim_time']>=stop-1e-7 and all(r.get(k)==new.get(k) for k in FENCES) and r.get('native_task_id') in native_ids]
    if not moved or max(math.dist(moved[0]['position_m'],r['position_m']) for r in moved)<=.3:errors.append('new native task did not produce measured movement')
    ended=next((r for r in rows if abs(r['sim_time']-new['finished_sim_time'])<1e-7),None);goal=new['steps'][0]['target']
    step_starts=[e for e in events if e['kind']=='step_started' and e.get('task_id')==new_id]
    if (ended is None or any(ended.get(k)!=new.get(k) for k in FENCES) or math.dist(ended['position_m'][:2],goal[:2])>.3
        or ended['speed_mps']>=.15 or len(step_starts)!=1 or new['finished_sim_time']>step_starts[0]['sim_time']+new['steps'][0]['timeout_s']):
        errors.append('new goal success not bound to actual stopped root and original new-step deadline')
    # Once replacement movement owns a corridor, late old cleanup cannot empty it.
    moving_claims=[r for r in moved if r['speed_mps']>=.15]
    if any(not r.get('traffic_claim_cells') for r in moving_claims):errors.append('new moving body lost its replacement claim')
    return {'verified':not errors,'errors':errors,'old_task_id':start['task_id'],'new_task_id':new_id,'new_route_id':new_route,
            'fault_sim_time':time,'old_claim_released_sim_time':stop,'actual_stop_samples':len(window),
            'new_native_started_sim_time':starts[0]['sim_time'] if starts else None,'new_goal_completed_sim_time':new['finished_sim_time']}


def audit(folder, *, reviewer=review, method_version='simpeople.local-yield-replacement.v3',
          scope='Actual local-yield supersession, old claim retained through new-generation stop, new route waits then reaches its new goal, independent witness. No all-crowd or rig promotion.'):
    folder=Path(folder);read=lambda n:json.loads((folder/n).read_text());errors=[]
    if not read('completed.json')['harness_completed']:raise ValueError('native replacement did not close')
    cutoff=read('benchmark_done.json')['event_cursor'];events=[]
    for n,h in read('source_manifest.json').items():
        p=folder/'source_snapshot'/n
        if not p.resolve().is_relative_to((folder/'source_snapshot').resolve()) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:errors.append('frozen source changed: '+n)
    for raw in (folder/'events.jsonl').open():
        if not any(('"'+k+'"') in raw[:140] for k in KINDS):continue
        e=json.loads(raw)
        if e['cursor']<=cutoff:events.append(e)
    starts=[e for e in events if e['kind']=='traffic_native_started' and e.get('action')=='local_yield']
    faults=[e for e in events if e['kind']=='benchmark_fault_applied'];case=read('workload.json');tasks={t['task_id']:t for t in read('tasks.json')}
    if len(starts)!=1 or len(faults)!=1 or len(case['events'])!=1:raise ValueError('one actual yield/replacement required; missing scope is unverified')
    start=starts[0];fault=faults[0];expected=case['events'][0];w=fault['trigger_evidence']['current']['witness'];witness=tasks[w['task_id']]
    snaps=[e for e in events if e['kind']=='traffic_local_yield_snapshot' and e['route_id']==start['route_id']];times={round(e['sim_time'],7) for e in snaps};roots_at={t:{} for t in times};rows=[];wr=[]
    for raw in (folder/'trajectories.jsonl').open():
        r=json.loads(raw);time=round(r['sim_time'],7)
        if time in roots_at:roots_at[time][r['actor_id']]=r
        if r['actor_id']==start['actor_id']:rows.append(r)
        if r['actor_id']==w['actor_id'] and r['sim_time']>=fault['sim_time']-1e-7 and all(r.get(k)==witness.get(k) for k in FENCES):wr.append(r)
    outcome=next(r for r in read('outcomes.json')['requests'] if r.get('task_id')==start['task_id']);spec=next(r for r in case['requests'] if r['request_case_id']==outcome['request_case_id'])
    result=reviewer(start,{e['phase']:e for e in snaps},[e for e in events if e['kind']=='traffic_local_yield_motion_observed' and e['route_id']==start['route_id']],fault,events,rows,roots_at,tasks,spec,expected)
    if (witness['status']!='succeeded' or w['status'] not in {'running','blocked'} or not witness['started_sim_time']<=fault['sim_time']<witness['finished_sim_time']
        or not wr or abs(wr[0]['sim_time']-fault['sim_time'])>1e-7 or max(math.dist(wr[0]['position_m'],r['position_m']) for r in wr)<=.3):errors.append('independent witness not active, moving and successful')
    recording=read('recording_metrics.json');completed=read('completed.json');geometry=read('acceptance_summary.json')['trajectory_proxies'];runtime=read('runtime_audit.json')
    if recording['frames_written']!=completed['frames'] or recording['empty_rgb_frames'] or recording['dropped_frames'] or not (folder/'raw_video.mp4').is_file():errors.append('continuous actual RGB incomplete')
    if geometry['sustained_overlap_segments'] or geometry['root_discontinuities']:errors.append('actual root geometry regression')
    waits=['fair waiting budget violation'] if runtime['wait_budget_violations'] else []
    return {'run_id':folder.name,'method_version':method_version,**gate_results([result],errors,waits),'errors':errors+waits,
            'replacement':result,'waiting_budget_violations':runtime['wait_budget_violations'],'full_release_passed':False,'production_source_installed':False,
            'scope':scope}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);a=p.parse_args();target=Path(a.output)
    if target.exists():raise FileExistsError('preserve prior grade')
    result=audit(a.run);target.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps(result,indent=2));raise SystemExit(0 if result['qualification_passed'] else 1)
