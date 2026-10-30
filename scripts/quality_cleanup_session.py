"""Native regression for a distant cancelled sit approach and bounded via travel."""
import argparse,json,math,os,signal,sys,time,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from simpeople.tools.client import call as rpc
from simpeople.core.errors import SimPeopleError
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--endpoint',default='http://127.0.0.1:8780');a=p.parse_args()
d=Path(__file__).resolve().parents[1]/'runs'/a.run_id;serial=0;result={}
log=(d/'cleanup_calls.jsonl').open('w',buffering=1)
def call(method,params=None):
 global serial
 serial+=1;params=dict(params or {})
 if method not in {'get_state','inspect_scene'}:params.setdefault('request_id',f'cleanup-audit-{serial}')
 deadline=time.monotonic()+180
 while True:
  try:r=rpc('people.'+method,params,a.endpoint);break
  except SimPeopleError as error:
   if error.code not in {'BRIDGE_TIMEOUT','BACKEND_UNAVAILABLE'} or time.monotonic()>deadline:raise
   log.write(json.dumps({'method':method,'params':params,'error':error.as_dict(),'retry_same_request_id':True})+'\n');time.sleep(1)
 log.write(json.dumps({'wall_time':time.time(),'method':method,'params':params,'result':r})+'\n');return r
def until(fn,seconds=1200):
 deadline=time.monotonic()+seconds
 while time.monotonic()<deadline:
  answer=fn()
  if answer:return answer
  time.sleep(.3)
 raise TimeoutError('native cleanup regression condition')
def state(tid):return call('get_state',{'task_id':tid})
def done(tid):return until(lambda:(s if (s:=state(tid))['status'] in {'succeeded','failed','cancelled'} else None))
try:
 call('spawn',{'actor_id':'cleanup_actor','spawn_anchor':[-17.5,-5,0]})
 # More than 12 live actors exercises the bounded, large-crowd route branch.
 for i in range(12):call('spawn',{'actor_id':f'background_{i:02d}','spawn_anchor':[-16.5+i*3,20,0]})
 call('record',{'mode':'camera','view':'follow','actor_id':'cleanup_actor'})
 tid=call('run_activity',{'actor_id':'cleanup_actor','steps':[{'action':'sit','target':'seat_00','duration_s':20}]})['task_id']
 moving=until(lambda:(s if (s:=state(tid))['observation'].get('speed_mps',0)>.3 else None))
 before=moving['observation'];cancel_time=call('inspect_scene')['sim_time']
 call('cancel',{'task_id':tid});terminal=done(tid)
 actors=call('get_state',{'actor_id':'cleanup_actor'})['actors'];actor=actors[0]
 result['distant_approach_cancel']={'task_id':tid,'terminal':terminal['status'],'elapsed_sim_s':call('inspect_scene')['sim_time']-cancel_time,
  'before_position_m':before['position_m'],'after_position_m':terminal['observation']['position_m'],'seat_released':actor['seat'] is None,'cleanup_pending':actor['seat_cleanup_pending']}
 steps=[{'action':'wait','duration_s':2},{'action':'move_to','via':[[-12.5,-5,0],[12.5,-5,0]],'target':[18.75,-5,0],'timeout_s':160},{'action':'wait','duration_s':1}]
 tid=call('run_activity',{'actor_id':'cleanup_actor','steps':steps})['task_id'];terminal=done(tid)
 result['bounded_via_route']={'task_id':tid,'terminal':terminal['status'],'steps':steps,'error':terminal.get('error')}
 rows=[json.loads(line) for line in (d/'trajectories.jsonl').open()]
 rows=[r for r in rows if r['actor_id']=='cleanup_actor' and r.get('ready') and r['sim_time']>=terminal['accepted_sim_time']]
 progress=0;via_steps=[];targets=steps[1]['via']+[steps[1]['target']]
 for row in rows:
  if progress<len(targets) and math.dist(row['position_m'][:2],targets[progress][:2])<=.35:
   via_steps.append({'target_m':targets[progress],'actual_position_m':row['position_m'],'sim_time':row['sim_time']});progress+=1
 result['bounded_via_route']['visited_targets_in_order']=via_steps
 result['bounded_via_route']['all_targets_observed']=progress==len(targets)
 result['passed']=result['distant_approach_cancel']['terminal']=='cancelled' and result['distant_approach_cancel']['seat_released'] and not result['distant_approach_cancel']['cleanup_pending'] and result['distant_approach_cancel']['elapsed_sim_s']<5 and terminal['status']=='succeeded' and progress==len(targets)
except Exception:result.update(passed=False,error=traceback.format_exc());traceback.print_exc()
finally:
 log.close();(d/'cleanup_acceptance.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
 pid=json.loads((d/'ready.json').read_text())['pid']
 try:
  cmd=Path(f'/proc/{pid}/cmdline').read_bytes()
  if b'kit_main.py' in cmd and a.run_id.encode() in cmd:os.kill(pid,signal.SIGTERM)
 except FileNotFoundError:pass
if not result.get('passed'):raise SystemExit(1)
