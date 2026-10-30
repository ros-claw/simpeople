from simpeople.core.traffic import ReservationGrid
from simpeople.core.quality import QualityAudit

def grid():
    nodes={(x,y) for x in range(-2,3) for y in range(-2,3)}
    return ReservationGrid(nodes,{n:[m for m in nodes if abs(m[0]-n[0])+abs(m[1]-n[1])==1] for n in nodes})

def test_opposing_corridors_are_exclusive_and_released():
    g=grid();positions={'a':[-2.5,0,0],'b':[2.5,0,0]}
    assert g.reserve('a',g.sweep(positions['a'],[0,0,0]),positions)
    assert not g.reserve('b',g.sweep(positions['b'],[0,0,0]),positions)
    g.release('a');assert g.reserve('b',g.sweep(positions['b'],[0,0,0]),positions)

def test_route_goes_around_stationary_person():
    g=grid();blocked=g.blocked('a',{'a':[-2.5,0,0],'seated':[0,0,0]})
    path=g.path((-2,0),(2,0),blocked)
    assert path and (0,0) not in path and any(n[1]!=0 for n in path)

def test_nearby_actors_can_separate_without_a_coarse_cell_deadlock():
    g=grid();positions={'a':[-.75,0,0],'b':[.75,0,0]}
    assert g.reserve('a',g.sweep(positions['a'],[-2.5,0,0]),positions,positions['a'],[-2.5,0,0])
    assert not g.reserve('b',g.sweep(positions['b'],[-1.25,0,0]),positions,positions['b'],[-1.25,0,0])

def test_geometry_alarm_requires_simulation_duration_and_emits_valid_event():
    events=[];audit=QualityAudit(lambda name,**p:events.append((name,p)))
    obs={'a':{'ready':True,'position_m':[0,0,0]},'b':{'ready':True,'position_m':[.2,0,0]}}
    audit.tick(0,obs,{})
    for _ in range(10):audit.tick(0,obs,{})
    assert not audit.flags
    audit.tick(.3,obs,{})
    assert len(audit.flags)==1 and events[0][0]=='quality_flag' and events[0][1]['issue']=='sustained_root_overlap'

def test_new_episode_can_reuse_actor_id_without_a_false_teleport_alarm():
    audit=QualityAudit();one={'a':{'ready':True,'position_m':[0,0,0]}}
    audit.tick(0,one,{},'first')
    audit.tick(.1,{'a':{'ready':True,'position_m':[10,0,0]}},{},'second')
    assert not audit.flags

def test_polyline_reservation_checks_turn_and_keeps_old_claim_on_failure():
    from simpeople.core.traffic import ReservationGrid
    g=ReservationGrid({(x,y) for x in range(8) for y in range(8)},{})
    g.claims['a']={(0,0)};g.claims['b']=g.footprint([2.5,2.5,0])
    old=g.claims['a'].copy()
    assert not g.reserve_polyline('a',[[0,0,0],[2.5,0,0],[2.5,5,0]],{'a':[0,0,0]})
    assert g.claims['a']==old
    g.release('b')
    assert not g.reserve_polyline('a',[[0,0,0],[2.5,0,0],[2.5,5,0]],{'a':[0,0,0],'b':[2.6,3,0]})
    assert g.claims['a']==old
    assert g.reserve_polyline('a',[[0,0,0],[2.5,0,0],[2.5,5,0]],{'a':[0,0,0],'b':[5,5,0]})
    assert g.footprint([2.5,5,0])<=g.claims['a']

def test_dense_native_samples_compress_without_losing_route_corner():
    from simpeople.core.traffic import simplify_polyline
    points=[[i*.001,0,0] for i in range(1001)]+[[1,i*.001,0] for i in range(1,1001)]
    assert simplify_polyline(points)==[[0,0,0],[1,0,0],[1,1,0]]
    assert simplify_polyline([[0,0,0],[.5,.2,0],[1,0,0]])==[[0,0,0],[.5,.2,0],[1,0,0]]

def test_lazy_navmesh_edges_validate_and_cache_without_crossing_hole():
    from simpeople.core.traffic import ReservationGrid,VerifiedLazyEdges
    calls=[];nodes={(x,y) for x in range(4) for y in range(3)}
    def valid(a,b):calls.append((a,b));return not (a[0]==1 and b[0]==2 or a[0]==2 and b[0]==1)
    edges=VerifiedLazyEdges(nodes,valid);g=ReservationGrid(nodes,edges)
    assert not calls
    assert g.path((0,0),(3,0),set()) is None
    before=len(calls);assert g.path((0,0),(1,2),set());assert len(calls)==before
    assert not any(a[0]<2 and b[0]>=2 for a,neighbors in edges.cache.items() for b in neighbors)

def test_bounded_corridor_preserves_turn_and_does_not_claim_distant_crossing():
    from simpeople.core.traffic import polyline_prefix
    route=[[0,0,0],[5,0,0],[5,10,0]]
    prefix=polyline_prefix(route,8)
    assert prefix==[[0,0,0],[5,0,0],[5,3,0]]
    g=grid();positions={'a':[0,0,0],'crossing':[5,8,0]}
    assert not g.reserve_polyline('a',route,positions)
    assert g.reserve_polyline('a',prefix,positions)
    assert not (g.footprint([5,8,0]) & g.claims['a'])
    assert polyline_prefix(route,100)==route
    assert polyline_prefix(route,5)==route[:2]
