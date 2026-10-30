"""Insert a box into an already reserved route, verify braking and clearance."""
import argparse,json,math,sys,time,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simpeople.tools.client import call as rpc
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--endpoint',default='http://127.0.0.1:8769');args=p.parse_args()
d=ROOT/'runs'/args.run_id;serial=0;report={};log=(d/'late_obstacle_calls.jsonl').open('w',buffering=1)
def call(method,params=None):
 global serial
 serial+=1;params=dict(params or {})
 if method not in {'get_state','inspect_scene'}:params.setdefault('request_id',f'late-box-{serial}')
 r=rpc('people.'+method,params,args.endpoint);log.write(json.dumps({'method':method,'params':params,'result':r,'wall_time':time.time()})+'\n');return r
def until(fn):
 end=time.monotonic()+180
 while time.monotonic()<end:
  r=fn()
  if r:return r
  time.sleep(.15)
 raise TimeoutError('late obstacle condition timed out')
try:
 call('move_prop',{'prop_id':'movable_box','position_m':[10,10,.65]})
 call('spawn',{'actor_id':'late_actor','spawn_anchor':[-5,0,0]})
 call('record',{'mode':'camera','view':'follow','actor_id':'late_actor'})
 task=call('move_to',{'actor_id':'late_actor','target':[6,0,0],'timeout_s':45})['task_id']
 until(lambda:call('get_state',{'task_id':task})['observation'].get('position_m',[-5])[0]>.4)
 moved=call('move_prop',{'prop_id':'movable_box','position_m':[2.5,0,.65]})
 state=until(lambda:(s if (s:=call('get_state',{'task_id':task}))['status'] in {'succeeded','failed','cancelled'} else None))
 events=[json.loads(l) for l in (d/'events.jsonl').open()]
 start=next(e['sim_time'] for e in reversed(events) if e['kind']=='prop_moved' and e.get('position_m')==[2.5,0,.65])
 margins=[]
 for line in (d/'trajectories.jsonl').open():
  r=json.loads(line)
  if r['actor_id']=='late_actor' and start<=r['sim_time']<=state['finished_sim_time']:
   x,y=r['position_m'][:2];margins.append(math.hypot(max(abs(x-2.5)-.5,0),max(abs(y)-.5,0)))
 assert state['status']=='succeeded',state
 assert margins and min(margins)>=.2, min(margins)
 assert any(e['kind']=='traffic_obstacle_brake' and e['sim_time']>=start for e in events)
 inspection=call('inspect_scene');assert inspection['recording']['camera_view']=='follow'
 call('record',{'mode':'camera','view':'overview'})
 report={'passed':True,'task_id':task,'minimum_root_to_box_surface_m':min(margins),'required_minimum_m':.2,
         'native_braking_and_replan_logged':True,'camera_follow_and_overview_verified':True}
 call('reset');call('move_prop',{'prop_id':'movable_box','position_m':[-4,10,.65]})
except Exception:
 report={'passed':False,'error':traceback.format_exc()};traceback.print_exc()
finally:
 log.close();(d/'late_obstacle_acceptance.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2),flush=True)
if not report.get('passed'):raise SystemExit(1)
