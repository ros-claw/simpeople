"""Replay a frozen case through the loopback bridge, recording all outcomes."""
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simpeople.core.workloads import WorkloadReplay
from simpeople.tools.client import call
class SimPeopleClient:
    def __init__(self,endpoint):self.endpoint=endpoint
    def call(self,method,params):return call(method,params,self.endpoint)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('case');p.add_argument('--endpoint',default='http://127.0.0.1:8768');p.add_argument('--output',required=True);p.add_argument('--wall-budget-s',type=float,default=3600);a=p.parse_args()
    case=json.loads(Path(a.case).read_text())
    if any(case.get(k) for k in ['events','checkpoints','runtime_policy','stop_when_complete']):raise SystemExit('This case requires scripts/bench_native_runtime.py; the live replay CLI cannot apply startup policies or native fault checkpoints.')
    client=SimPeopleClient(a.endpoint);origin=client.call('get_state',{})['sim_time'];replay=WorkloadReplay(case,client,origin);end=time.monotonic()+a.wall_budget_s
    while time.monotonic()<end:
        now=client.call('get_state',{})['sim_time']-origin;replay.tick(now)
        if now>=case['duration_s']:break
        time.sleep(.05)
    folder=Path(a.output);folder.mkdir(exist_ok=False,parents=True);(folder/'outcomes.json').write_text(json.dumps(replay.summary(),indent=2));(folder/'workload.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in replay.trace))
