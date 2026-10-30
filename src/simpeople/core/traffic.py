"""Grid reservations over a verified NavMesh graph. No animation/root writes."""
import heapq
import math

class ReservationGrid:
    def __init__(self,nodes,edges,cell_m=1.25,margin_m=.45):
        self.nodes=set(nodes);self.edges=edges;self.cell=cell_m;self.margin=margin_m;self.claims={}
    def point(self,node):return [node[0]*self.cell,node[1]*self.cell,0]
    def nearest(self,p):return (round(p[0]/self.cell),round(p[1]/self.cell))
    def footprint(self,p):
        c=self.cell;m=self.margin
        return {(x,y) for x in range(math.floor((p[0]-m)/c+.5),math.floor((p[0]+m)/c+.5)+1)
                      for y in range(math.floor((p[1]-m)/c+.5),math.floor((p[1]+m)/c+.5)+1)}
    def sweep(self,start,end):
        steps=max(1,math.ceil(math.dist(start[:2],end[:2])/.2));cells=set()
        for i in range(steps+1):cells.update(self.footprint([start[j]+(end[j]-start[j])*i/steps for j in range(3)]))
        return cells
    def blocked(self,actor,positions):
        cells=set()
        for other,p in positions.items():
            if other!=actor:
                cells.update(n for n in self.footprint(p) if math.dist(self.point(n)[:2],p[:2])<.9)
        cells.update(self.claimed(actor))
        return cells
    def claimed(self,actor):
        cells=set()
        for other,claim in self.claims.items():
            if other!=actor:cells.update(claim)
        return cells
    def clearance(self,actor,start,end,positions):
        dx=end[0]-start[0];dy=end[1]-start[1];length2=dx*dx+dy*dy
        for other,p in positions.items():
            if other==actor:continue
            t=max(0,min(1,((p[0]-start[0])*dx+(p[1]-start[1])*dy)/length2)) if length2 else 0
            distance=math.hypot(start[0]+t*dx-p[0],start[1]+t*dy-p[1])
            if distance<.9:
                # A close initial configuration may only move away, never further in.
                initial=math.dist(start[:2],p[:2])
                if t>1e-6 or math.dist(end[:2],p[:2])<=initial+.05:return False
        return True
    def can_reserve(self,actor,cells,positions,start=None,end=None):
        if cells & self.claimed(actor):return False
        if start is not None:return self.clearance(actor,start,end,positions)
        return not (cells & self.blocked(actor,positions))
    def reserve(self,actor,cells,positions,start=None,end=None):
        if not self.can_reserve(actor,cells,positions,start,end):return False
        self.claims[actor]=set(cells);return True
    def reserve_polyline(self,actor,points,positions):
        """Atomically claim every leg, including clearance and final braking area."""
        if len(points)<2:return False
        cells=set()
        for start,end in zip(points,points[1:]):
            cells.update(self.sweep(start,end))
            if not self.clearance(actor,start,end,positions):return False
        if cells & self.claimed(actor):return False
        self.claims[actor]=cells;return True
    def release(self,actor):self.claims.pop(actor,None)
    def path(self,start,goal,blocked):
        if goal in blocked or start not in self.nodes or goal not in self.nodes:return None
        queue=[(0,0,start)];cost={start:0};parent={}
        while queue:
            _,g,node=heapq.heappop(queue)
            if g!=cost[node]:continue
            if node==goal:
                path=[goal]
                while path[-1]!=start:path.append(parent[path[-1]])
                return list(reversed(path))
            for nxt in self.edges.get(node,[]):
                if nxt in blocked:continue
                new=g+1
                if new<cost.get(nxt,math.inf):
                    cost[nxt]=new;parent[nxt]=node
                    heuristic=abs(nxt[0]-goal[0])+abs(nxt[1]-goal[1])
                    heapq.heappush(queue,(new+heuristic,new,nxt))
        return None

def simplify_polyline(points,tolerance_m=.01):
    """RDP keeps endpoints/corners while discarding dense NavMesh samples."""
    if len(points)<3:return list(points)
    keep={0,len(points)-1};stack=[(0,len(points)-1)]
    while stack:
        first,last=stack.pop();a=points[first];b=points[last]
        v=[b[k]-a[k] for k in range(3)];length=sum(x*x for x in v)
        worst=-1;index=None
        for i in range(first+1,last):
            t=max(0,min(1,sum((points[i][k]-a[k])*v[k] for k in range(3))/length)) if length else 0
            distance=math.sqrt(sum((points[i][k]-a[k]-t*v[k])**2 for k in range(3)))
            if distance>worst:worst=distance;index=i
        if index is not None and worst>tolerance_m:
            keep.add(index);stack.extend(((first,index),(index,last)))
    return [points[i] for i in sorted(keep)]

def polyline_prefix(points,distance_m):
    """Keep route corners and an interpolated endpoint within a safe horizon."""
    if not points:return []
    if distance_m<=0:raise ValueError('corridor distance must be positive')
    result=[list(points[0])];remaining=distance_m
    for start,end in zip(points,points[1:]):
        length=math.dist(start,end)
        if length<=1e-9:continue
        if length>remaining:
            result.append([start[k]+(end[k]-start[k])*remaining/length for k in range(3)])
            return result
        result.append(list(end));remaining-=length
        if remaining<=1e-9:return result
    return result

class VerifiedLazyEdges:
    """Cache each NavMesh-verified local edge only when A* needs that node."""
    def __init__(self,nodes,validator):self.nodes=nodes;self.validator=validator;self.cache={}
    def get(self,node,default=None):
        if node not in self.nodes:return default
        if node not in self.cache:
            neighbors=[]
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
                other=(node[0]+dx,node[1]+dy)
                if other in self.nodes and self.validator(node,other):neighbors.append(other)
            self.cache[node]=neighbors
        return self.cache[node]
