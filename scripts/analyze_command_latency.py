"""Separate bridge application, native dispatch and observed motion latency."""
import argparse
import json
from pathlib import Path
import statistics

p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args();d=Path(a.directory)
events=[json.loads(line) for line in (d/'events.jsonl').open()]
stamps={round(x['sim_time'],6):x['wall_time'] for x in (json.loads(line) for line in (d/'video_timestamps.jsonl').open())}
accepted={};requests={};applied=None;started={};steps={};native={};cancelled={};finished={}
all_bridge=[]
for e in events:
    kind=e['kind']
    if kind=='command_applied':
        applied=e;all_bridge.append(e['wall_time']-e['received_wall_time'])
    elif kind=='tool_call' and applied and e['method']==applied['method'].removeprefix('people.'):
        applied={**applied,'request_id':e['params'].get('request_id')}
    elif kind=='task_accepted' and e['task'].get('source','agent')=='agent':
        t=e['task'];accepted[t['task_id']]=t
        if (applied and applied['method'].removeprefix('people.') in {'move_to','run_activity','perform'}
            and applied['episode_id']==t['episode_id']):
            requests[t['task_id']]=applied
    elif kind=='task_started':started[e['task_id']]=e
    elif kind=='step_started' and e['index']==0:steps[e['task_id']]=e
    elif kind=='traffic_native_started':native.setdefault(e['route_id'],e)
    elif kind=='cancel_requested':cancelled[e['task_id']]=e
    elif kind=='task_ended':finished[e['task']['task_id']]=e

previous={};onsets={};before={}
for line in (d/'trajectories.jsonl').open():
    row=json.loads(line);key=(row['episode_id'],row['actor_id']);tid=row['task_id']
    if tid in accepted and tid not in before:
        before[tid]=previous.get(key)
    if (tid in accepted and tid not in onsets and row.get('ready') and row['speed_mps']>.15 and
        accepted[tid]['steps'][0]['action']=='move_to'):
        prior=before.get(tid)
        if prior and prior.get('ready') and prior['speed_mps']<.15:
            wall=stamps.get(round(row['sim_time'],6))
            if wall is not None:onsets[tid]={'wall_time':wall,'sim_time':row['sim_time'],'speed_mps':row['speed_mps']}
    previous[key]=row

def stats(values):
    values=sorted(values)
    return {'samples':len(values),'median_s':statistics.median(values) if values else None,
            'p95_s':values[min(len(values)-1,int(.95*len(values)))] if values else None,'max_s':max(values) if values else None}

records=[]
for tid,t in accepted.items():
    request=requests.get(tid)
    if not request:continue
    received=request['received_wall_time'];step=steps.get(tid);route=(step or {}).get('backend_task_id')
    dispatch=native.get(route) if isinstance(route,str) else step
    if not step or step['step']['action']!='move_to':dispatch=None
    prior=before.get(tid)
    records.append({'task_id':tid,'actor_id':t['actor_id'],'request_id':request.get('request_id'),
      'method':request['method'],'received_wall_time':received,
      'first_action':t['steps'][0]['action'],
      'receive_to_main_thread_s':request['wall_time']-received,
      'receive_to_task_started_s':started[tid]['wall_time']-received if tid in started else None,
      'receive_to_native_dispatch_s':dispatch['wall_time']-received if dispatch else None,
      'receive_to_observed_motion_s':onsets[tid]['wall_time']-received if tid in onsets else None,
      'motion_measurement_scope':'previous recorded pose stationary, first captured runtime root speed >0.15m/s' if tid in onsets else 'not estimated: actor already moving, no prior stationary sample, or non-move first step',
      'previous_speed_mps':prior.get('speed_mps') if prior else None,'first_motion_sample':onsets.get(tid)})
settlement=[finished[tid]['wall_time']-e['wall_time'] for tid,e in cancelled.items() if tid in finished and finished[tid]['task']['status']=='cancelled']
result={'run_id':d.name,'all_bridge_receive_to_apply':stats(all_bridge),
        'agent_motion_tasks':records,'agent_task_receive_to_native_dispatch':stats([r['receive_to_native_dispatch_s'] for r in records if r['receive_to_native_dispatch_s'] is not None]),
        'stationary_actor_receive_to_observed_motion':stats([r['receive_to_observed_motion_s'] for r in records if r['receive_to_observed_motion_s'] is not None]),
        'cancel_request_to_settled_terminal':stats(settlement),
        'limitations':['Wall-clock observations on this shared machine; frame sampling bounds motion onset accuracy.',
                       'Native dispatch means an actual API call, not physical movement. Already-moving retargets are deliberately excluded from stationary-onset statistics.',
                       'This audit includes all matching recorded agent tasks, including later failures/cancellations; task terminal evidence remains separate.']}
(d/'command_latency_audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in {'agent_motion_tasks','limitations'}},indent=2))
