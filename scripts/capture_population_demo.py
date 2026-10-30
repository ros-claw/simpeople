"""Bookmark real wall-clock footage while controlling a separate population run.

The benchmark camera is never touched. All waiting remains in the source video;
the companion editor selects labelled intervals without speeding up the footage.
"""
import argparse
import json
from pathlib import Path
import signal
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from simpeople.tools.client import call as rpc

p=argparse.ArgumentParser()
p.add_argument('--run-id',required=True)
p.add_argument('--endpoint',default='http://127.0.0.1:8770')
a=p.parse_args()
d=ROOT/'runs'/a.run_id
serial=0
sections=[]
checks={}
deadline=time.monotonic()+3600
while not (d/'ready.json').exists():
    if time.monotonic()>deadline:raise TimeoutError('demo startup')
    time.sleep(1)
log=(d/'demo_calls.jsonl').open('w',buffering=1)

def call(method,params=None):
    global serial
    serial+=1
    params=dict(params or {})
    if method not in {'get_state','inspect_scene'}:params.setdefault('request_id',f'demo-{serial}')
    result=rpc('people.'+method,params,a.endpoint)
    log.write(json.dumps({'wall_time':time.time(),'method':method,'params':params,'result':result})+'\n')
    return result

def until(fn,seconds=2400):
    limit=time.monotonic()+seconds
    while time.monotonic()<limit:
        result=fn()
        if result:return result
        time.sleep(1)
    raise TimeoutError('demo observation timed out')

def step(actor):
    task=actor.get('task') or {}
    steps=task.get('steps',[])
    index=task.get('step_index',0)
    return steps[index] if index<len(steps) else {}

def find(predicate):
    return next((x for x in call('get_state')['actors'] if predicate(x)),None)

def speed(actor):return (actor.get('observation') or {}).get('speed_mps',0)

def section(label,seconds,actor_id=None):
    params={'mode':'camera','view':'follow' if actor_id else 'overview'}
    if actor_id:params['actor_id']=actor_id
    call('record',params)
    # The next synchronous frame is guaranteed to use the selected camera.
    time.sleep(.7)
    start=call('get_state')
    bookmark={'label':label,'actor_id':actor_id,'start_wall_time':time.time(),
              'start_sim_time':start['sim_time'],'requested_wall_seconds':seconds}
    time.sleep(seconds)
    end=call('get_state')
    bookmark.update(end_wall_time=time.time(),end_sim_time=end['sim_time'])
    sections.append(bookmark)
    (d/'demo_bookmarks.json').write_text(json.dumps({'run_id':a.run_id,'sections':sections},indent=2)+'\n')

try:
    initial=call('get_state')
    checks['actual_population_count']=len(initial['actors'])
    assert len(initial['actors'])==30
    section('30 PEOPLE / overview / measured wall time',18)
    walking=until(lambda:find(lambda x:.6<speed(x)<1.5 and step(x).get('action')=='move_to'))
    section('WALK / full body and feet',12,walking['actor_id'])
    queued=until(lambda:find(lambda x:step(x).get('action')=='queue' and x['task']['step_phase']=='serving' and speed(x)<.15))
    section('QUEUE / real service and spacing',12,queued['actor_id'])
    seated=until(lambda:find(lambda x:step(x).get('action')=='sit' and x['task']['step_phase']=='holding'))
    section('SIT / actual seated pose',12,seated['actor_id'])
    def jogging(x):
        joints=(x.get('observation') or {}).get('joints_m',{})
        return (step(x).get('gait')=='run' and speed(x)>2.2 and
                all(joints.get(tag,[0,0,0])[2]>.12 for tag in ['LeftFoot','RightFoot']))
    runner=until(lambda:find(jogging))
    section('NATIVE JOG / actual movement',14,runner['actor_id'])
    section('SHARED ROUTES / overview',14)
    controlled=until(lambda:find(lambda x:speed(x)>.5 and step(x).get('action')=='move_to' and not x['seat'] and not x['seat_cleanup_pending']))
    aid=controlled['actor_id'];old=controlled['task']['task_id']
    call('record',{'mode':'camera','view':'follow','actor_id':aid})
    first=call('move_to',{'actor_id':aid,'target':[-15,-2,0]})['task_id']
    assert call('get_state',{'task_id':old})['status']=='cancelled'
    until(lambda:find(lambda x:x['actor_id']==aid and speed(x)>.4),300)
    section('AGENT / first new destination',10,aid)
    changed=call('move_to',{'actor_id':aid,'target':[15,-2,0]})['task_id']
    assert call('get_state',{'task_id':first})['status']=='cancelled'
    until(lambda:find(lambda x:x['actor_id']==aid and speed(x)>.4),300)
    section('AGENT / redirect while moving',12,aid)
    call('cancel',{'task_id':changed})
    stopped=until(lambda:(s if (s:=call('get_state',{'task_id':changed}))['status'] in {'cancelled','failed'} else None),120)
    assert stopped['status']=='cancelled' and stopped['observation']['speed_mps']<.15
    checks['redirect_and_cancel_with_actual_settlement']=True
    section('AGENT / cancelled and stopped',8,aid)
    section('30 PEOPLE / continuing local activities',10)
except Exception:
    checks['error']=traceback.format_exc()
    traceback.print_exc()
finally:
    checks['sections']=len(sections)
    (d/'demo_acceptance.json').write_text(json.dumps(checks,indent=2)+'\n')
    log.close()
    ready=json.loads((d/'ready.json').read_text())
    pid=ready['pid']
    try:
        cmd=Path(f'/proc/{pid}/cmdline').read_bytes()
        if b'kit_main.py' in cmd and a.run_id.encode() in cmd:
            import os
            os.kill(pid,signal.SIGTERM)
    except FileNotFoundError:pass
    print(json.dumps(checks,indent=2),flush=True)
if 'error' in checks:raise SystemExit(1)
