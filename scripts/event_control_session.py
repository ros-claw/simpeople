"""Continuous life cycle, safe external-event responses, redirection and cancellation."""
import argparse
import json
import math
from pathlib import Path
import sys
import time
import traceback
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simpeople.tools.client import call as rpc
parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True)
parser.add_argument('--endpoint',default='http://127.0.0.1:8769');parser.add_argument('--camera-follow',action='store_true');args=parser.parse_args()
directory=ROOT/'runs'/args.run_id;serial=0;checks={}
log=(directory/'event_control_calls.jsonl').open('w',buffering=1)
def call(method,p=None):
    global serial
    serial+=1;p=dict(p or {})
    if method not in {'inspect_scene','get_state','list_actions'}:p.setdefault('request_id',f'event-control-{serial}')
    result=rpc('people.'+method,p,args.endpoint)
    log.write(json.dumps({'wall_time':time.time(),'method':method,'params':p,'result':result})+'\n')
    return result

def until(fn,timeout=240):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=fn()
        if value:return value
        time.sleep(.15)
    raise TimeoutError('event control condition timed out')
def state(tid):return call('get_state',{'task_id':tid})
def done(tid):return until(lambda:(s if (s:=state(tid))['status'] in {'succeeded','failed','cancelled'} else None))
def activity(steps):return call('run_activity',{'actor_id':'worker','steps':steps})['task_id']
def moving(tid):return until(lambda:state(tid)['observation'].get('speed_mps',0)>.3)
def event_state(eid):return next(x for x in call('get_state')['events'] if x['event_id']==eid)['results'][0]
def event_done(eid):return until(lambda:(s if (s:=event_state(eid))['status'] in {'succeeded','failed','cancelled','superseded'} else None))
def event(kind,**extra):return call('signal_event',{'kind':kind,'actor_ids':['worker'],'duration_s':1,**extra})['event_id']
def move(target,**extra):return {'action':'move_to','target':target,**extra}
try:
    call('spawn',{'actor_id':'worker','spawn_anchor':'entrance'})
    if args.camera_follow:call('record',{'mode':'camera','view':'follow','actor_id':'worker'})
    life=json.loads((ROOT/'configs/single_life_cycle.json').read_text())['steps']
    task=activity(life);assert done(task)['status']=='succeeded';checks['continuous_life_cycle']=True
    baseline=activity([move([16,0,0]),{'action':'wait','duration_s':5}]);moving(baseline)
    eid=event('robot_nearby',duration_s=2)
    assert event_done(eid)['status']=='succeeded'
    current=call('get_state',{'actor_id':'worker'})['actors'][0]['task']
    assert current['source']=='event_restore' and current['task_id']!=baseline
    checks['robot_nearby_restored_remaining_activity']=True
    eid=event('passage_blocked',target=[-2,0,0]);assert event_done(eid)['status']=='succeeded'
    checks['passage_blocked_explicit_detour']=True
    seated=activity([{'action':'sit','target':'chair_01','duration_s':3},{'action':'leave_seat'},{'action':'wait','duration_s':4}])
    until(lambda:state(seated).get('step_phase')=='holding')
    eid=event('call_person',target=[10,0,0])
    until(lambda:event_state(eid)['status']=='deferred')
    assert call('get_state',{'actor_id':'worker'})['actors'][0]['task']['task_id']==seated
    assert event_done(eid)['status']=='succeeded'
    checks['call_person_deferred_until_seat_release']=True
    eid=event('region_closed',target=[-10,0,0]);assert event_done(eid)['status']=='succeeded'
    final=call('get_state',{'actor_id':'worker'})['actors'][0]['task'];assert final['source']=='event'
    start=call('get_state')['sim_time'];until(lambda:call('get_state')['sim_time']>start+2)
    assert call('get_state',{'actor_id':'worker'})['actors'][0]['task']['task_id']==final['task_id']
    checks['region_closed_holds_for_new_instruction']=True
    old=activity([move([16,0,0])]);moving(old)
    changed=activity([move([-10,-5,0])]);assert state(old)['status']=='cancelled';moving(changed)
    call('cancel',{'task_id':changed});assert done(changed)['status']=='cancelled'
    checks['real_redirect_and_cancel_in_continuous_video']=True
except Exception:
    checks['error']=traceback.format_exc();traceback.print_exc()
finally:
    log.close();(directory/'event_control_acceptance.json').write_text(json.dumps(checks,indent=2)+'\n')
    print(json.dumps(checks,indent=2),flush=True)
if 'error' in checks:raise SystemExit(1)
