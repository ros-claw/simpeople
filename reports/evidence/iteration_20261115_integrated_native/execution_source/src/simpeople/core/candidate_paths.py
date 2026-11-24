"""Counterexamples and one bounded search after a physical candidate rejection.

No leases, fairness guards, targets or poses are changed here. The adapter must
still submit every alternative to its normal admission and execution checks.
"""
import math
from .traffic import ClearanceEdges
from .route_history import history_path


def goal_leases(grid,actor,goal):
    cells=grid.footprint(goal)
    return {owner:sorted(owned & cells) for owner,owned in grid.claims.items() if owner!=actor and owned & cells}


def conflicts(grid,actor,points,positions,*,extra_cells=()):
    cells=set().union(*(grid.sweep(a,b) for a,b in zip(points,points[1:])))
    cells.update(extra_cells)
    claims=[{'owner':owner,'cells':sorted(cells & owned)} for owner,owned in grid.claims.items()
            if owner!=actor and cells & owned]
    bodies=[]
    for index,(a,b) in enumerate(zip(points,points[1:])):
        dx,dy=b[0]-a[0],b[1]-a[1];length2=dx*dx+dy*dy
        for other,p in positions.items():
            if other==actor or grid.clearance(actor,a,b,{other:p}):continue
            t=max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length2)) if length2 else 0
            bodies.append({'owner':other,'position_m':list(p),'segment_index':index,
                'closest_fraction':t,'distance_m':math.hypot(a[0]+t*dx-p[0],a[1]+t*dy-p[1]),
                'threshold_m':.9})
    return {'body_conflicts':bodies,'claim_conflicts':claims,'physical_feasible':not bodies and not claims}


def destination(grid,path,position,goal,running=False):
    center=grid.point(path[0])
    if math.dist(position[:2],center[:2])>.35:return center
    if len(path)==1:return list(goal)
    direction=(path[1][0]-path[0][0],path[1][1]-path[0][1]);last=1
    for index in range(2,min(len(path),9 if running else 5)):
        if (path[index][0]-path[index-1][0],path[index][1]-path[index-1][1])!=direction:break
        last=index
    return grid.point(path[last])


def alternative(grid,actor,position,goal,positions,start,ends,blocked,visits,connection,running=False):
    """At most one A* search; connectors and actual-root chord also verified."""
    end=next((n for n in ends if n not in blocked and
        grid.can_reserve(actor,grid.sweep(grid.point(n),goal),positions,grid.point(n),goal) and
        connection(grid.point(n),goal)),None)
    if end is None:return None
    path=history_path(grid,start,end,blocked,visits,edges=ClearanceEdges(grid,actor,positions))
    if not path:return None
    target=destination(grid,path,position,goal,running)
    if not grid.can_reserve(actor,grid.sweep(position,target),positions,position,target):return None
    return {'path':path,'destination_m':target,'original_goal_m':list(goal)}
