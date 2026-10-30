"""Grade real host traces against native state; CLI exit alone is insufficient."""
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args();d=Path(a.directory)
events=[json.loads(x) for x in (d/'events.jsonl').read_text().splitlines()]
ended=[x['task'] for x in events if x['kind']=='task_ended'];states=[];results=[]
for i in range(1,4):
 f=d/f'codex_task_{i}_native_state.json'
 if not f.exists():break
 state=json.loads(f.read_text());states.append({x['actor_id']:x for x in state['actors']});calls=[]
 for line in (d/f'codex_task_{i}.jsonl').read_text().splitlines():
  try:r=json.loads(line)
  except ValueError:continue
  item=r.get('item',{})
  if r.get('type')=='item.completed' and item.get('type')=='mcp_tool_call' and item.get('server')=='simpeople':calls.append(item)
 current=states[-1];checks={}
 if i==1:
  actor=current.get('codex_life');life=[t for t in ended if t['actor_id']=='codex_life' and t['status']=='succeeded']
  actions=[step['action'] for t in life for step in t['steps']]
  checks={'actor_created':actor is not None,'native_life_actions_completed':all(x in actions for x in ('move_to','sit','leave_seat')),
          'final_task_succeeded':bool(actor and actor.get('task') and actor['task']['status']=='succeeded'),
          'seat_released':bool(actor and actor['seat'] is None and not actor['seat_cleanup_pending'])}
 elif i==2:
  one,two,three=[current.get('codex_g'+str(j)) for j in (1,2,3)]
  checks={'three_created':all((one,two,three)),
          'first_two_retargeted':bool(one and two and one['control_epoch']>=2 and two['control_epoch']>=2),
          'first_two_completed':bool(one and two and all(x.get('task') and x['task']['status']=='succeeded' for x in (one,two))),
          'third_kept_original_wait':bool(three and three['control_epoch']==1 and three.get('task') and three['task']['steps'][0]['action']=='wait')}
 else:
  one=current.get('codex_g1');old=states[1];cancelled=[t for t in ended if t['actor_id']=='codex_g1' and t['status']=='cancelled' and any(s['action']=='move_to' for s in t['steps'])]
  # Replacement in task 2 also cancels a wait. Require a cancelled move and a later successful wait.
  restore=one.get('task') if one else None
  checks={'moving_task_cancelled':bool(cancelled),'restored_wait_completed':bool(restore and restore['status']=='succeeded' and restore['steps'][0]['action']=='wait'),
          'actor_stopped':bool(one and one['observation'].get('speed_mps',99)<.15),
          'others_kept_tasks':all(aid in current and aid in old and current[aid].get('task',{}).get('task_id')==old[aid].get('task',{}).get('task_id') for aid in ('codex_g2','codex_g3'))}
 results.append({'task_number':i,'passed':all(checks.values()),'checks':checks,'completed_mcp_calls':len(calls),
                 'tool_errors_including_recovered':sum(x.get('status')=='failed' or x.get('error') is not None for x in calls)})
result={'passed':len(results)==3 and all(x['passed'] for x in results),'results':results,'evidence':'real Codex JSONL plus actual native task events and post-trial state',
        'capture_scope':'control/animation state; see config.json for RGB recording availability'}
(d/'host_acceptance.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
