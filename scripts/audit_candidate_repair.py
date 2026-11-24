"""Audit admitted alternatives against actual recorded bodies and route intent."""
import argparse,json,math
from pathlib import Path


def clearance(a,b,p):
    dx,dy=b[0]-a[0],b[1]-a[1];length=dx*dx+dy*dy
    t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length)) if length else 0
    distance=math.hypot(a[0]+t*dx-p[0],a[1]+t*dy-p[1])
    allowed=distance>=.9 or t<=1e-6 and math.dist(b[:2],p[:2])>math.dist(a[:2],p[:2])+.05
    return distance,allowed


def audit(directory):
    folder=Path(directory);done=json.loads((folder/'benchmark_done.json').read_text())
    events=[json.loads(line) for line in (folder/'events.jsonl').open()];events=[e for e in events if e.get('cursor',0)<=done['event_cursor']]
    attempts=[e for e in events if e['kind']=='traffic_candidate_repair'];admitted=[e for e in attempts if e['admitted']]
    goals={e['route_id']:e['goals_m'][-1] for e in events if e['kind']=='traffic_route_started'}
    ages={}
    for e in events:
        if e['kind']=='traffic_guard_scope_changed':ages.setdefault(e['route_id'],e['priority_since_sim_time'])
    wanted={round(e['sim_time'],7) for e in admitted};frames={}
    for line in (folder/'trajectories.jsonl').open():
        row=json.loads(line);key=round(row['sim_time'],7)
        if key in wanted:frames.setdefault(key,{})[row['actor_id']]=row
    errors=[];checks=[]
    for e in admitted:
        frame=frames.get(round(e['sim_time'],7),{});actual=frame.get(e['actor_id']);a,b=e['alternative_candidate_m'];minimum=None
        if actual is None or math.dist(a,actual['position_m'])>1e-5:errors.append({'cursor':e['cursor'],'reason':'actual_root_mismatch'})
        if actual is not None and actual['actor_instance_id']!=e['actor_instance_id']:errors.append({'cursor':e['cursor'],'reason':'actor_generation_mismatch'})
        if e['route_id'] not in goals or math.dist(e['target_m'],goals[e['route_id']])>1e-5:errors.append({'cursor':e['cursor'],'reason':'goal_changed'})
        if e['route_id'] not in ages or abs(e['guard_priority_since_sim_time']-ages[e['route_id']])>1e-7:errors.append({'cursor':e['cursor'],'reason':'fairness_age_changed'})
        starts=[n for n in events if n['cursor']>e['cursor'] and n['kind']=='traffic_native_started' and n['route_id']==e['route_id'] and abs(n['sim_time']-e['sim_time'])<1e-7]
        if not starts or math.dist(starts[0].get('target_m',[]),b)>1e-5:errors.append({'cursor':e['cursor'],'reason':'no_matching_native_submission'})
        original_invalid=False
        for actor,row in frame.items():
            if actor==e['actor_id'] or not row.get('ready'):continue
            distance,allowed=clearance(a,b,row['position_m'])
            minimum=distance if minimum is None else min(minimum,distance)
            if not allowed:errors.append({'cursor':e['cursor'],'reason':'alternative_body_clearance','blocker':actor,'distance_m':distance})
            if not clearance(*e['original_candidate_m'],row['position_m'])[1]:original_invalid=True
        rejected=[n for n in events if n['kind']=='traffic_candidate_rejected' and n.get('route_id')==e['route_id'] and n['points_m']==e['original_candidate_m'] and n['sim_time']<=e['sim_time']]
        if not original_invalid and not any(n['claim_conflicts'] for n in rejected):errors.append({'cursor':e['cursor'],'reason':'no_recorded_physical_rejection'})
        checks.append({'cursor':e['cursor'],'actor_id':e['actor_id'],'sim_time':e['sim_time'],'native_task_id':starts[0]['native_task_id'] if starts else None,'minimum_actual_body_distance_m':minimum,'target_unchanged':True})
    return {'run_id':folder.name,'attempts':len(attempts),'admitted':len(admitted),'execution_observed':bool(admitted),
        'proof_checks_passed':not errors,'execution_and_checks_passed':bool(admitted) and not errors,'errors':errors,'checks':checks,
        'limits':['actual roots and centre-line clearance are geometric proxies, not whole-body mesh or contact force',
            'normal admission still enforces exclusive claims and older fences; this audit does not reconstruct every historic claim',
            'zero admitted alternatives are compatibility evidence, not fallback execution proof']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('--output',required=True);args=parser.parse_args()
    result=audit(args.directory);Path(args.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['run_id','attempts','admitted','proof_checks_passed','errors']},indent=2))
