"""Real narrow-door, queue, moving-obstacle and follow tests via the live bridge."""
import argparse
import json
import math
from pathlib import Path
import sys
import time
import traceback
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from simpeople.tools.client import call as rpc

parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True)
parser.add_argument('--endpoint',default='http://127.0.0.1:8769');args=parser.parse_args()
root=Path(__file__).resolve().parents[1];directory=root/'runs'/args.run_id
log=(directory/'interaction_calls.jsonl').open('a',buffering=1);checks={};serial=0

def call(method,p=None):
    global serial
    p=dict(p or {});serial+=1
    if method not in {'get_state','inspect_scene','list_assets','list_actions','validate_activity'}:
        p.setdefault('request_id',f'interaction-{serial}')
    result=rpc('people.'+method,p,args.endpoint)
    log.write(json.dumps({'wall_time':time.time(),'method':method,'params':p,'result':result})+'\n')
    return result

def until(fn,timeout=180):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        r=fn()
        if r:return r
        time.sleep(.15)
    raise TimeoutError('interaction condition timed out')

def state(tid):return call('get_state',{'task_id':tid})
def done(tid):return until(lambda:(s if (s:=state(tid))['status'] in {'succeeded','failed','cancelled'} else None))
def activity(actor,steps):return call('run_activity',{'actor_id':actor,'steps':steps})['task_id']
def move(goal,**more):return {'action':'move_to','target':goal,**more}

try:
    call('inspect_scene')
    for aid,point in [('west',[-4,-10,0]),('east',[4,-10,0])]:call('spawn',{'actor_id':aid,'spawn_anchor':point})
    west=activity('west',[move('door_east',resource_id='narrow_door'),move([5,-8,0])])
    east=activity('east',[move('door_west',resource_id='narrow_door'),move([-5,-8,0])])
    assert done(west)['status']=='succeeded'
    assert done(east)['status']=='succeeded';checks['T11_opposing_narrow_door']=True
    call('reset')
    queue_tasks=[]
    for i in range(3):
        aid=f'queued_{i}';home=[-18+i*1.5,-20,0]
        call('spawn',{'actor_id':aid,'spawn_anchor':home})
        queue_tasks.append(activity(aid,[{'action':'queue','target':'queue_0','duration_s':1.5},move(home)]))
    for tid in queue_tasks:assert done(tid)['status']=='succeeded'
    checks['queue_three_advance_and_clear']=True
    call('reset')
    call('move_prop',{'prop_id':'movable_box','position_m':[1.5,7,.65]})
    call('spawn',{'actor_id':'blocked_actor','spawn_anchor':[-5,0,0]})
    blocked=activity('blocked_actor',[move([6,0,0],timeout_s=30)])
    until(lambda:state(blocked)['observation'].get('position_m',[0])[0]>-3)
    moved=call('move_prop',{'prop_id':'movable_box','position_m':[1.5,0,.65]})
    blocked_result=done(blocked)
    assert blocked_result['status']=='succeeded' or (blocked_result['status']=='failed' and
           blocked_result['error']['code'] in {'TARGET_BLOCKED','BACKEND_TASK_FAILED','TIMEOUT','TARGET_UNREACHABLE'})
    checks['T12_dynamic_obstacle']={'terminal':blocked_result['status'],'error':blocked_result.get('error')}
    call('reset');call('move_prop',{'prop_id':'movable_box','position_m':[-1,0,.65]})
    call('spawn',{'actor_id':'follower','spawn_anchor':[-5,-1.5,0]})
    follow=activity('follower',[{'action':'follow','target':'movable_box','duration_s':12,'distance_m':2}])
    until(lambda:state(follow)['status']=='running')
    start=state(follow)['observation']['position_m'];start_sim=call('inspect_scene')['sim_time']
    for i,point in enumerate([[1,-1,.65],[3,-2,.65],[5,-2,.65]]):
        until(lambda:call('inspect_scene')['sim_time']>=start_sim+(i+1)*2)
        call('move_prop',{'prop_id':'movable_box','position_m':point})
    follow_result=done(follow)
    assert follow_result['status']=='succeeded'
    assert math.dist(start[:2],follow_result['observation']['position_m'][:2])>1
    assert follow_result['observation']['speed_mps']<.15
    checks['follow_moving_kinematic_object']=True
    # A stop requested while paused must apply on resume, before the old action can resume.
    changing=activity('follower',[move([-10,-2,0])])
    until(lambda:state(changing)['observation']['speed_mps']>.3)
    call('pause');call('cancel',{'task_id':changing});call('resume')
    assert done(changing)['status']=='cancelled';checks['cancel_while_paused']=True
    call('reset')
except Exception:
    checks['error']=traceback.format_exc();traceback.print_exc()
finally:
    log.close();(directory/'interaction_acceptance.json').write_text(json.dumps(checks,indent=2))
    print(json.dumps(checks,indent=2))
if 'error' in checks:raise SystemExit(1)
