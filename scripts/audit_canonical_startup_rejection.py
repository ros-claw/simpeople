"""Independent actual-body audit of startup rejection; no Kit/controller import."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from audit_canonical_heading_rejection import review_rejection, FENCES


def review(rows, reference, receipt):
    result=review_rejection(rows,reference,receipt,expected_facing_y=1)
    errors=list(result['errors']);domain=reference['native_startup_conditions']
    before=receipt['startup_settings_before'];bad=receipt['startup_settings_bad'];restored=receipt['startup_settings_restored']
    for label,value in [('domain',domain),('supported settings',before),('changed settings',bad)]:
        for key in ['response_time_s','response_random_offset_s','nav_blocked_timeout_s']:
            n=value.get(key)
            if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n):
                return {'verified':False,'errors':[*errors,'invalid numeric startup '+label+': '+key]}
    if (domain.get('schema_version')!='simpeople.native-motion-startup.v1' or domain.get('idle_tags')!=['Idle']
        or domain.get('response_random_offset_s')!=0 or domain.get('nav_blocked_timeout_s')!=3
        or abs(domain.get('response_time_s',0)-1/30)>1e-12 or domain.get('api_seed')!=42):
        errors.append('short probe lacks its explicit tested startup domain')
    required={'idle_tags','response_time_s','response_random_offset_s','nav_blocked_timeout_s','seed_configuration'}
    if set(before)!=required or set(bad)!=required or before!=restored:
        errors.append('startup settings absent, changed silently or not restored')
    seed=before.get('seed_configuration')
    if (not isinstance(seed,dict) or seed!={'api_seed':42,'configured_before_agents':True,'configured_on_owner_thread':True}
        or seed.get('configured_before_agents') is not True or seed.get('configured_on_owner_thread') is not True):
        errors.append('owned pre-birth main-thread seed receipt absent')
    if (before.get('idle_tags')!=['Idle'] or before.get('response_random_offset_s')!=0
        or before.get('nav_blocked_timeout_s')!=3
        or abs(before.get('response_time_s',0)-1/30)>1e-8
        or {k:v for k,v in bad.items() if k!='response_random_offset_s'}!={k:v for k,v in before.items() if k!='response_random_offset_s'}
        or not isinstance(bad.get('response_random_offset_s'),(int,float))
        or isinstance(bad.get('response_random_offset_s'),bool)
        or not math.isfinite(bad['response_random_offset_s'])
        or abs(bad['response_random_offset_s']-.01)>1e-8):
        errors.append('counterfactual did not change only actual response jitter from zero to .01')
    diagnostic=receipt['error'].get('details',{}).get('startup_error',{})
    if (diagnostic.get('passed') is not False or diagnostic.get('observed_settings')!=bad
        or diagnostic.get('required_domain')!=domain
        or diagnostic.get('errors')!=['native setting outside declared startup domain: response_random_offset_s']):
        errors.append('refusal not specifically caused by observed startup mismatch')
    samples=[r for r in rows if r['actor_id']==receipt['actor_id']
             and receipt['sim_time']-.1-1e-7<=r['sim_time']<=receipt['sim_time']+1e-7]
    angles=[]
    for r in samples:
        f=r['actual_observation']['facing_direction'];norm=math.sqrt(sum(x*x for x in f))
        angle=math.degrees(math.acos(max(-1,min(1,f[1]/norm)))) if norm else float('inf');angles.append(angle)
        if angle>.2+1e-7:errors.append('valid supported +Y entry not demonstrated before startup refusal')
    precondition=receipt.get('supported_entry_quality',{})
    if not precondition.get('passed') or not precondition.get('native_entry_domain',{}).get('passed'):
        errors.append('actual adapter did not first accept the same body/heading at supported startup')
    return {'verified':not errors,'errors':errors,'owned_body_readback':result,
            'actual_entry_max_heading_error_deg':max(angles,default=None),
            'changed_setting':'response_random_offset_s','supported_value':0,'unsupported_value':bad.get('response_random_offset_s')}


def audit(folder):
    folder=Path(folder);read=lambda n:json.loads((folder/n).read_text());errors=[]
    for n,h in read('source_manifest.json').items():
        p=folder/'source_snapshot'/n
        if not p.resolve().is_relative_to((folder/'source_snapshot').resolve()) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=h:
            errors.append('frozen source changed: '+n)
    receipt=read('unsupported_startup_rejection.json');registry=read('source_snapshot/inputs/actions.json');reference=registry['actions'][receipt['clip']]['canonical_entry']
    rows=[json.loads(l) for l in (folder/'native_pose_history.jsonl').open()];result=review(rows,reference,receipt);errors+=result['errors']
    tasks={t['task_id']:t for t in read('tasks.json')};w=receipt['witness_before'];end=receipt['witness_after_hold'];wt=tasks[w['task_id']]
    if (any(w.get(k)!=end.get(k) for k in FENCES) or w['status'] not in {'running','blocked'}
        or end['status'] not in {'running','blocked'} or wt['status']!='succeeded'):
        errors.append('independent witness not active through refusal and subsequently successful')
    roots=[]
    for raw in (folder/'trajectories.jsonl').open():
        r=json.loads(raw)
        if receipt['sim_time']-1e-7<=r['sim_time']<=receipt['after_hold_sim_time']+1e-7 and r['actor_id']==w['actor_id'] and all(r.get(k)==w.get(k) for k in FENCES):roots.append(r)
    if len(roots)<31 or max((math.dist(roots[0]['position_m'],r['position_m']) for r in roots),default=0)<=.3:
        errors.append('actual moving witness during the one-second refusal hold absent')
    if any(t.get('request_id')=='unsupported_startup_generated' for t in tasks.values()):errors.append('rejected request created a logical task')
    phases=read('generated_native_acceptance.json')['phases'];walk=next((p for p in phases if p['name']=='walk_after_startup_rejection'),None)
    if not walk or any(t['status']!='succeeded' for t in walk['tasks']):errors.append('ordinary walking after startup refusal failed')
    if read('native_seed_configuration.json')!=receipt['startup_settings_before']['seed_configuration']:
        errors.append('seed declaration does not match frozen pre-birth SDK configuration receipt')
    entry=read('custom_actions/registry.json')[receipt['clip']]
    if entry['source_sha256'].get('startup_contract')!=hashlib.sha256((folder/'source_snapshot/src/simpeople/motion/startup.py').read_bytes()).hexdigest():
        errors.append('registered action not bound to the startup contract code hash')
    clock={}
    for raw in (folder/'video_timestamps.jsonl').open():
        r=json.loads(raw)
        if any(abs(r['sim_time']-t)<1e-7 for t in [receipt['sim_time'],receipt['after_hold_sim_time']]):clock[r['sim_time']]=r['frame']
    if len(clock)!=2:errors.append('startup readbacks lack same-simulation-time RGB indices')
    completed=read('completed.json');capture=read('recording_metrics.json')
    if not completed['harness_completed'] or capture['frames_written']!=completed['frames'] or capture['empty_rgb_frames'] or capture['dropped_frames']:
        errors.append('native closure or continuous CPU RGB incomplete')
    return {'run_id':folder.name,'method_version':'simpeople.canonical-startup-rejection.v1',
            'startup_refusal_verified':not errors,'errors':errors,'readback':result,'actual_sim_time_to_rgb':clock,
            'positive_motion_scope':'not_tested_in_this_short_probe','production_source_installed':False,
            'qualified_generated_native_rigs':[],
            'scope':'Same actual valid +Y body, only live jitter setting changed before request; old task/world/SDK preserved, setting restored, one second actual Idle and moving witness, subsequent walk. Seed provenance records SDK configuration, not a seed getter or deterministic execution.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);args=p.parse_args();target=Path(args.output)
    if target.exists():raise FileExistsError('preserve previous grade')
    result=audit(args.run);target.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['startup_refusal_verified'] else 1)
