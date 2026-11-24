"""Independent actual-pose audit of an expected canonical heading refusal."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from simpeople.motion.entry import entry_error

FENCES=('session_id','episode_id','actor_instance_id','control_epoch','task_id')


def review_admissions(rows, admissions, tasks, registry):
    errors=[];results=[]
    for admission in admissions:
        for actor,task_id in admission['precondition_task_ids'].items():
            task=tasks[task_id];reference=registry['actions']['canonical_'+actor+'__'+admission['case']]['canonical_entry']
            observed=[r for r in rows if r['actor_id']==actor and r['phase']=='canonical_admission_'+admission['case']
                      and r['task'].get('task_id')==task_id][-4:]
            valid=len(observed)==4;angles=[]
            for r in observed:
                o=r['actual_observation'];f=o['facing_direction'];norm=math.sqrt(sum(v*v for v in f))
                angle=math.degrees(math.acos(max(-1,min(1,f[1]/norm)))) if norm else float('inf');angles.append(angle)
                valid=valid and (o.get('ready') is True and o['action']=='Idle' and o['native_task_id']==task['native_task_id']
                    and all(r['task'].get(k)==task.get(k) and task.get(k) is not None for k in FENCES)
                    and r['task']['status']=='running' and o['speed_mps']<.15 and angle<=.2+1e-7
                    and abs(o['observation_sim_time']-r['sim_time'])<1e-7
                    and entry_error(r['world_pose'],f,reference)['passed'])
            valid=valid and all(abs(b['sim_time']-a['sim_time']-1/30)<1e-7 for a,b in zip(observed,observed[1:]))
            if not valid:errors.append('positive canonical entry lacks four actual owned +Y body samples: '+actor+':'+task_id)
            results.append({'actor_id':actor,'precondition_task_id':task_id,'verified':valid,'actual_samples':len(observed),
                            'max_heading_error_deg':max(angles,default=None),'last_sim_time':observed[-1]['sim_time'] if observed else None})
    if not results:errors.append('positive canonical admissions absent')
    return {'verified':bool(results) and not errors,'errors':errors,'admissions':results}


def review_rejection(rows, reference, receipt, *, expected_facing_y=-1):
    if isinstance(expected_facing_y,bool) or expected_facing_y not in {-1,1}:
        raise ValueError('explicit positive or negative Y readback domain required')
    errors=[];before=receipt['before'];after=receipt['after'];time=receipt['sim_time'];aid=receipt['actor_id']
    actor=[r for r in rows if r['actor_id']==aid]
    samples=[r for r in actor if time-.1-1e-7<=r['sim_time']<=time+1e-7]
    after_hold=[r for r in actor if time-1e-7<=r['sim_time']<=receipt['after_hold_sim_time']+1e-7]
    if (any(before.get(k) is None for k in FENCES) or before!=after or receipt['error']['code']!='MOTION_ENTRY_NOT_READY'
            or receipt['after_hold_task']['status']!='running'
            or any(receipt['after_hold_task'].get(k)!=before.get(k) for k in FENCES)):
        errors.append('rejection mutated the original task/world/actor/control owner')
    if len(samples)!=4 or not after_hold or abs(after_hold[-1]['sim_time']-receipt['after_hold_sim_time'])>1e-7 or after_hold[-1]['sim_time']-time<1-1e-7:
        errors.append('actual four-frame entry or one-second post-rejection readback absent')
    for a,b in zip(after_hold,after_hold[1:]):
        if abs(b['sim_time']-a['sim_time']-1/30)>1e-7:errors.append('post-rejection readback has a gap');break
    for a,b in zip(samples,samples[1:]):
        if abs(b['sim_time']-a['sim_time']-1/30)>1e-7:errors.append('entry readback has a gap');break
    body=[]
    for r in [*samples,*after_hold]:
        obs=r['actual_observation'];task=r['task'];facing=obs['facing_direction']
        if (any(task.get(k)!=before.get(k) for k in FENCES) or r.get('actor_instance_id')!=before['actor_instance_id']
                or task.get('status')!='running' or obs.get('ready') is not True
                or obs.get('native_task_id')!=before['native_task_id'] or obs.get('action')!='Idle'
                or abs(obs.get('observation_sim_time',-1)-r['sim_time'])>1e-7
                or not isinstance(obs.get('speed_mps'),(int,float)) or isinstance(obs['speed_mps'],bool) or not math.isfinite(obs['speed_mps']) or not 0<=obs['speed_mps']<.15
                or len(facing)!=3 or any(not math.isfinite(v) for v in facing)
                or abs(math.sqrt(sum(v*v for v in facing))-1)>.001 or facing[1]*expected_facing_y<=.99):
            errors.append('required heading was not a still-owned actual Idle');break
    for r in samples:
        q=entry_error(r['world_pose'],r['actual_observation']['facing_direction'],reference);body.append(q)
        if not q['passed']:errors.append('body-frame entry itself invalid; heading-specific refusal unproven')
    if samples and (samples[-1]['source_tick']!=receipt['source_tick'] or samples[-1]['actual_observation']!=receipt['actual_observation']):
        errors.append('refusal receipt not bound to the actual sampled entry')
    return {'verified':not errors,'errors':errors,'actual_entry_samples':len(samples),'actual_post_rejection_samples':len(after_hold),
            'body_frame_quality':body,'observed_native_task_id':before['native_task_id']}


def audit(folder, *, negative_only=False):
    folder=Path(folder);read=lambda n:json.loads((folder/n).read_text());errors=[]
    for n,h in read('source_manifest.json').items():
        p=folder/'source_snapshot'/n
        if not p.resolve().is_relative_to((folder/'source_snapshot').resolve()) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:errors.append('frozen source changed: '+n)
    receipt=read('unsupported_heading_rejection.json');registry=read('source_snapshot/inputs/actions.json');reference=registry['actions'][receipt['clip']]['canonical_entry']
    if reference.get('native_entry_domain')!={'world_facing_direction':[0,1,0],'max_angle_deg':.2,'stable_frames':4,'sample_rate':30,'base_action':'Idle'}:
        errors.append('declared supported domain changed from this frozen +Y/0.2deg/four-frame screen')
    rows=[json.loads(l) for l in (folder/'native_pose_history.jsonl').open()]
    review=review_rejection(rows,reference,receipt);errors.extend(review['errors'])
    tasks={t['task_id']:t for t in read('tasks.json')};w=receipt['witness_before'];end=receipt['witness_after_hold'];wt=tasks[w['task_id']]
    admissions=({'verified':False,'errors':[],'admissions':[]} if negative_only else
                review_admissions(rows,read('canonical_admissions.json'),tasks,registry))
    errors.extend(admissions['errors'])
    if any(t.get('request_id')=='unsupported_heading_generated' for t in tasks.values()):
        errors.append('rejected generated request nevertheless created a logical task')
    if any(w.get(k)!=end.get(k) for k in FENCES) or w['status'] not in {'running','blocked'} or end['status'] not in {'running','blocked'} or wt['status']!='succeeded':
        errors.append('independent witness was not active and ultimately successful')
    roots=[]
    for raw in (folder/'trajectories.jsonl').open():
        r=json.loads(raw)
        if receipt['sim_time']-1e-7<=r['sim_time']<=receipt['after_hold_sim_time']+1e-7 and r['actor_id']==w['actor_id'] and all(r.get(k)==w.get(k) for k in FENCES):roots.append(r)
    if len(roots)<31 or max((math.dist(roots[0]['position_m'],r['position_m']) for r in roots),default=0)<=.3:errors.append('witness actual motion during refusal unverified')
    phases=read('generated_native_acceptance.json')['phases']
    walk=next((p for p in phases if p['name']=='walk_after_heading_rejection'),None)
    if not walk or any(t['status']!='succeeded' for t in walk['tasks']):errors.append('ordinary native walking did not recover after refusal')
    clock={}
    for raw in (folder/'video_timestamps.jsonl').open():
        r=json.loads(raw)
        if any(abs(r['sim_time']-t)<1e-7 for t in [receipt['sim_time'],receipt['after_hold_sim_time']]):clock[r['sim_time']]=r['frame']
    if len(clock)!=2:errors.append('rejection readbacks lack same-sim-time RGB indices')
    if not read('completed.json')['harness_completed']:errors.append('native harness did not close')
    return {'run_id':folder.name,'method_version':'simpeople.canonical-heading-rejection.v3','expected_rejection_verified':not errors,'errors':errors,
            'negative_only':negative_only,'positive_admission_scope':'not_tested_in_this_short_probe' if negative_only else 'required',
            'canonical_domain_admission_verified':admissions['verified'],'canonical_domain_admissions':admissions['admissions'],
            'readback':review,'actual_sim_time_to_rgb':clock,'qualified_generated_native_rigs':[],'production_source_installed':False,
            'scope':'Same-body valid entry at unsupported -Y is rejected before ownership mutation; original native Idle and witness continue, subsequent native walk succeeds. This is rejection evidence, not generated-motion or rig success.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);p.add_argument('--negative-only',action='store_true');a=p.parse_args();target=Path(a.output)
    if target.exists():raise FileExistsError('preserve previous grade')
    result=audit(a.run,negative_only=a.negative_only);target.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps(result,indent=2));raise SystemExit(0 if result['expected_rejection_verified'] else 1)
