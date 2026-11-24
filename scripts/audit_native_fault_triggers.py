"""Independent evidence review of event-bound native fault experiments.

Reads real journal/SDK rows; never imports the trigger implementation or Kit.
The frozen diagonal root/cell auditor remains a separate mandatory gate.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def audit(folder):
    folder=Path(folder);read=lambda name:json.loads((folder/name).read_text())
    completed=read('completed.json');case=read('workload.json');cutoff=read('benchmark_done.json')['event_cursor']
    errors=[]
    if not completed['harness_completed'] or not completed['functional_expected_matched']:
        errors.append('native functional closure missing')
    if read('bootstrap.json').get('diagnostic_native_release_triggers') is not True:
        errors.append('explicit diagnostic driver not used')
    for name,digest in read('source_manifest.json').items():
        relative=Path(name);source=folder/'source_snapshot'/relative
        if relative.is_absolute() or '..' in relative.parts or not source.is_file() or not source.resolve().is_relative_to((folder/'source_snapshot').resolve()):
            errors.append('invalid frozen source path: '+name);continue
        if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
            errors.append('changed frozen source: '+name)
    events=[]
    for line in (folder/'events.jsonl').open():
        if b'"kind": "tool_result"' in line[:140].encode():continue
        e=json.loads(line)
        if e['cursor']<=cutoff:events.append(e)
    cell=next(e['cell_m'] for e in events if e['kind']=='traffic_grid_ready')
    tracks={(e['route_id'],e['native_task_id']):e for e in events if e['kind']=='traffic_tail_tracking'
            and e.get('eligible') is True and e.get('diagonal_straight_enabled') is True
            and all(round(e['points_m'][0][i]/cell)!=round(e['points_m'][-1][i]/cell) for i in [0,1])}
    faults=[e for e in events if e['kind']=='benchmark_fault_applied']
    expected={e['event_id']:e for e in case['events']};by_id={e['event_id']:e for e in faults}
    if set(by_id)!=set(expected) or len(faults)!=len(expected):errors.append('missing or duplicate actual fault')
    tasks={t['task_id']:t for t in read('tasks.json')};wanted={};reviews=[];cancel_epochs={}
    for event_id,spec in expected.items():
        e=by_id.get(event_id)
        if e is None:continue
        trigger=spec['trigger'];proof=e.get('trigger_evidence') or {}
        if e.get('method')!=spec['method']:errors.append(event_id+': fault operation mismatch')
        if proof.get('kind')!=trigger['kind']:
            errors.append(event_id+': wrong trigger kind');continue
        if trigger['kind']=='event_applied':
            earlier=by_id.get(trigger['event_id']);delta=e['sim_time']-earlier['sim_time'] if earlier else None
            if delta is None or not trigger['delay_s']-1e-6<=delta<=trigger['delay_s']+1/30+1e-6:
                errors.append(event_id+': clear delay not measured from actual entry')
            params=spec['params']
            moved=[r for r in events if r['kind']=='prop_moved' and r['prop_id']==params.get('prop_id')
                   and abs(r['sim_time']-e['sim_time'])<1e-7 and math.dist(r['position_m'],params['position_m'])<1e-6] if 'position_m' in params else []
            if spec['method']!='move_prop' or e.get('resolved_params')!=params or not moved:
                errors.append(event_id+': actual prop clearing not observed')
            continue
        release=proof['release'];current=proof['current'];fences=release['fences'];actor=trigger['actor_id']
        candidates=[r for r in events if r['kind']=='traffic_tail_released'
                    and (r['route_id'],r['native_task_id']) in tracks and r.get('actor_id')==actor]
        first=min(candidates,key=lambda r:r['cursor']) if candidates else None
        if first is None:
            errors.append(event_id+': no actual diagonal release');continue
        if (first['cursor']>=e['cursor'] or not -1e-7<=e['sim_time']-first['sim_time']<=1/30+1e-6
                or abs(first['sim_time']-release['observed_sim_time'])>1e-7
                or (release['route_id'],release['native_task_id'])!=(first['route_id'],first['native_task_id'])):
            errors.append(event_id+': not immediately after the first same diagonal task release')
        if any(e.get(k)!=first.get(k) for k in ['session_id','episode_id']):
            errors.append(event_id+': fault event world mismatch')
        for key in ['session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id']:
            if fences.get(key) is None or fences[key]!=first.get(key) or current.get(key)!=fences[key]:
                errors.append(event_id+': world/task fence mismatch '+key)
        if (current['agent']!=first['agent'] or current['body_instance_id']!=first['body_instance_id']
                or current['current_route_id']!=first['route_id']
                or current['route_native_task_id']!=first['native_task_id']
                or current['sdk_task_id']!=first['native_task_id']):
            errors.append(event_id+': native route/body/current-task mismatch')
        lead=tasks.get(fences['task_id'],{});witness=current['witness'];w=tasks.get(witness['task_id'],{})
        if not (lead.get('started_sim_time') is not None and lead.get('finished_sim_time') is not None
                and lead['started_sim_time']<=e['sim_time']<lead['finished_sim_time']
                and current.get('task_status') in {'running','blocked'} and current.get('cancel_requested') is False):
            errors.append(event_id+': lead already terminal or cancellation pending')
        active=(w.get('actor_id')==trigger['witness_actor_id'] and w.get('status')=='succeeded'
                and w['started_sim_time']<=e['sim_time']<w['finished_sim_time']
                and witness.get('status') in {'running','blocked'}
                and all(witness.get(k)==w.get(k) for k in ['actor_id','actor_instance_id','task_id','control_epoch']))
        if not active:errors.append(event_id+': witness not independently active and successful')
        if spec['method']=='cancel' and not (lead.get('status')=='cancelled' and lead.get('physical_stop_verified')):
            errors.append(event_id+': cancelled lead not physically settled')
        if spec['method']=='cancel':
            # Cancel intentionally advances the ACTOR's control epoch. The old
            # logical task retains its original epoch for late-result fencing.
            # Bind the stop samples to the actual cancel event, never ignore
            # epochs or require the superseded movement generation to stop.
            cancels=[r for r in events if r['kind']=='cancel_requested'
                     and all(r.get(k)==fences.get(k) for k in ['session_id','episode_id','actor_instance_id','task_id'])
                     and first['cursor']<r['cursor']<e['cursor']
                     and abs(r['sim_time']-e['sim_time'])<1e-7
                     and r.get('control_epoch')==fences['control_epoch']+1]
            if len(cancels)!=1 or lead.get('cancel_sim_time') is None or abs(lead['cancel_sim_time']-e['sim_time'])>1e-7:
                errors.append(event_id+': actual cancellation epoch transition unbound')
            else:cancel_epochs[fences['task_id']]=cancels[0]['control_epoch']
        wanted[(actor,round(e['sim_time'],7))]=(e,current,fences,first['native_task_id'])
        wanted[(trigger['witness_actor_id'],round(e['sim_time'],7))]=(e,witness,w,None)
        if spec['method']=='move_prop':
            points=tracks[(first['route_id'],first['native_task_id'])]['points_m'];a,b=points[0],points[-1]
            length=math.dist(a[:2],b[:2]);unit=[(b[i]-a[i])/length for i in [0,1]]
            root=current['position_m'];progress=sum((root[i]-a[i])*unit[i] for i in [0,1]);p=trigger['placement']
            distance=min(progress+p['forward_m'],length-p['end_margin_m']);point=[a[i]+distance*unit[i] for i in [0,1]]+[p['z_m']]
            actual=e['resolved_params'].get('position_m')
            moved=[r for r in events if r['kind']=='prop_moved' and r['prop_id']==spec['params']['prop_id']
                   and abs(r['sim_time']-e['sim_time'])<1e-7 and math.dist(r['position_m'],point)<1e-6]
            if actual is None or math.dist(actual,point)>1e-6 or not moved or not progress<distance<=length:
                errors.append(event_id+': box not placed once on the observed current path')
            brakes=[r for r in events if r['kind']=='traffic_obstacle_brake' and r.get('route_id')==first['route_id']
                    and r.get('agent')==first['agent'] and e['sim_time']<=r['sim_time']<e['sim_time']+8+1/30]
            box=read('runtime_audit.json').get('dynamic_box_geometry_proxy')
            if not brakes or not box or not box['passed']:errors.append(event_id+': lead braking or root/AABB guard unverified')
        reviews.append({'event_id':event_id,'first_diagonal_release_cursor':first['cursor'],
                        'fault_cursor':e['cursor'],'witness_active_at_fault':active})
    found=set();witness_roots={};stop_rows={}
    for line in (folder/'trajectories.jsonl').open():
        row=json.loads(line);key=(row['actor_id'],round(row['sim_time'],7))
        if key in wanted:
            e,context,fences,sdk_id=wanted[key];found.add(key)
            if (not row.get('ready') or any(row.get(k)!=fences.get(k) for k in ['session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id'])
                    or (sdk_id is not None and row.get('native_task_id')!=sdk_id)):
                errors.append('fault not bound to actual same-tick SDK row: '+str(key))
            if 'position_m' in context and math.dist(row['position_m'],context['position_m'])>1e-5:
                errors.append('trigger current root differs from actual SDK row')
        for e,ctx,fences,sdk_id in wanted.values():
            if sdk_id is None and all(row.get(k)==fences.get(k) for k in ['session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id']) and row['sim_time']>=e['sim_time']:
                witness_roots.setdefault(fences['task_id'],[]).append(row['position_m'])
            if sdk_id is not None:
                expected_epoch=cancel_epochs.get(fences['task_id'],fences['control_epoch'])
                bucket=stop_rows.setdefault(fences['task_id'],[])
                if row.get('control_epoch')==expected_epoch and all(row.get(k)==fences.get(k) for k in ['session_id','episode_id','actor_id','actor_instance_id','task_id']):
                    bucket.append(row)
    if set(wanted)-found:errors.append('same-tick actual SDK fault samples missing')
    for roots in witness_roots.values():
        if not roots or max(math.dist(roots[0],p) for p in roots)<.3:errors.append('witness actual motion after fault missing')
    for task_id,rows in stop_rows.items():
        task=tasks[task_id]
        if task['status']!='cancelled':continue
        end=task['finished_sim_time'];window=[r for r in rows if end-.5-1e-7<=r['sim_time']<=end+1e-7]
        complete=(len(window)>=16 and abs(window[0]['sim_time']-(end-.5))<1e-6 and abs(window[-1]['sim_time']-end)<1e-6
                  and task_id in cancel_epochs and all(r.get('ready') and r.get('action')=='Idle' for r in window))
        if complete:
            for a,b in zip(window,window[1:]):
                dt=b['sim_time']-a['sim_time']
                if abs(dt-1/30)>1e-6 or math.dist(a['position_m'][:2],b['position_m'][:2])/dt>=.15:complete=False;break
        if not complete:errors.append('cancelled lead lacks half-second actual root stop window')
    strong=read('diagonal_review_v2.json')
    runtime=read('runtime_audit.json');geometry=read('acceptance_summary.json')['trajectory_proxies']
    if runtime['wait_budget_violations'] or geometry['sustained_overlap_segments'] or geometry['root_discontinuities']:
        errors.append('runtime wait budget or root geometry regression')
    passed=bool(reviews) and not errors and strong['qualification_passed']
    return {'run_id':folder.name,'method_version':'simpeople.native-fault-trigger-audit.v2','qualification_passed':passed,'errors':errors,'events':reviews,
            'actual_cancel_control_epochs':cancel_epochs,
            'full_release_passed':False,'scope':'Event-trigger timing/current SDK identity, box placement/braking/AABB and active witness only, AND frozen strong diagonal audit. No performance, exact mesh-contact or crowd release certification.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);args=p.parse_args();target=Path(args.output)
    assert not target.exists(),'preserve previous grade';result=audit(args.run);target.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));raise SystemExit(0 if result['qualification_passed'] else 1)
