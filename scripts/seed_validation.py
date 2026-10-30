"""Additional-seed validation with explicit requested and formal observation windows."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from summarize_run import summarize

def wait_closed(directory):
    deadline=time.monotonic()+12*3600
    while time.monotonic()<deadline:
        if all((directory/n).exists() for n in ['completion.json','metrics.json','population.json']):
            try:
                pid=json.loads((directory/'ready.json').read_text())['pid']
                active=b'kit_main.py' in Path(f'/proc/{pid}/cmdline').read_bytes()
            except FileNotFoundError:active=False
            if not active:return
        time.sleep(2)
    raise TimeoutError(directory.name)

def validate(directory):
    wait_closed(directory)
    summary=summarize(directory)
    subprocess.run([sys.executable,str(ROOT/'scripts/check_framing.py'),str(directory)],check=True)
    framing=json.loads((directory/'framing_audit.json').read_text())
    quality=json.loads((directory/'quality_audit.json').read_text())
    completion=json.loads((directory/'completion.json').read_text())
    config=json.loads((directory/'config.json').read_text())
    checks={'clean_exit':completion['exit_code']==0,
            'requested_actor_count':summary['richness']['instances']==summary['configuration']['people'],
            'requested_observation_window_met':summary['performance']['sim_elapsed_s']+1/30>=config['duration'],
            'measurement_at_least_120_wall_seconds':summary['performance']['measurement_wall_s']>=120,
            'all_actors_participated':summary['richness']['moving_participants']==summary['richness']['instances'],
            'every_actor_completed_role_cycle':summary['minimum_role_cycles']>=1,
            'no_suspended_actors':not summary['suspended_actors'],
            'no_geometry_flags':quality['critical_count']==0,
            'no_offline_overlaps':not summary['trajectory_proxies']['sustained_overlap_segments'],
            'no_root_discontinuities':not summary['trajectory_proxies']['root_discontinuities'],
            'all_initial_actors_in_frame':framing['all_initial_actor_extents_inside']}
    programs=[]
    for line in (directory/'events.jsonl').open():
        e=json.loads(line)
        if e['kind']=='task_accepted' and e['task']['source']=='scheduler':
            programs.append({'actor_id':e['task']['actor_id'],'steps':e['task']['steps']})
    formal_duration={10:600,30:900,50:600,100:120}.get(config['people'])
    full_window=formal_duration is not None and config['duration']>=formal_duration
    scope=('full-duration additional-seed validation' if full_window else
           'shorter additional-seed validation; does not replace the full-duration gate')
    result={'run_id':directory.name,'seed':summary['configuration']['seed'],'scope':scope,
            'requested_duration_sim_s':config['duration'],'formal_duration_sim_s':formal_duration,
            'full_duration_window_requested':full_window,
            'sim_elapsed_s':summary['performance']['sim_elapsed_s'],'checks':checks,'passed':all(checks.values()),
            'measurement_passed':all(value for key,value in checks.items() if key!='every_actor_completed_role_cycle'),
            'role_cycle_coverage_complete':checks['every_actor_completed_role_cycle'],
            'summary':'acceptance_summary.json','scheduled_programs_sha256':hashlib.sha256(json.dumps(programs,sort_keys=True).encode()).hexdigest(),
            'task_status_counts':summary['task_status_counts'],'failures_by_code':summary['failures_by_code']}
    (directory/'seed_validation.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True)
    p.add_argument('--next-run');p.add_argument('--next-seed',type=int,default=99)
    p.add_argument('--people',type=int,default=30);p.add_argument('--duration',type=float,default=300)
    p.add_argument('--gpu',type=int,default=0);p.add_argument('--port',type=int,default=8769)
    a=p.parse_args()
    first=validate(ROOT/'runs'/a.run_id);print(json.dumps(first),flush=True)
    if a.next_run:
        if not first['checks']['no_geometry_flags'] or not first['checks']['no_suspended_actors']:
            raise SystemExit('Current population needs repair; additional seed was not launched.')
        with (ROOT/'.runtime'/(a.next_run+'-driver.log')).open('w') as log:
            code=subprocess.call([sys.executable,'-m','simpeople.tools.cli','run','--scenario','industrial_life','--people',str(a.people),
                  '--duration',str(a.duration),'--seed',str(a.next_seed),'--gpu',str(a.gpu),'--port',str(a.port),'--run-id',a.next_run],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        if code:raise SystemExit(code)
        second=validate(ROOT/'runs'/a.next_run);print(json.dumps(second),flush=True)
