"""Read-only retry scheduling evidence; never upgrades task/native outcomes."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit_events(events):
    actors={};routes={};delays={};errors=[];waits=[];starts=0
    def error(event,reason):errors.append({'cursor':event.get('cursor'),'reason':reason})
    def collect(value,event):
        if isinstance(value,dict):
            if all(k in value for k in ('actor_id','actor_instance_id','prim_path')):
                key=(event.get('episode_id'),value['prim_path']);binding={k:value[k] for k in ('actor_id','actor_instance_id')}
                if key in actors and actors[key]!=binding:error(event,'physical_handle_reused')
                actors[key]=binding
            for child in value.values():collect(child,event)
        elif isinstance(value,list):
            for child in value:collect(child,event)
    for event in events:
        if event['kind']=='tool_result' and (event.get('method')=='spawn' or event.get('method')=='batch' and event.get('result',{}).get('operation')=='spawn'):collect(event.get('result'),event)
    instrumented=[e for e in events if e['kind']=='traffic_route_started' and 'retry_actor_id' in e]
    if not instrumented:
        return {'supported':False,'execution_checks_passed':False,'errors':[],
                'scope':'Legacy or unexercised logging; not evidence that the new retry contract executed.'}
    for event in events:
        kind=event['kind'];key=(event.get('episode_id'),event.get('route_id'))
        if kind=='traffic_route_started':
            starts+=1;binding=actors.get((event.get('episode_id'),event.get('agent')))
            if key in routes:error(event,'duplicate_route_start')
            routes[key]=event
            if binding is None:error(event,'route_has_no_spawn_binding');continue
            actor=binding['actor_id'];delay=event.get('retry_delay_s')
            if event.get('retry_actor_id')!=actor:error(event,'retry_key_is_not_logical_actor')
            if not isinstance(delay,(int,float)) or isinstance(delay,bool) or not math.isfinite(delay) or not .2-1e-9<=delay<=.3+1e-9 or abs((delay-.2)/.01-round((delay-.2)/.01))>1e-7:
                error(event,'delay_outside_declared_stagger_buckets');continue
            record=delays.setdefault(actor,{'delay_s':delay,'physical_handles':set(),'actor_instance_ids':set()})
            if abs(record['delay_s']-delay)>1e-8:error(event,'logical_actor_delay_changed')
            record['physical_handles'].add(event['agent']);record['actor_instance_ids'].add(binding['actor_instance_id'])
        elif kind=='traffic_wait_started':
            route=routes.get(key);delay=event.get('retry_delay_s');deadline=event.get('retry_at_sim_time')
            if route is None:error(event,'wait_has_no_route_start');continue
            if event.get('agent')!=route.get('agent') or event.get('retry_actor_id')!=route.get('retry_actor_id'):error(event,'wait_identity_changed')
            if delay!=route.get('retry_delay_s'):error(event,'wait_delay_changed')
            valid=all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (delay,deadline,event.get('sim_time')))
            if not valid or abs(deadline-event['sim_time']-delay)>1e-6:error(event,'actual_retry_schedule_mismatch')
            waits.append({'cursor':event.get('cursor'),'actor_id':event.get('retry_actor_id'),'sim_time':event.get('sim_time'),'retry_at_sim_time':deadline,'delay_s':delay,'passed':bool(valid and abs(deadline-event['sim_time']-delay)<=1e-6)})
    distinct=len({round(row['delay_s'],8) for row in delays.values()})
    checks={'spawn_bound_routes_observed':bool(starts) and bool(delays),
            'actual_block_schedules_observed':bool(waits),'multiple_actor_stagger_values_observed':distinct>=2,'no_contract_errors':not errors}
    return {'supported':True,'execution_checks_passed':all(checks.values()),'checks':checks,'route_starts':starts,'wait_starts':len(waits),'distinct_delay_values':distinct,
            'actors':{a:{'delay_s':r['delay_s'],'physical_handles':sorted(r['physical_handles']),'actor_instance_ids':sorted(r['actor_instance_ids'])} for a,r in delays.items()},
            'wait_schedules':waits,'errors':errors,'scope':'Logical retry identity, bounded staggering and actual scheduled clock offsets only. Native movement, stopping, fairness, deadlines and capacity need their own audits.'}


def audit(directory):
    directory=Path(directory)
    if not all((directory/n).is_file() for n in ['completed.json','benchmark_done.json','events.jsonl']):
        return {'measurement_closed':False,'execution_checks_passed':False,'reason':'BENCHMARK_NOT_CLOSED'}
    completed=json.loads((directory/'completed.json').read_text())
    if completed.get('harness_completed') is not True:return {'measurement_closed':False,'execution_checks_passed':False,'reason':'HARNESS_NOT_COMPLETED'}
    cutoff=json.loads((directory/'benchmark_done.json').read_text())['event_cursor']
    events=[e for e in map(json.loads,(directory/'events.jsonl').read_text().splitlines()) if e.get('cursor',0)<=cutoff]
    result=audit_events(events);result.update(run_id=directory.name,measurement_closed=True,functional_expected_matched=completed.get('functional_expected_matched'),
        inputs_sha256={n:sha(directory/n) for n in ['source_manifest.json','workload.json','events.jsonl','benchmark_done.json','completed.json']})
    return result


def compare(directories):
    directories=list(map(Path,directories));results=[audit(d) for d in directories];errors=[];common={}
    for directory,result in zip(directories,results):
        if not result.get('execution_checks_passed'):errors.append({'run_id':directory.name,'reason':'retry_execution_not_proven'});continue
        for actor,row in result['actors'].items():
            previous=common.get(actor)
            if previous:
                if abs(previous['delay_s']-row['delay_s'])>1e-8:errors.append({'actor_id':actor,'run_id':directory.name,'reason':'logical_delay_changed_across_runs'})
                if set(previous['physical_handles']) & set(row['physical_handles']) or set(previous['actor_instance_ids']) & set(row['actor_instance_ids']):errors.append({'actor_id':actor,'run_id':directory.name,'reason':'fresh_physical_incarnation_not_proven'})
            else:previous=common[actor]={'delay_s':row['delay_s'],'physical_handles':set(),'actor_instance_ids':set()}
            previous['physical_handles'].update(row['physical_handles']);previous['actor_instance_ids'].update(row['actor_instance_ids'])
    if len(directories)>=2 and all(r.get('measurement_closed') for r in results):
        for name in ['source_manifest.json','workload.json']:
            if len({sha(d/name) for d in directories})!=1:errors.append({'reason':'paired_input_changed','path':name})
        if any(set(r.get('actors',{}))!=set(results[0].get('actors',{})) for r in results):errors.append({'reason':'observed_logical_actor_set_changed'})
    else:errors.append({'reason':'need_two_closed_repetitions'})
    return {'passed':not errors,'runs':results,'errors':errors,'scope':'Repeatability of scheduling identity across fresh incarnations on identical frozen inputs. This is not a RuntimeBench release or speedup certificate.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directories',nargs='+');parser.add_argument('--output',required=True);args=parser.parse_args()
    result=audit(args.directories[0]) if len(args.directories)==1 else compare(args.directories)
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k in ('passed','execution_checks_passed','measurement_closed','errors')},indent=2))
    raise SystemExit(0 if result.get('passed',result.get('execution_checks_passed')) else 2)
