"""Run the same 35 m walk/run profile on twelve real native character rigs."""
import argparse,json,os,signal,sys,time,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from simpeople.tools.client import call as rpc
from simpeople.core.errors import SimPeopleError
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);a=p.parse_args();root=Path(__file__).resolve().parents[1];d=root/'runs'/a.run_id
end=time.monotonic()+300
while not (d/'ready.json').exists():
 if time.monotonic()>end:raise TimeoutError('runtime startup')
 time.sleep(1)
log=(d/'gait_pool_calls.jsonl').open('w',buffering=1);serial=0;result={}
def call(m,p=None):
 global serial
 serial+=1;p=dict(p or {})
 if m not in {'inspect_scene','list_assets','get_state'}:p.setdefault('request_id',f'pool-{serial}')
 deadline=time.monotonic()+180
 while True:
  try:r=rpc('people.'+m,p,'http://127.0.0.1:8780');break
  except SimPeopleError as error:
   log.write(json.dumps({'wall_time':time.time(),'method':m,'params':p,'error':error.as_dict(),'retry_same_request_id':True})+'\n')
   if error.code not in {'BRIDGE_TIMEOUT','BACKEND_UNAVAILABLE'} or time.monotonic()>deadline:raise
   time.sleep(1)
 log.write(json.dumps({'wall_time':time.time(),'method':m,'params':p,'result':r})+'\n');return r
try:
 assets=call('list_assets')['assets'][:12];tasks=[]
 for i,asset in enumerate(assets):
  aid=f'gait_{i:02d}';y=-17.5+i*3
  call('spawn',{'actor_id':aid,'asset_id':asset['asset_id'],'spawn_anchor':[-17.5,y,0]})
 for i,asset in enumerate(assets):
  aid=f'gait_{i:02d}';y=-17.5+i*3
  steps=[{'action':'wait','duration_s':2},{'action':'move_to','target':[17.5,y,0],'gait':'walk','speed_mps':1.2,'timeout_s':120},{'action':'wait','duration_s':1},{'action':'move_to','target':[-17.5,y,0],'gait':'run','speed_mps':2.8,'timeout_s':120},{'action':'wait','duration_s':2}]
  tasks.append(call('run_activity',{'actor_id':aid,'steps':steps})['task_id'])
 call('record',{'mode':'camera','view':'gait_side','actor_id':'gait_00'})
 end=time.monotonic()+2400;states=[];tour=0
 while time.monotonic()<end:
  states=[call('get_state',{'task_id':t}) for t in tasks]
  if all(s['status'] in {'succeeded','failed','cancelled'} for s in states):break
  if states[0].get('step_index') in {1,3}:
   call('record',{'mode':'camera','view':'gait_side','actor_id':f'gait_{tour%12:02d}'});tour+=1
  time.sleep(1)
 result={'passed':all(s['status']=='succeeded' for s in states),'results':[{'asset_id':assets[i]['asset_id'],'actor_id':f'gait_{i:02d}','task_id':s['task_id'],'terminal':s['status'],'error':s.get('error')} for i,s in enumerate(states)]}
except Exception:result.update(passed=False,error=traceback.format_exc());traceback.print_exc()
finally:
 log.close();(d/'gait_pool_acceptance.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
 ready=json.loads((d/'ready.json').read_text());pid=ready['pid']
 try:
  command=Path(f'/proc/{pid}/cmdline').read_bytes().decode().replace('\0',' ')
  if 'kit_main.py' in command and a.run_id in command:os.kill(pid,signal.SIGTERM)
 except FileNotFoundError:pass
if not result.get('passed'):raise SystemExit(1)
