"""Audit closed RuntimeBench evidence without changing its original outcomes."""
import argparse
import json
import math
from pathlib import Path
from analyze_waits import analyze


def audit(directory):
    folder=Path(directory)
    def read(name):return json.loads((folder/name).read_text())
    case=read('workload.json');outcomes=read('outcomes.json');done=read('benchmark_done.json')
    tasks={t['task_id']:t for t in read('tasks.json')};expected={r['request_case_id']:r for r in case['requests']}
    events=[]
    for line in (folder/'events.jsonl').open():
        event=json.loads(line)
        if event.get('cursor',0)<=done['event_cursor']:events.append(event)
    waits=analyze(folder);matched=[];unmatched=[]
    for row in outcomes['requests']:
        spec=expected[row['request_case_id']];task=tasks.get(row.get('task_id'),{})
        ok=(row['state']==spec.get('expected_outcome','succeeded') and
            ('expected_error_code' not in spec or (row.get('error') or {}).get('code')==spec['expected_error_code']) and
            ('expected_physical_stop' not in spec or task.get('physical_stop_verified')==spec['expected_physical_stop']))
        (matched if ok else unmatched).append(row['request_case_id'])
    recovery_checks=[];route_goals={e['route_id']:e['goals_m'][-1] for e in events if e['kind']=='traffic_route_started'}
    for task in tasks.values():
        attempts=[a for a in task.get('recovery_attempts',[]) if a['at_sim_time']<=done['time_s']]
        for attempt in attempts:
            starts=[e for e in events if e['kind']=='step_started' and e.get('task_id')==task['task_id'] and e['sim_time']<=attempt['at_sim_time']]
            start=max(starts,key=lambda e:e['sim_time']) if starts else None
            original=start['sim_time']+start['step'].get('timeout_s',120) if start else None
            recovery_checks.append({'task_id':task['task_id'],'actor_id':task['actor_id'],'attempt':attempt,
                'original_step_deadline_sim_time':original,'deadline_unchanged':original is not None and abs(original-attempt['deadline_sim_time'])<1e-5})
    applied=[{'route_id':e['route_id'],'target_unchanged':e['route_id'] in route_goals and math.dist(e['target_m'],route_goals[e['route_id']])<1e-5,
        'physical_stop_verified':e['physical_stop_verified']} for e in events if e['kind']=='traffic_recovery_applied']
    box=None
    if any(e.get('method')=='move_prop' and e.get('params',{}).get('prop_id')=='movable_box' for e in case.get('events',[])):
        moves=[e for e in events if e['kind']=='prop_moved' and e['prop_id']=='movable_box']
        enter,leave=moves;center=enter['position_m'];size=read('scene_semantics.json')['movable_box']['size_m'];worst=None
        for line in (folder/'trajectories.jsonl').open():
            row=json.loads(line)
            if not row.get('ready') or not enter['sim_time']<=row['sim_time']<leave['sim_time']:continue
            pos=row['position_m'];distance=math.hypot(*[max(abs(pos[i]-center[i])-size[i]/2,0) for i in range(2)])
            if worst is None or distance<worst['distance_m']:worst={'actor_id':row['actor_id'],'sim_time':row['sim_time'],'distance_m':distance,'position_m':pos}
        box={'enter_sim_time':enter['sim_time'],'leave_sim_time':leave['sim_time'],'box_size_m':size,'minimum_root_to_surface':worst,
            'threshold_m':.2,'passed':worst is not None and worst['distance_m']>=.2,
            'obstacle_brakes':sum(e['kind']=='traffic_obstacle_brake' for e in events),
            'definition':'actual native roots against the box AABB from main-thread applied prop events and authored USD dimensions; no contact-force or mesh claim'}
    return {'run_id':folder.name,'finite':case.get('finite',True),'planned_requests':len(expected),'outcome_counts':outcomes['counts'],
        'expected_outcomes_matched':len(matched),'unmatched_requests':unmatched,'all_expected_outcomes_matched':not unmatched,
        'conservation_passed':outcomes['conservation_passed'],'admission_bounds_passed':waits['admission_bounds_passed'],
        'active_tickets_at_cutoff':waits['active_tickets_at_cutoff'],'ticket_status_counts':waits['ticket_status_counts'],
        'persistent_cycles':len(waits['persistent_cycles']),'wait_budget_violations':len(waits['wait_budget_violations']),
        'feasible_newcomers_deferred':len(waits['feasible_newcomers_deferred']),
        'verified_partial_drainage_grants':sum(e['kind']=='traffic_drainage_granted' for e in events),
        'recovery_attempts_per_task':{t['task_id']:len(t.get('recovery_attempts',[])) for t in tasks.values()},
        'recovery_budget_passed':all(len(t.get('recovery_attempts',[]))<=2 for t in tasks.values()),
        'recovery_checks':recovery_checks,'recovery_deadlines_unchanged':all(r['deadline_unchanged'] for r in recovery_checks) if recovery_checks else None,
        'applied_recovery':applied,'dynamic_box_geometry_proxy':box,
        'limits':['a continuous 120 s screen retains censored requests; it cannot certify the full release workload',
            'zero attempts/applied events do not certify native recovery execution',
            'explicit timeout or cancellation is not a passed fairness budget',
            'physical stop describes settlement then, not permanently immobilized native idle motion']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('--output',required=True);args=parser.parse_args()
    result=audit(args.directory);Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['run_id','all_expected_outcomes_matched','unmatched_requests','wait_budget_violations','recovery_budget_passed']},indent=2))
