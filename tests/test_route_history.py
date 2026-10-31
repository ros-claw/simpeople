from simpeople.core.traffic import ReservationGrid
from simpeople.core.route_history import history_path

def make_grid():
    nodes={(x,y) for x in range(5) for y in range(3)}
    edges={n:[m for m in nodes if abs(m[0]-n[0])+abs(m[1]-n[1])==1] for n in nodes}
    return ReservationGrid(nodes,edges)

def test_temporary_corridor_replan_avoids_a_repeated_detour():
    grid=make_grid();start=(0,1);goal=(4,1);blocked={(2,1)}
    previous=grid.path(start,goal,blocked)
    visits={n:2 for n in previous[1:-1]}
    alternative=history_path(grid,start,goal,blocked,visits)
    assert alternative and (2,1) not in alternative
    assert sum(visits.get(n,0) for n in alternative[1:-1])<sum(visits.get(n,0) for n in previous[1:-1])
    assert len(alternative)==len(previous)

def test_history_never_forbids_the_only_safe_retreat():
    grid=make_grid();start=(0,1);goal=(4,1)
    blocked={(2,1)}|{(x,2) for x in range(5)}
    visits={(x,0):20 for x in range(5)}
    path=history_path(grid,start,goal,blocked,visits)
    assert path and path[0]==start and path[-1]==goal
    assert any(n in visits for n in path) and not (set(path)&blocked)
    assert history_path(grid,start,goal,blocked,{})==grid.path(start,goal,blocked)
