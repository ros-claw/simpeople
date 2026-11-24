import copy
from simpeople.core.traffic import ReservationGrid,FairGate
from simpeople.core.candidate_paths import alternative,conflicts,destination,goal_leases


def make():
    nodes={(x,y) for x in range(5) for y in range(-2,3)}
    return ReservationGrid(nodes,{n:[m for m in sorted(nodes) if abs(m[0]-n[0])+abs(m[1]-n[1])==1] for n in nodes})


def test_rejection_counterexample_matches_actual_clearance_and_keeps_initial_escape_exception():
    grid=make();points=[[0,0,0],[1.25,0,0]];positions={'a':[0,0,0],'b':[.625,.85,0]}
    proof=conflicts(grid,'a',points,positions)
    assert not proof['physical_feasible']
    assert proof['body_conflicts'][0]['closest_fraction']==.5
    assert proof['body_conflicts'][0]['distance_m']==.85
    assert proof['body_conflicts'][0]['position_m']==positions['b']
    assert conflicts(grid,'a',[[0,0,0],[-1.25,0,0]],{'b':[.2,0,0]})['physical_feasible']


def test_failed_chord_gets_one_verified_detour_without_acquiring_or_releasing_any_claim():
    grid=make();positions={'a':[0,0,0],'b':[.625,.85,0]};blocked=grid.blocked('a',positions)
    old=grid.path((0,0),(4,0),blocked);original=destination(grid,old,[0,0,0],[5,0,0])
    assert not grid.can_reserve('a',grid.sweep([0,0,0],original),positions,[0,0,0],original)
    before=copy.deepcopy(grid.claims);connections=[]
    def connection(a,b):connections.append((a,b));return True
    repair=alternative(grid,'a',[0,0,0],[5,0,0],positions,(0,0),[(4,0)],blocked,{},connection)
    assert repair and repair['original_goal_m']==[5,0,0] and repair['path'][1]!=(1,0)
    assert grid.can_reserve('a',grid.sweep([0,0,0],repair['destination_m']),positions,[0,0,0],repair['destination_m'])
    assert grid.claims==before and len(connections)==1


def test_no_path_and_occupied_goal_cannot_be_relabelled_as_progress():
    grid=make();positions={'a':[0,0,0],'b':[5,0,0]};blocked=grid.blocked('a',positions)
    assert alternative(grid,'a',[0,0,0],[5,0,0],positions,(0,0),[(4,0),(4,1)],blocked,{},lambda a,b:True) is None
    assert not grid.claims


def test_actual_root_connector_and_native_connection_remain_mandatory():
    grid=make();positions={'a':[0,0,0]}
    assert alternative(grid,'a',[0,0,0],[5,0,0],positions,(0,0),[(4,0)],set(),{},lambda a,b:False) is None
    grid.claims['other']={(1,0)}
    repair=alternative(grid,'a',[0,0,0],[5,0,0],positions,(0,0),[(4,0)],grid.blocked('a',positions),{},lambda a,b:True)
    assert repair and not grid.sweep([0,0,0],repair['destination_m']) & grid.claims['other']


def test_safe_geometry_does_not_bypass_the_older_fairness_guard():
    grid=make();gate=FairGate();gate.request('older','b',{(0,-1)},0);gate.request('new','a',{(0,-1)},1)
    repair=alternative(grid,'a',[0,0,0],[5,0,0],{'b':[.625,.85,0]},(0,0),[(4,0)],set(),{},lambda a,b:True)
    assert repair and not gate.allowed('new',grid.sweep([0,0,0],repair['destination_m']))
    assert gate.pending['older']['since']==0 and not grid.claims


def test_recorded_cancelled_body_requires_a_retreat_near_the_floor_boundary():
    nodes={(x,y) for x in range(-12,1) for y in range(-17,-12)}
    grid=ReservationGrid(nodes,{n:[m for m in sorted(nodes) if abs(m[0]-n[0])+abs(m[1]-n[1])==1] for n in nodes})
    root=[-7.492166519165039,-21.25188636779785,0]
    body=[-7.04322624206543,-20.40911293029785,0];goal=[-2.3,-20,0]
    proof=conflicts(grid,'q_06',[root,[-3.75,-21.25,0]],{'q_08':body})
    assert .842<proof['body_conflicts'][0]['distance_m']<.844
    assert all(sum((p[i]-body[i])**2 for i in range(2))**.5>.9 for p in [root,[-3.75,-21.25,0]])
    positions={'q_06':root,'q_08':body};blocked=grid.blocked('q_06',positions)
    repair=alternative(grid,'q_06',root,goal,positions,(-6,-17),[(-2,-16)],blocked,{(-7,-17):4},lambda a,b:True)
    assert repair and repair['path'][1]==(-7,-17) and repair['original_goal_m']==goal


def test_held_destination_is_distinct_from_free_approach_and_own_lease():
    grid=make();grid.claims={'a':{(4,0)},'previous':{(4,0),(3,0)},'elsewhere':{(0,2)}}
    assert goal_leases(grid,'a',[5,0,0])=={'previous':[(4,0)]}
    grid.release('previous');assert not goal_leases(grid,'a',[5,0,0])
