"""Run actual CLI controls against a live Kit process and preserve every reply.

This is a tool integration/acceptance driver, not a simulated agent transcript.
The current agent invokes it during implementation; no LLM messages are fabricated.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import time
import traceback

parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);args=parser.parse_args()
root=Path(__file__).resolve().parents[1];directory=root/'runs'/args.run_id
log=(directory/'agent_cli_calls.jsonl').open('a',buffering=1)
checks={}

def call(method,params=None):
    wall=time.time();params=params or {}
    p=subprocess.run(['simpeople','call','people.'+method,'--json',json.dumps(params)],capture_output=True,text=True,timeout=40)
    result=json.loads(p.stdout)
    log.write(json.dumps({'wall_time':wall,'method':method,'params':params,'returncode':p.returncode,'response':result})+'\n')
    if p.returncode:raise RuntimeError(result)
    return result

def until(predicate,timeout=90):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        result=predicate()
        if result:return result
        time.sleep(.15)
    raise TimeoutError('acceptance condition did not become true')

def terminal(tid):
    def poll():
        r=call('get_state',{'task_id':tid})
        return r if r['status'] in {'succeeded','failed','cancelled'} else None
    return until(poll)

def activity(rid,steps,actor='agent_01'):
    return call('run_activity',{'request_id':rid,'actor_id':actor,'steps':steps})['task_id']

try:
    scene=call('inspect_scene')
    assert scene['navmesh_available'] and scene['frame_spec']['up_axis']=='Z'
    call('spawn',{'request_id':'agent-spawn-01','actor_id':'agent_01','spawn_anchor':'entrance'})
    replay=call('spawn',{'request_id':'agent-spawn-01','actor_id':'agent_01','spawn_anchor':'entrance'})
    assert replay['idempotent_replay'];checks['T13_duplicate_spawn']=True
    call('list_actions',{'actor_id':'agent_01'})
    old=activity('agent-go-workbench',[{'action':'move_to','target':'workbench_a'},{'action':'wait','duration_s':30}])
    def moved():
        r=call('get_state',{'task_id':old});o=r['observation']
        return r if o and o['ready'] and math.dist(o['position_m'][:2],[-5,-3])>.8 else None
    until(moved)
    new=activity('agent-change-chair',[{'action':'move_to','target':'chair_approach'},{'action':'wait','duration_s':20}])
    assert call('get_state',{'task_id':old})['status']=='cancelled'
    until(lambda:call('get_state',{'task_id':new})['observation']['speed_mps']>.4)
    call('cancel',{'request_id':'agent-cancel-changing-goal','task_id':new})
    r=terminal(new);assert r['status']=='cancelled' and r['step_index']==0
    assert r['observation']['speed_mps']<.15
    checks['T05_mid_motion_replacement']=True;checks['T06_cancel_stops_successor']=True
    waiting=activity('agent-wait-pause',[{'action':'wait','duration_s':3}])
    until(lambda:call('get_state',{'task_id':waiting})['status']=='running')
    before=call('pause',{'request_id':'agent-pause'})['sim_time']
    time.sleep(2)
    after=call('inspect_scene')['sim_time']
    assert abs(after-before)<.04
    assert call('get_state',{'task_id':waiting})['status']=='paused'
    call('resume',{'request_id':'agent-resume'})
    assert terminal(waiting)['status']=='succeeded';checks['T07_pause_resume']=True
    unreachable=activity('agent-unreachable',[{'action':'move_to','target':'unreachable','timeout_s':10}])
    r=terminal(unreachable);assert r['status']=='failed' and r['error']['code']=='TARGET_UNREACHABLE'
    checks['T04_unreachable']=True
    call('spawn',{'request_id':'agent-spawn-02','actor_id':'agent_02','spawn_anchor':[-4,-4.5,0]})
    one=activity('agent-seat-1',[{'action':'sit','target':'chair_01','duration_s':2},{'action':'leave_seat'}])
    two=activity('agent-seat-2',[{'action':'sit','target':'chair_01','duration_s':2},{'action':'leave_seat'}],actor='agent_02')
    until(lambda:call('get_state',{'task_id':two})['status']=='blocked')
    assert terminal(one)['status']=='succeeded'
    assert terminal(two)['status']=='succeeded';checks['T10_seat_competition']=True
    sitting=activity('agent-seat-cancel',[{'action':'sit','target':'chair_01','duration_s':20},{'action':'move_to','target':'exit_a'}])
    until(lambda:call('get_state',{'task_id':sitting})['step_phase']=='holding')
    call('cancel',{'request_id':'agent-cancel-seat','task_id':sitting})
    assert terminal(sitting)['status']=='cancelled'
    assert call('inspect_scene')['resources']['owners']=={}
    checks['T06_cancel_while_seated']=True
    active=activity('agent-reset-active',[{'action':'move_to','target':'point_a'}])
    prior=call('inspect_scene')['episode_id']
    reset=call('reset',{'request_id':'agent-reset','episode_id':prior})
    assert reset['episode_id']!=prior
    assert call('get_state',{'task_id':active})['status']=='cancelled'
    assert call('get_state',{'task_id':active})['observation'] is None
    assert call('inspect_scene')['actors']==[];checks['T08_reset']=True
    checks['T15_actual_cli_control']=True
except Exception:
    checks['error']=traceback.format_exc();traceback.print_exc()
finally:
    log.close();(directory/'agent_cli_acceptance.json').write_text(json.dumps(checks,indent=2))
    print(json.dumps(checks,indent=2))
if 'error' in checks:raise SystemExit(1)
