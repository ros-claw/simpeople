"""Correlate accepted/rejected/replayed requests without inventing command IDs."""
import argparse,json
from collections import defaultdict
from pathlib import Path
def analyze(path):
    calls=defaultdict(int);results=defaultdict(int);commands={};uncorrelated=0
    for line in Path(path).open():
        e=json.loads(line)
        rid=e.get('request_id');cid=e.get('command_id')
        if e['kind'] in {'tool_call','tool_result'}:
            if not rid:uncorrelated+=1;continue
            key=(rid,e.get('method'));(calls if e['kind']=='tool_call' else results)[key]+=1
        if cid:
            row=commands.setdefault(cid,{'request_ids':set(),'task_ids':set(),'attempt_ids':set(),'native_task_ids':set(),'task_outcomes':{},'errors':[]})
            for key,dest in [('request_id','request_ids'),('task_id','task_ids'),('attempt_id','attempt_ids')]:
                value=e.get('logical_task_id') if key=='task_id' and e['kind']=='native_task_ended' else e.get(key)
                if value is not None:row[dest].add(str(value))
            if e.get('native_task_id') is not None:row['native_task_ids'].add(str(e['native_task_id']))
            if e['kind']=='task_ended':
                task=e['task'];row['task_outcomes'][task['task_id']]={k:task.get(k) for k in ['actor_id','actor_instance_id','status','error','physical_stop_verified','termination_reason','finished_sim_time']}
            error=e.get('error') or e.get('task',{}).get('error')
            if error:row['errors'].append({'event_kind':e['kind'],'error':error})
    for row in commands.values():
        for key in ['request_ids','task_ids','attempt_ids','native_task_ids']:row[key]=sorted(row[key])
    unmatched=[{'request_id':rid,'method':method,'calls':calls.get((rid,method),0),'results':results.get((rid,method),0)} for rid,method in sorted(set(calls)|set(results)) if results.get((rid,method),0)!=calls.get((rid,method),0)]
    return {'commands':commands,'unmatched_request_results':unmatched,'request_call_events':sum(calls.values()),'request_result_events':sum(results.values()),'uncorrelated_tool_events':uncorrelated,'scope':'retries/rejections are attempts, not task success; uncorrelated legacy reads retained separately'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('events');p.add_argument('--output');a=p.parse_args();r=analyze(a.events);text=json.dumps(r,indent=2,ensure_ascii=False)
    if a.output:Path(a.output).write_text(text+'\n')
    else:print(text)
