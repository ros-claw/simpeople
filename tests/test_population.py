import math
import pytest
from simpeople.core.population import Population,ROLES
from simpeople.core.errors import SimPeopleError

class Backend:
    def list_assets(self):return [{'asset_id':'default'}]
    def resolve_target(self,name):return [0,0,0]

class Engine:
    sim_time=0
    def __init__(self):self.backend=Backend();self.spawned=[]
    def cmd_spawn(self,p):self.spawned.append(p['actor_id']);return {'actor_id':p['actor_id']}

@pytest.mark.parametrize('count',[50,100])
def test_large_population_patrol_stops_cannot_mutually_block_at_shared_goals(count):
    population=Population(Engine(),17);population.populate({'count':count})
    stops=[]
    for assignment in population.assignments.values():
        if assignment['role']=='patrol':
            program=population.program(assignment)
            stops.extend(s['target'] for s in program[:4] if s['action']=='move_to')
    assert len({tuple(p) for p in stops})==len(stops)
    assert min(math.dist(a,b) for n,a in enumerate(stops) for b in stops[n+1:])>=2.5
    assert all(abs(v/1.25-round(v/1.25))<1e-9 for p in stops for v in p[:2])
    assert all(abs(v)<22 for p in stops for v in p[:2])

@pytest.mark.parametrize('count',[10,30])
def test_previously_accepted_low_count_patrol_recipe_is_preserved(count):
    population=Population(Engine(),42);population.populate({'count':count})
    for assignment in population.assignments.values():
        if assignment['role']=='patrol':
            i=assignment['index'];program=population.program(assignment)
            assert [s['target'] for s in program[:4] if s['action']=='move_to']==[
                [-17,-2+i%5*1.3,0],[-3+i%5*1.5,16.5,0],[17,-2+i%5*1.3,0]]

def test_unconfigured_patrol_capacity_is_rejected_before_creating_any_actor():
    engine=Engine();population=Population(engine,42)
    with pytest.raises(SimPeopleError):population.populate({'count':16,'roles':['patrol']})
    assert engine.spawned==[]

@pytest.mark.parametrize('count',[50,100])
def test_response_destinations_have_independent_grid_bays_clear_of_patrol_stops(count):
    population=Population(Engine(),42);result=population.populate({'count':count})
    stops=[];patrol=[]
    for assignment in population.assignments.values():
        program=population.program(assignment)
        if assignment['role']=='responder':stops.append(program[1]['target'])
        if assignment['role']=='patrol':patrol.extend(s['target'] for s in program[:4] if s['action']=='move_to')
    assert result['responder_stop_profile']=='independent-grid-v3'
    assert len(stops)==count//len(ROLES)
    assert min(math.dist(a,b) for n,a in enumerate(stops) for b in stops[n+1:])>=2.5
    assert min(math.dist(a,b) for a in stops for b in patrol)>=2.5
    assert all(abs(v/1.25-round(v/1.25))<1e-9 for p in stops for v in p[:2])

@pytest.mark.parametrize('count',[10,30])
def test_previously_accepted_low_count_response_stations_are_preserved(count):
    population=Population(Engine(),42);result=population.populate({'count':count})
    assert result['responder_stop_profile']=='legacy-three-station-v1'
    for assignment in population.assignments.values():
        if assignment['role']=='responder':
            assert population.program(assignment)[1]['target']==f"event_station_{assignment['index']%3}"

def test_unconfigured_response_capacity_is_rejected_before_creating_any_actor():
    engine=Engine();population=Population(engine,42)
    with pytest.raises(SimPeopleError):population.populate({'count':17,'roles':['responder']})
    assert engine.spawned==[]
