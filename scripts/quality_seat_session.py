"""Twelve native rigs: full seat cycles, side views, entry and seated cancellation."""
import argparse,json,os,signal,sys,time,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from simpeople.tools.client import call as rpc
from simpeople.core.errors import SimPeopleError
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--endpoint',default='http://127.0.0.1:8780');a=p.parse_args()
d=Path(__file__).resolve().parents[1]/'runs'/a.run_id;end=time.monotonic()+300
while not (d/'ready.json').exists():
 if time.monotonic()>end:raise TimeoutError('runtime startup')
 time.sleep(1)
log=(d/'seat_calls.jsonl').open('w',buffering=1);serial=0;result={};tasks=[]
def call(m,p=None):
 global serial
 serial+=1;p=dict(p or {})
 if m not in {'inspect_scene','list_assets','get_state'}:p.setdefault('request_id',f'seat-{serial}')
 retry_deadline=time.monotonic()+180
 while True:
  try:r=rpc('people.'+m,p,a.endpoint);break
  except SimPeopleError as error:
   log.write(json.dumps({'wall_time':time.time(),'method':m,'params':p,'error':error.as_dict(),'retry_same_request_id':True})+'\n')
   if error.code not in {'BRIDGE_TIMEOUT','BACKEND_UNAVAILABLE'} or time.monotonic()>retry_deadline:raise
   time.sleep(1)
 log.write(json.dumps({'wall_time':time.time(),'method':m,'params':p,'result':r})+'\n');return r
def until(fn,timeout=1200):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  r=fn()
  if r:return r
  time.sleep(.5)
 raise TimeoutError('seat audit condition')
def state(tid):return call('get_state',{'task_id':tid})
def done(tid):return until(lambda:(s if (s:=state(tid))['status'] in {'succeeded','failed','cancelled'} else None))
def plan(aid,steps):return call('run_activity',{'actor_id':aid,'steps':steps})['task_id']
try:
 scene=call('inspect_scene');assets=call('list_assets')['assets'][:12]
 for i,asset in enumerate(assets):
  seat=scene['locations'][f'asset_seat_{i:02d}'];pos=seat['seat_profile']['position_m']
  aid=f'seat_actor_{i:02d}';call('spawn',{'actor_id':aid,'asset_id':asset['asset_id'],'spawn_anchor':[pos[0],pos[1]-1.8,0]})
  tasks.append(plan(aid,[{'action':'sit','target':f'asset_seat_{i:02d}','duration_s':25,'timeout_s':120}, {'action':'leave_seat'}, {'action':'move_to','target':seat['egress']},{'action':'wait','duration_s':1}]))
 call('record',{'mode':'camera','view':'seat_side','actor_id':'seat_actor_00'})
 until(lambda:all(state(t)['step_phase']=='holding' for t in tasks))
 for i,tid in enumerate(tasks):
  call('record',{'mode':'camera','view':'seat_side','actor_id':f'seat_actor_{i:02d}'})
  now=call('inspect_scene')['sim_time'];until(lambda:call('inspect_scene')['sim_time']>now+.35)
 result['full_cycles']=[{'asset_id':assets[i]['asset_id'],'task_id':t,'terminal':done(t)['status']} for i,t in enumerate(tasks)]
 # Repeat on the default rig to exercise both cancellation windows explicitly.
 for phase in ('entering','holding'):
  tid=plan('seat_actor_00',[{'action':'sit','target':'asset_seat_00','duration_s':30}])
  call('record',{'mode':'camera','view':'seat_side','actor_id':'seat_actor_00'})
  if phase=='holding':until(lambda:state(tid)['step_phase']=='holding')
  else:until(lambda:state(tid)['observation'].get('action')=='Sit' and state(tid)['step_phase']!='holding')
  call('cancel',{'task_id':tid});terminal=done(tid);result['cancel_'+phase]={'terminal':terminal['status'],'task_id':tid}
 result['passed']=all(r['terminal']=='succeeded' for r in result['full_cycles']) and all(result['cancel_'+x]['terminal']=='cancelled' for x in ('entering','holding'))
except Exception:result.update(passed=False,error=traceback.format_exc());traceback.print_exc()
finally:
 log.close();(d/'seat_acceptance.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
 ready=json.loads((d/'ready.json').read_text());pid=ready['pid']
 try:
  cmd=Path(f'/proc/{pid}/cmdline').read_bytes().decode().replace('\0',' ')
  if 'kit_main.py' in cmd and a.run_id in cmd:os.kill(pid,signal.SIGTERM)
 except FileNotFoundError:pass
if not result.get('passed'):raise SystemExit(1)
