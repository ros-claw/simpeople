from simpeople.core.traffic import ReservationGrid,ClearanceEdges
from simpeople.core.route_history import history_path

def grid():
    nodes={(x,y) for x in range(5) for y in range(-2,3)}
    return ReservationGrid(nodes,{n:[m for m in sorted(nodes) if abs(m[0]-n[0])+abs(m[1]-n[1])==1] for n in nodes})

def test_free_nodes_can_hide_an_occupied_edge_and_search_must_take_a_detour():
    g=grid();positions={'a':[0,0,0],'standing':[.625,.85,0]};blocked=g.blocked('a',positions)
    old=g.path((0,0),(4,0),blocked)
    assert old[:2]==[(0,0),(1,0)] and not g.clearance('a',g.point(old[0]),g.point(old[1]),positions)
    edges=ClearanceEdges(g,'a',positions);path=g.path((0,0),(4,0),blocked,edges=edges)
    assert path and path[1]!=(1,0)
    assert all(g.can_reserve('a',g.sweep(g.point(a),g.point(b)),positions,g.point(a),g.point(b)) for a,b in zip(path,path[1:]))
    assert history_path(g,(0,0),(4,0),blocked,{(0,-1):1},edges=edges)

def test_dynamic_edge_cache_does_not_outlive_position_or_claim_snapshot():
    g=grid();positions={'a':[0,0,0]};first=ClearanceEdges(g,'a',positions)
    assert (1,0) in first.get((0,0))
    g.claims['other']={(1,0)};second=ClearanceEdges(g,'a',positions)
    assert (1,0) not in second.get((0,0))
    g.release('other');assert (1,0) in ClearanceEdges(g,'a',positions).get((0,0))
