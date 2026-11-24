"""Freeze complete requests; independent actor/cycle seeds do not depend on finishes."""
import argparse,json,random,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simpeople.core.workloads import actor_cycle_seed,validate_case,case_hash
from simpeople.core.population import Population,ROLES,home_slot
def smoke(count=10):
    actors=[{'actor_id':f'bench_{i:03}','asset_id':'default','spawn_anchor':home_slot(i)} for i in range(count)];requests=[]
    for cycle in range(2):
        for i,a in enumerate(actors):
            aid=a['actor_id'];home=a['spawn_anchor'];inside=[home[0],home[1]+2.5,0] if i<14 else home
            requests.append({'request_case_id':f'{aid}_cycle{cycle}','actor_id':aid,'at_s':0 if cycle else i*.1,'deadline_s':90,
                'depends_on':[f'{aid}_cycle{cycle-1}'] if cycle else [],
                'steps':[{'action':'move_to','target':inside,'timeout_s':35},{'action':'wait','duration_s':1},{'action':'move_to','target':home,'timeout_s':35}]})
    return {'schema_version':'simpeople.benchmark.v1','case_id':f'smoke{count}_closed_v1','category':'ordinary','scene':{'id':'industrial','revision':'industrial_source_B0'},
        'actors':actors,'requests':requests,'submission_mode':'closed_loop','busy_policy':'queue','max_pending_per_actor':2,'duration_s':90,'finite':True,'capture_profile':'full'}
def freeze_population(semantics,count=50,cycles=2,seed=17):
    class Backend:
        def resolve_target(self,key):return semantics[key]['position_m']
    class Engine:backend=Backend()
    pop=Population(Engine(),seed);actors=[]
    for i in range(count):
        aid=f'person_{i+1:03}';assignment={'role':ROLES[i%len(ROLES)],'index':i,'home_m':home_slot(i)};pop.assignments[aid]=assignment;actors.append({'actor_id':aid,'asset_id':'default','spawn_anchor':home_slot(i),'role':assignment['role']})
    requests=[]
    for cycle in range(cycles):
        for aid,assignment in pop.assignments.items():
            rng=random.Random(actor_cycle_seed(seed,aid,cycle));pop.rng=rng;arrival=rng.uniform(0,8) if cycle==0 else 0
            requests.append({'request_case_id':f'{aid}_cycle{cycle}','actor_id':aid,'at_s':arrival,'deadline_s':600,'depends_on':[f'{aid}_cycle{cycle-1}'] if cycle else [],'steps':pop.program(assignment)})
    return {'schema_version':'simpeople.benchmark.v1','case_id':f'population{count}_closed_seed{seed}_v1','category':'ordinary','scene':{'id':'industrial','revision':hashlib.sha256(json.dumps(semantics,sort_keys=True).encode()).hexdigest()},'actors':actors,'requests':requests,'submission_mode':'closed_loop','busy_policy':'queue','max_pending_per_actor':2,'duration_s':600,'finite':True,'capture_profile':'full','seed_derivation':'sha256(seed:actor:cycle), independent of completion order'}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--semantics');p.add_argument('--output',default='benchmarks/workloads');a=p.parse_args();folder=Path(a.output);folder.mkdir(parents=True,exist_ok=True)
    semantics=json.loads(Path(a.semantics).read_text()) if a.semantics else None
    revision=hashlib.sha256(json.dumps(semantics,sort_keys=True).encode()).hexdigest() if semantics else None
    if revision is None:raise SystemExit('--semantics is required to freeze the scene revision')
    cases=[smoke()];cases[0]['scene']['revision']=revision
    if a.semantics:
        for n in [10,30,50]:cases.append(freeze_population(json.loads(Path(a.semantics).read_text()),n))
    c=smoke(2);c.update(case_id='open_queue2_v1',submission_mode='open_arrival');c['scene']['revision']=revision;c['requests']=[{**r,'depends_on':[],'at_s':0 if i<2 else .25} for i,r in enumerate(c['requests'])];cases.append(c)
    for c in cases:
        for r in c['requests']:r.update(expected_outcome='succeeded',think_s=0)
        validate_case(c);(folder/(c['case_id']+'.json')).write_text(json.dumps(c,indent=2)+'\n');print(c['case_id'],case_hash(c))
