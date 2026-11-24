"""Actual SDK wait admission after a cancelled yield; no Kit/controller imports."""
import argparse
import json
import math
from pathlib import Path
from audit_local_yield import FENCES, footprint, review_admission
from audit_local_yield_faults import stop_window
from audit_local_yield_replacement import audit as audit_replacement


def review(start, phases, motions, fault, events, rows, roots_at, tasks, spec, expected):
    errors=[];old=tasks[start['task_id']]
    admission=review_admission(start,phases,roots_at,old,spec);errors+=admission['errors']
    if 'cells' not in admission:return {'verified':False,'errors':errors}
    cells=admission['cells'];body=admission['body'];rid=start['route_id'];time=fault['sim_time']
    normalized=[{**s,**({'gait':s.get('gait','walk')} if s['action']=='move_to' else {})} for s in spec['steps']]
    if old.get('steps')!=normalized:errors.append('old request was changed')
    proof=fault.get('trigger_evidence') or {};current=proof.get('current',{});release_proof=proof.get('release',{})
    first=motions[0] if motions else None
    if (first is None or first['cursor']>=fault['cursor'] or not -1e-7<=time-first['sim_time']<=1/30+1e-6
        or proof.get('kind')!='native_local_yield_motion' or fault.get('method')!='run_activity'
        or fault.get('resolved_params')!=expected['params']
        or release_proof.get('route_id')!=rid or release_proof.get('native_task_id')!=start['native_task_id']
        or abs(release_proof.get('observed_sim_time',-1)-(first or {}).get('sim_time',-2))>1e-7
        or any(current.get(k)!=start.get(k) or release_proof.get('fences',{}).get(k)!=start.get(k) for k in FENCES)
        or current.get('sdk_task_id')!=start['native_task_id'] or current.get('body_instance_id')!=body):
        errors.append('wait replacement not bound to first actual owned yield motion')
    if (old.get('status')!='cancelled' or old.get('physical_stop_verified') is not False
        or old.get('error',{}).get('message')!='superseded' or abs(old.get('finished_sim_time',-1)-time)>1e-7):
        errors.append('old supersession incorrectly marked physically settled')
    new_id=(fault.get('result') or {}).get('task_id');new=tasks.get(new_id,{})
    requested=expected['params']['steps']
    if (len(requested)!=1 or requested[0].get('action')!='wait' or new_id==start['task_id']
        or new.get('status')!='succeeded' or new.get('steps')!=requested
        or any(new.get(k)!=start.get(k) for k in FENCES if k not in {'task_id','control_epoch'})
        or new.get('control_epoch')!=start['control_epoch']+1):
        return {'verified':False,'errors':[*errors,'new wait identity, step or success invalid']}
    retain=[e for e in events if e['kind']=='traffic_cancelled_yield_claim_retained' and e.get('route_id')==rid]
    releases=[e for e in events if e['kind']=='traffic_cancelled_yield_claim_released' and e.get('route_id')==rid]
    if (len(retain)!=1 or len(releases)!=1 or abs(retain[0]['sim_time']-time)>1e-7
        or any(e.get('body_instance_id')!=body or set(map(tuple,e.get('cells',[])))!=cells for e in retain+releases)):
        return {'verified':False,'errors':[*errors,'whole old claim retention and release absent']}
    release=releases[0];stop=release['sim_time'];window,valid=stop_window(rows,stop,new)
    if not valid:errors.append('sixteen actual Idle stop samples absent')
    bindings=[e for e in events if e['kind']=='native_task_bound' and e.get('task_id')==new_id
              and all(e.get(k)==new.get(k) for k in FENCES)]
    starts=[e for e in events if e['kind']=='step_started' and e.get('task_id')==new_id]
    deferred=[e for e in events if e['kind']=='action_admission_deferred' and e.get('task_id')==new_id]
    if (len(bindings)!=1 or len(starts)!=1 or len(deferred)!=1
        or not isinstance(bindings[0].get('native_task_id'),int) or isinstance(bindings[0].get('native_task_id'),bool)
        or bindings[0].get('backend_task_id')!=bindings[0]['native_task_id']
        or bindings[0]['cursor']<=release['cursor'] or bindings[0]['sim_time']<stop-1e-7
        or starts[0]['cursor']<=bindings[0]['cursor'] or starts[0]['sim_time']<stop-1e-7):
        return {'verified':False,'errors':[*errors,'wait SDK admitted before retained stop or admission evidence absent']}
    begin=starts[0]['sim_time'];finish=new['finished_sim_time'];step=requested[0]
    if (abs(deferred[0]['sim_time']-time)>1/30+1e-6
        or deferred[0].get('blocked_details',{}).get('previous_route_id')!=rid
        or deferred[0].get('blocked_details',{}).get('body_instance_id')!=body
        or abs(deferred[0].get('deadline_sim_time',-1)-(time+step['timeout_s']))>1/30+1e-6
        or finish>deferred[0]['deadline_sim_time']+1e-7
        or not step['duration_s']-1e-7<=finish-begin<=step['duration_s']+1/30+1e-6):
        errors.append('wait duration includes braking or original deadline changed')
    stream=[r for r in rows if start['sim_time']-1e-7<=r['sim_time']<=finish+1e-7]
    if (not stream or abs(stream[0]['sim_time']-start['sim_time'])>1e-7
        or abs(stream[-1]['sim_time']-finish)>1e-7
        or any(abs(b['sim_time']-a['sim_time']-1/30)>1e-6 for a,b in zip(stream,stream[1:]))):
        errors.append('actual body stream discontinuous')
    at=next((r for r in rows if abs(r['sim_time']-time)<1e-7),None)
    if (at is None or first is None or at.get('native_task_id')!=start['native_task_id']
        or math.dist(at['position_m'],current.get('position_m',[]))>1e-5
        or math.dist(at['position_m'],first['actual_position_m'])>1e-5
        or math.dist(at['position_m'][:2],start['points_m'][0][:2])<=.1):errors.append('actual moving old body not witnessed at trigger')
    hold=[r for r in stream if r['sim_time']>=begin-1e-7]
    actual_wait=[r for r in hold if r.get('native_task_id')==bindings[0]['native_task_id']]
    # The tick-start read at the submission instant can still report the last
    # settled Idle. Never relabel it as new SDK evidence or count it in the
    # new task's actual hold duration. Require the new SDK by the next real tick.
    if (not actual_wait or actual_wait[0]['sim_time']>begin+1/30+1e-6
        or abs(actual_wait[-1]['sim_time']-finish)>1e-7
        or finish-actual_wait[0]['sim_time']<step['duration_s']-1e-7):
        errors.append('actual new wait SDK lacks full requested hold duration')
    for r in stream:
        owner=start if r['sim_time']<=time+1e-7 else new
        if (not r.get('ready') or any(r.get(k)!=owner.get(k) for k in FENCES)
            or r.get('traffic_body_instance_id')!=body or r.get('native_actor_prim_path')!=start['agent']):
            errors.append('wait borrowed another body or generation');break
        if r['sim_time']<stop-1e-7:
            if (set(map(tuple,r.get('traffic_claim_cells',[])))!=cells
                or not footprint(r['position_m'],admission['cell'],admission['margin'])<=cells
                or r.get('native_task_id')==bindings[0]['native_task_id']):
                errors.append('old claim released or wait SDK active before actual stop');break
        if r['sim_time']>=begin-1e-7:
            submission_sample=(abs(r['sim_time']-begin)<1e-7 and abs(begin-stop)<1e-7
                and r.get('native_task_id')==window[-2].get('native_task_id'))
            if (r.get('action')!='Idle' or r['speed_mps']>=.15
                or (r.get('native_task_id')!=bindings[0]['native_task_id'] and not submission_sample)
                or math.dist(r['position_m'][:2],window[-1]['position_m'][:2])>.05):
                errors.append('wait hold lacks same owned stationary SDK body');break
    if any(e['kind']=='traffic_native_started' and e.get('route_id')==rid and e['cursor']>fault['cursor'] for e in events):errors.append('old movement resumed')
    if any(e['kind']=='traffic_cancelled_yield_settlement_stale' and e.get('route_id')==rid for e in events):errors.append('old claim changed ownership during settlement')
    return {'verified':not errors,'errors':errors,'old_task_id':start['task_id'],'new_task_id':new_id,
            'fault_sim_time':time,'old_claim_released_sim_time':stop,'actual_stop_samples':len(window),
            'wait_native_submitted_sim_time':begin,
            'wait_sdk_first_observed_sim_time':actual_wait[0]['sim_time'] if actual_wait else None,
            'wait_finished_sim_time':finish,
            'actual_wait_duration_s':finish-actual_wait[0]['sim_time'] if actual_wait else None}


def audit(folder):
    return audit_replacement(folder,reviewer=review,method_version='simpeople.local-yield-wait.v2',
        scope='Actual yield superseded by wait. Entire old claim retained until sixteen stopped samples; new Idle SDK and full wait duration start afterwards. Independent witness. No full release or rig promotion.')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);args=p.parse_args();target=Path(args.output)
    if target.exists():raise FileExistsError('preserve prior grade')
    result=audit(args.run);target.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['qualification_passed'] else 1)
