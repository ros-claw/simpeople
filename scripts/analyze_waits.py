"""Queue/traffic waits, including rejected and unfinished requests at cutoff."""
import argparse
import json
from collections import Counter
from pathlib import Path

ACTIVE={'waiting','admitted','serving','exiting'}

def stats(values):
    values=sorted(values)
    return {'samples':len(values),'p50_sim_s':values[len(values)//2] if values else None,
            'p95_sim_s':values[min(len(values)-1,int(.95*len(values)))] if values else None,
            'max_sim_s':values[-1] if values else None}

def analyze(directory):
    folder=Path(directory)
    def read(name,default=None):return json.loads((folder/name).read_text()) if (folder/name).exists() else default
    cutoff=read('benchmark_done.json',{});cursor=cutoff.get('event_cursor');now=cutoff.get('time_s',read('metrics.json',{}).get('sim_elapsed_s',0))
    outcomes=read('outcomes.json');case=read('workload.json',{});tickets={};steps={};current={};traffic={};maxima={};cycles=[];violations=[];deferred=[];recoveries=[];last_sim=0
    for line in (folder/'events.jsonl').open():
        event=json.loads(line)
        if cursor is not None and event.get('cursor',0)>cursor:continue
        if cursor is None and event.get('sim_time',0)>now+1e-7:continue
        last_sim=max(last_sim,event.get('sim_time',0));kind=event['kind'];tid=event.get('logical_task_id',event.get('task_id'));sim=event.get('sim_time',0)
        if kind.startswith('admission_') and event.get('ticket'):
            row=event['ticket'];tickets[row['ticket_id']]=row
            resource=row['resource_id'];active=[t for t in tickets.values() if t['resource_id']==resource and t['status'] in ACTIVE]
            maximum=maxima.setdefault(resource,{'capacity':row['capacity'],'outside_capacity':row['outside_capacity'],'max_active':0,'max_outside':0})
            maximum['max_active']=max(maximum['max_active'],len(active));maximum['max_outside']=max(maximum['max_outside'],max(0,len(active)-row['capacity']))
        if kind=='step_started' and event.get('step',{}).get('action')=='queue':
            key=(tid,event['index']);current[tid]=key;steps[key]={'task_id':tid,'actor_id':event['actor_id'],'resource_id':event['step']['target'],'start_sim_time':sim,'completed':False}
        key=current.get(tid)
        if key in steps:
            row=steps[key]
            for event_kind,field in [('queue_service_started','service_started_sim_time'),('queue_service_ended','service_ended_sim_time'),('queue_slot_arrived','first_slot_arrived_sim_time')]:
                if kind==event_kind:row.setdefault(field,sim)
            if kind=='step_ended' and event.get('action')=='queue':row.update(completed=True,end_sim_time=sim,latency_sim_s=sim-row['start_sim_time'])
            if kind=='task_ended' and not row['completed']:
                row.update(task_terminal=event['task']['status'],terminal_sim_time=sim,
                    wait_until_terminal_sim_s=sim-row['start_sim_time'],error=event['task'].get('error'))
        rid=event.get('route_id')
        if kind=='traffic_wait_started':traffic.setdefault(rid,[]).append({'start_sim_time':sim,'blocker_details':event.get('blocked_details'),'actor_handle':event.get('agent')})
        if rid in traffic and traffic[rid] and 'end_sim_time' not in traffic[rid][-1]:
            if kind=='traffic_wait_ended':traffic[rid][-1].update(end_sim_time=sim,served=True,wait_sim_s=sim-traffic[rid][-1]['start_sim_time'])
            elif kind in {'traffic_route_ended','traffic_route_cancelled'}:traffic[rid][-1].update(end_sim_time=sim,served=False,termination=kind,wait_lower_bound_sim_s=sim-traffic[rid][-1]['start_sim_time'])
        if kind in {'traffic_wait_cycle','task_wait_cycle'}:cycles.append(event)
        if kind=='traffic_wait_budget_exceeded':violations.append(event)
        if kind=='traffic_fairness_deferred':deferred.append(event)
        if kind in {'recovery_attempt','traffic_recovery_requested','traffic_recovery_applied'}:recoveries.append(event)
    now=max(now,last_sim)
    for row in steps.values():
        if not row['completed'] and not row.get('task_terminal'):row['unfinished_wait_lower_bound_sim_s']=max(0,now-row['start_sim_time'])
        if row.get('service_started_sim_time') is not None:row['request_to_service_sim_s']=row['service_started_sim_time']-row['start_sim_time']
    for row in tickets.values():
        if row['status'] in ACTIVE:row['unfinished_wait_lower_bound_sim_s']=max(0,now-row['requested_sim_time'])
        if row.get('admitted_sim_time') is not None:row['admission_wait_sim_s']=row['admitted_sim_time']-row['requested_sim_time']
    waits=[r for segments in traffic.values() for r in segments]
    for row in waits:
        if 'end_sim_time' not in row:row.update(served=False,censored=True,wait_lower_bound_sim_s=max(0,now-row['start_sim_time']))
    return {'run_id':folder.name,'case_sha256':outcomes.get('case_sha256') if outcomes else None,'finite':case.get('finite',True),
        'cutoff_sim_time':now,'cutoff_event_cursor':cursor,'planned_outcomes':{k:outcomes.get(k) for k in ['scheduled','submitted','admitted','counts','denominator','censored','unsuccessful','conservation_passed']} if outcomes else None,
        'tickets':list(tickets.values()),'ticket_status_counts':dict(Counter(r['status'] for r in tickets.values())),
        'active_tickets_at_cutoff':sum(r['status'] in ACTIVE for r in tickets.values()),'admission_bounds':maxima,
        'admission_bounds_passed':all(r['max_outside']<=r['outside_capacity'] and r['max_active']<=r['capacity']+r['outside_capacity'] for r in maxima.values()) if maxima else None,
        'queue_steps':list(steps.values()),'completed_queue_latency':stats([r['latency_sim_s'] for r in steps.values() if r['completed']]),
        'request_to_service':stats([r['request_to_service_sim_s'] for r in steps.values() if 'request_to_service_sim_s' in r]),
        'unfinished_queue_steps':sum(not r['completed'] and not r.get('task_terminal') for r in steps.values()),
        'queue_steps_without_completion':sum(not r['completed'] for r in steps.values()),
        'terminal_without_queue_completion':dict(Counter(r['task_terminal'] for r in steps.values() if not r['completed'] and r.get('task_terminal'))),'traffic_waits':waits,
        'served_traffic_wait':stats([r['wait_sim_s'] for r in waits if r.get('served')]),'unserved_traffic_waits':sum(not r.get('served') for r in waits),
        'persistent_cycles':cycles,'wait_budget_violations':violations,'feasible_newcomers_deferred':deferred,'recovery_events':recoveries,
        'limits':['admission wait, request-to-service, and request-to-exit latency are different metrics',
            'completed/served distributions exclude unfinished waits; their counts and lower bounds remain alongside them',
            'legacy traces without tickets/service events cannot certify admission FIFO or a service-wait percentile',
            'a timeout or explicit cleanup failure does not turn a fairness budget violation into a pass']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--output',required=True);a=p.parse_args()
    result=analyze(a.directory);Path(a.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['run_id','ticket_status_counts','admission_bounds_passed','unfinished_queue_steps','unserved_traffic_waits']},indent=2))
