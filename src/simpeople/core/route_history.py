"""Soft per-route history costs for replanning around temporary crowd claims.

Previously travelled nodes remain usable: this must not turn a necessary retreat
through a doorway into an unreachable target. Geometry and reservations are
unchanged; only the choice between currently available paths is affected.
"""
import heapq
import math

def history_path(grid,start,goal,blocked,visits):
    if not visits:return grid.path(start,goal,blocked)
    if goal in blocked or start not in grid.nodes or goal not in grid.nodes:return None
    queue=[(0,0,start)];cost={start:0};parent={}
    while queue:
        _,g,node=heapq.heappop(queue)
        if g!=cost[node]:continue
        if node==goal:
            path=[goal]
            while path[-1]!=start:path.append(parent[path[-1]])
            return list(reversed(path))
        for nxt in grid.edges.get(node,[]):
            if nxt in blocked:continue
            # A bounded, positive cost discourages repeated reversals without
            # forbidding a route that has to traverse an earlier node again.
            penalty=2*min(4,visits.get(nxt,0))
            new=g+1+penalty
            if new<cost.get(nxt,math.inf):
                cost[nxt]=new;parent[nxt]=node
                heuristic=abs(nxt[0]-goal[0])+abs(nxt[1]-goal[1])
                heapq.heappush(queue,(new+heuristic,new,nxt))
    return None
