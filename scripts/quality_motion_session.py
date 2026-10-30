"""Drive a reproducible native gait audit, retaining real RPC replies and terminals."""
import argparse
import json
import os
from pathlib import Path
import signal
import sys
import time
import traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from simpeople.tools.client import call as rpc
from simpeople.core.errors import SimPeopleError
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--endpoint',default='http://127.0.0.1:8780');p.add_argument('--with-obstacles',action='store_true');a=p.parse_args()
d=Path(__file__).resolve().parents[1]/'runs'/a.run_id
end=time.monotonic()+240
while not (d/'ready.json').exists():
    if time.monotonic()>end:raise TimeoutError('runtime not ready')
    time.sleep(1)
log=(d/'motion_calls.jsonl').open('a',buffering=1);serial=0;result={}
def call(method,params=None):
    global serial
    params=dict(params or {});serial+=1
    if method not in {'inspect_scene','get_state'}:params.setdefault('request_id',f'gait-audit-{serial}')
    retry_deadline=time.monotonic()+180
    while True:
        try:r=rpc('people.'+method,params,a.endpoint);break
        except SimPeopleError as error:
            log.write(json.dumps({'wall_time':time.time(),'method':method,'params':params,'error':error.as_dict(),'retry_same_request_id':True})+'\n')
            if error.code not in {'BRIDGE_TIMEOUT','BACKEND_UNAVAILABLE'} or time.monotonic()>retry_deadline:raise
            time.sleep(1)
    log.write(json.dumps({'wall_time':time.time(),'method':method,'params':params,'result':r})+'\n');return r
try:
    call('inspect_scene')
    call('spawn',{'actor_id':'audit_actor','spawn_anchor':[-17.5,0,0]})
    call('record',{'mode':'camera','view':'follow','actor_id':'audit_actor'})
    steps=[{'action':'wait','duration_s':2},
           {'action':'move_to','target':[17.5,0,0],'gait':'walk','speed_mps':1.2,'timeout_s':160},
           {'action':'wait','duration_s':1},
           {'action':'move_to','via':[[18.75,0,0]],'target':[18.75,12.5,0],'gait':'walk','speed_mps':1.2,'timeout_s':100},
           {'action':'wait','duration_s':1},
           {'action':'move_to','target':[18.75,-8.75,0],'gait':'run','speed_mps':2.8,'timeout_s':100},
           {'action':'wait','duration_s':2}]
    tid=call('run_activity',{'actor_id':'audit_actor','steps':steps})['task_id']
    end=time.monotonic()+2400
    while time.monotonic()<end:
        s=call('get_state',{'task_id':tid})
        if s['status'] in {'succeeded','failed','cancelled'}:break
        time.sleep(.7)
    else:raise TimeoutError('motion audit task deadline')
    result={'task_id':tid,'terminal':s['status'],'error':s.get('error'),'steps':steps,'passed':s['status']=='succeeded'}
    if result['passed'] and a.with_obstacles:
        for aid,anchor in [('d_west',[-8,-18.75,0]),('d_east',[8,-17.5,0])]:call('spawn',{'actor_id':aid,'spawn_anchor':anchor})
        west=call('move_to',{'actor_id':'d_west','target':[8,-18.75,0],'timeout_s':120})['task_id']
        east=call('move_to',{'actor_id':'d_east','target':[-8,-17.5,0],'timeout_s':120})['task_id']
        call('record',{'mode':'camera','view':'follow','actor_id':'d_west'})
        deadline=time.monotonic()+600
        while time.monotonic()<deadline:
            w=call('get_state',{'task_id':west})
            if w['observation'].get('speed_mps',0)>.5:break
            time.sleep(.5)
        call('move_prop',{'prop_id':'movable_box','position_m':[0,-18.75,.65]})
        for name,task_id in [('dynamic_obstacle',west),('competitor',east)]:
            deadline=time.monotonic()+900
            while time.monotonic()<deadline:
                q=call('get_state',{'task_id':task_id})
                if q['status'] in {'succeeded','failed','cancelled'}:break
                time.sleep(.7)
            result[name]={'task_id':task_id,'terminal':q['status'],'error':q.get('error')}
        result['passed']=all(result[name]['terminal']=='succeeded' for name in ('dynamic_obstacle','competitor'))
except Exception:result={'passed':False,'error':traceback.format_exc()};traceback.print_exc()
finally:
    log.close();(d/'motion_acceptance.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    ready=json.loads((d/'ready.json').read_text());pid=ready['pid']
    try:
        command=Path(f'/proc/{pid}/cmdline').read_bytes().decode().replace('\0',' ')
        if 'kit_main.py' in command and a.run_id in command:os.kill(pid,signal.SIGTERM)
    except FileNotFoundError:pass
if not result.get('passed'):raise SystemExit(1)
