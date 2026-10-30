"""Regress the exact construction-character/workbench corner rejection."""
import argparse,json,math,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simpeople.tools.client import call as rpc
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--endpoint',default='http://127.0.0.1:8769');args=p.parse_args()
d=ROOT/'runs'/args.run_id;log=(d/'boundary_calls.jsonl').open('w',buffering=1);serial=0;report={}
def call(method,params=None):
 global serial
 serial+=1;params=dict(params or {})
 if method not in {'get_state','inspect_scene'}:params.setdefault('request_id',f'boundary-{serial}')
 result=rpc('people.'+method,params,args.endpoint);log.write(json.dumps({'method':method,'params':params,'result':result,'wall_time':time.time()})+'\n');return result
try:
 call('spawn',{'actor_id':'construction','asset_id':'male_adult_construction_02','spawn_anchor':[1.25,1.25,0]})
 points=[[1.25,3.75,0],[5,3.75,0],[12.7,12.7,0]]
 results=[]
 for goal in points:
  task=call('move_to',{'actor_id':'construction','target':goal,'timeout_s':120})
  end=time.monotonic()+240
  while time.monotonic()<end:
   state=call('get_state',{'task_id':task['task_id']})
   if state['status'] in {'succeeded','failed','cancelled'}:break
   time.sleep(.2)
  assert state['status']=='succeeded',state
  observation=state['observation'];error=math.dist(goal[:2],observation['position_m'][:2])
  assert error<=.3 and observation['speed_mps']<.15
  results.append({'target':goal,'actual_position_m':observation['position_m'],'error_m':error,'task_id':task['task_id']})
 report={'passed':True,'results':results,'scope':'same construction model and exact workbench corner; measured positions, no teleport'}
except Exception:
 report={'passed':False,'error':traceback.format_exc()};traceback.print_exc()
finally:
 log.close();(d/'boundary_acceptance.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2),flush=True)
if not report.get('passed'):raise SystemExit(1)
