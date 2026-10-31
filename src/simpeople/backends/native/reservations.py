"""Native locomotion with exclusive forward-corridor reservations.

Route IDs are supervisor jobs. Every actual native subtask ID and transition is
logged separately. No USD transform or joint is changed to resolve congestion.
"""
import math
import uuid
import heapq
import carb
import omni.anim.navigation.core as nav
from pxr import Usd,UsdGeom,UsdPhysics
from .adapter import NativeBackend
from simpeople.core.errors import SimPeopleError
from simpeople.core.traffic import ReservationGrid, simplify_polyline,polyline_prefix,VerifiedLazyEdges
from simpeople.core.route_history import history_path

class ReservationNativeBackend(NativeBackend):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.grid=None;self.routes={};self.owner_routes={};self.positions={};self.now=0
        self.static_bounds=[];self.dynamic_prims=[]
        self.corridor_profile=False;self.dynamic_bounds={}
        self.navigation_queries=0
    def enable_corridor_profile(self):
        self.corridor_profile=True
    def emit(self,kind,**payload):
        if self.on_event:self.on_event(kind,**payload)
    def list_actions(self,handle,include_quality=True):
        actions=super().list_actions(handle,include_quality=include_quality)
        if len(self.instances)>1:
            actions['follow']={'status':'blocked','reason':'Moving-target follow is verified for one actor; crowd follow has not passed corridor reservation acceptance.'}
        return actions
    def spawn(self,aid,asset_id,anchor):
        point=self.resolve_target(anchor)
        if self.grid and self.grid.footprint(point) & self.grid.claimed(None):
            raise SimPeopleError('RESOURCE_BUSY','spawn anchor lies in a reserved corridor')
        return super().spawn(aid,asset_id,anchor)
    def segment(self,start,goal):
        self.navigation_queries+=1
        mesh=self.nav.get_navmesh()
        profile=nav.NavAgentDesc(radius=.45/self.mpu,height=1.6/self.mpu,collision_gap=0.0)
        path=mesh.query_shortest_path(start_pos=carb.Float3(*self.to_stage(start)),end_pos=carb.Float3(*self.to_stage(goal)),agent=profile) if mesh else None
        points=[self.to_public(p) for p in path.get_points()] if path else []
        if not points or math.dist(points[-1],goal)>.3:return None
        return points
    def grid_connection(self,start,goal,node_is_start=False):
        points=self.segment(start,goal)
        if not points:return False
        if not self.corridor_profile:return True
        point=points[0] if node_is_start else points[-1]
        node=start if node_is_start else goal
        return math.dist(point,node)<=.02
    def bounds(self,prim):
        box=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_]).ComputeWorldBound(prim).ComputeAlignedRange()
        lo=self.to_public(box.GetMin());hi=self.to_public(box.GetMax())
        return [lo[0]-.45,lo[1]-.45,hi[0]+.45,hi[1]+.45,hi[2]]
    @staticmethod
    def inside(point,bounds):return bounds[0]<point[0]<bounds[2] and bounds[1]<point[1]<bounds[3]
    def make_grid(self,seed):
        box=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_]).ComputeWorldBound(self.stage.GetPrimAtPath('/World/Ground')).ComputeAlignedRange()
        lo=self.to_public(box.GetMin());hi=self.to_public(box.GetMax());cell=1.25
        for prim in self.stage.Traverse():
            if not prim.IsA(UsdGeom.Mesh) or str(prim.GetPath()).startswith(self.namespace) or not prim.HasAPI(UsdPhysics.CollisionAPI):continue
            bounds=self.bounds(prim)
            if bounds[4]<=.15:continue
            if prim.HasAPI(UsdPhysics.RigidBodyAPI):self.dynamic_prims.append(prim);continue
            self.static_bounds.append(bounds)
        nodes=set();edges={}
        for x in range(math.ceil((lo[0]+.5)/cell),math.floor((hi[0]-.5)/cell)+1):
            for y in range(math.ceil((lo[1]+.5)/cell),math.floor((hi[1]-.5)/cell)+1):
                point=[x*cell,y*cell,0]
                if any(self.inside(point,b) for b in self.static_bounds):continue
                if self.corridor_profile:
                    nodes.add((x,y));continue
                path=self.segment(seed,point)
                if path and math.dist(path[-1][:2],point[:2])<=.02:nodes.add((x,y))
        if self.corridor_profile:
            def valid_edge(one,two):
                p=[one[0]*cell,one[1]*cell,0];q=[two[0]*cell,two[1]*cell,0];points=self.segment(p,q)
                return bool(points and math.dist(points[0],p)<=.02 and math.dist(points[-1],q)<=.02
                            and sum(math.dist(a[:2],b[:2]) for a,b in zip(points,points[1:]))<=cell*1.3)
            self.grid=ReservationGrid(nodes,VerifiedLazyEdges(nodes,valid_edge),cell)
            self.emit('traffic_grid_ready',nodes=len(nodes),cell_m=cell,footprint_margin_m=self.grid.margin,
                      static_obstacle_bounds_m=self.static_bounds,nav_profile_radius_m=.45,
                      grid_profile='lazy_local_navmesh_edges',navigation_queries=self.navigation_queries)
            return
        for node in nodes:
            edges[node]=[];p=[node[0]*cell,node[1]*cell,0]
            for dx,dy in [(1,0),(-1,0),(0,1),(0,-1)]:
                nxt=(node[0]+dx,node[1]+dy)
                if nxt not in nodes:continue
                q=[nxt[0]*cell,nxt[1]*cell,0];points=self.segment(p,q)
                if points and sum(math.dist(a[:2],b[:2]) for a,b in zip(points,points[1:]))<=cell*1.3:
                    edges[node].append(nxt)
        self.grid=ReservationGrid(nodes,edges,cell)
        self.emit('traffic_grid_ready',nodes=len(nodes),cell_m=cell,footprint_margin_m=self.grid.margin,
                  static_obstacle_bounds_m=self.static_bounds,nav_profile_radius_m=.45)
    def start(self,handle,step):
        if step['action'] not in {'move_to','sit'}:
            self.cancel_route(handle);return super().start(handle,step)
        obs=self.observe(handle)
        if not obs.get('ready'):raise SimPeopleError('SIM_NOT_READY','native agent absent')
        if step['action']=='sit':
            goals=[self.resolve_target(self.semantics[step['target']]['approach'])]
        else:goals=[self.resolve_target(p) for p in [*step.get('via',[]),step['target']]]
        if not self.segment(obs['position_m'],goals[-1]):raise SimPeopleError('TARGET_UNREACHABLE','no NavMesh path to route target')
        self.cancel_route(handle)
        rid='route-'+uuid.uuid4().hex
        self.routes[rid]={'handle':handle,'step':dict(step),'goals':goals,'goal_index':0,'status':'running',
                          'native_task_id':None,'retries':0,'blocked_since':None,'retry_at':0,'phase':'travel'}
        self.owner_routes[handle]=rid
        self.emit('traffic_route_started',route_id=rid,agent=handle,goals_m=goals)
        return rid
    def cancel_route(self,handle):
        rid=self.owner_routes.pop(handle,None)
        if rid and self.routes[rid]['status'] not in {'succeeded','failed','cancelled'}:
            self.routes[rid]['status']='cancelled';self.emit('traffic_route_cancelled',route_id=rid,agent=handle)
        if self.grid:self.grid.release(handle)
    def stop(self,handle):self.cancel_route(handle);super().stop(handle)
    def despawn(self,handle):self.cancel_route(handle);super().despawn(handle)
    def task_state(self,handle,tid):
        if isinstance(tid,str) and tid.startswith('route-'):
            state=self.routes[tid]['status'];return 'running' if state=='blocked' else 'failed' if state=='cancelled' else state
        return super().task_state(handle,tid)
    def task_error(self,handle,tid):
        if isinstance(tid,str) and tid.startswith('route-'):return self.routes[tid].get('error')
        return super().task_error(handle,tid)
    def blocked_reason(self,handle,tid):
        job=self.routes.get(tid)
        return {'reason':'traffic_reservation','since_sim_time':job['blocked_since']} if job and job['status']=='blocked' else None
    def block(self,rid,job):
        if self.corridor_profile:
            job['retry_at']=self.now+.2+(sum(job['handle'].encode())%11)*.01
        if job['status']!='blocked':
            job['status']='blocked';job['blocked_since']=self.now
            super().stop(job['handle']);self.emit('traffic_wait_started',route_id=rid,agent=job['handle'])
    def complete(self,rid,job,status,error=None):
        job.update(status=status,error=error);self.grid.release(job['handle'])
        self.emit('traffic_route_ended',route_id=rid,agent=job['handle'],status=status,error=error)
    def tick(self,sim_time):
        self.now=sim_time
        observations={h:self.observe(h) for h in self.instances}
        self.positions={h:(o['position_m'] if o.get('ready') else self.instances[h]['spawn_position_m']) for h,o in observations.items()}
        if not self.positions:return
        if self.grid is None:self.make_grid(next(iter(self.positions.values())))
        for prim in self.dynamic_prims:
            bounds=self.bounds(prim)
            key='obstacle:'+str(prim.GetPath())
            if not self.performance_optimized or self.dynamic_bounds.get(key)!=bounds:
                self.dynamic_bounds[key]=bounds
                self.grid.claims[key]={n for n in self.grid.nodes if self.inside(self.grid.point(n),bounds)}
        obstacle_cells=set().union(*(self.grid.claims['obstacle:'+str(p.GetPath())] for p in self.dynamic_prims)) if self.dynamic_prims else set()
        for handle,rid in list(self.owner_routes.items()):
            try:
                job=self.routes[rid]
                if job['status'] in {'running','blocked'} and job['phase']=='travel' and job['native_task_id'] is not None and self.grid.claims.get(handle,set()) & obstacle_cells:
                    super().stop(handle)
                    job.update(native_task_id=None,phase='braking',status='blocked',blocked_since=self.now,brake_stable_since=None)
                    self.emit('traffic_obstacle_brake',route_id=rid,agent=handle)
                self.tick_route(handle,rid,observations[handle])
            except SimPeopleError as err:
                super().stop(handle);self.complete(rid,self.routes[rid],'failed',err.as_dict())

    def tick_route(self,handle,rid,obs):
        job=self.routes[rid]
        if job['status'] in {'succeeded','failed','cancelled'}:return
        if not obs.get('ready') or self.now<job['retry_at']:return
        if job['phase']=='braking':
            if obs['speed_mps']>=.15:job['brake_stable_since']=None;return
            if job['brake_stable_since'] is None:job['brake_stable_since']=self.now
            if self.now-job['brake_stable_since']<.5:return
            self.grid.release(handle);job['phase']='travel'
        if job['native_task_id'] is not None:
            if job.get('continuous_active'):
                while job['goal_index']<len(job['goals'])-1 and math.dist(obs['position_m'][:2],job['goals'][job['goal_index']][:2])<.5:
                    job['goal_index']+=1
            native=super().task_state(handle,job['native_task_id'])
            if native=='failed':
                job['retries']+=1;self.grid.release(handle)
                error=super().task_error(handle,job['native_task_id'])
                self.emit('traffic_native_retry',route_id=rid,native_task_id=job['native_task_id'],error=error,retry=job['retries'])
                if job['retries']>=3:self.complete(rid,job,'failed',error);return
                super().stop(handle);job.update(native_task_id=None,retry_at=self.now+1,continuous_active=False,corridor_candidate=None);return
            if native!='succeeded':return
            if job['phase']=='sit':
                # Sit normally stays RUNNING; an explicit native terminal result
                # is exposed while Engine separately checks the seated pose.
                self.complete(rid,job,'succeeded');return
            if math.dist(obs['position_m'][:2],job['segment_goal'][:2])>.3 or obs['speed_mps']>=.15:return
            if job.get('continuous_active'):
                # A bounded corridor may end before the next mandatory via.
                # Native success only confirms this submitted target list.
                job['goal_index']=job['continuous_next_goal_index'];job['continuous_active']=False
            if self.corridor_profile and len(self.instances)>12 and job.get('history_segment'):
                visits=job.setdefault('grid_visits',{});node=self.grid.nearest(obs['position_m'])
                visits[node]=visits.get(node,0)+1
            self.grid.release(handle);job['native_task_id']=None
        goal=job['goals'][job['goal_index']]
        if math.dist(obs['position_m'][:2],goal[:2])<=.3 and obs['speed_mps']<.15:
            if job['goal_index']+1<len(job['goals']):job['goal_index']+=1;goal=job['goals'][job['goal_index']]
            elif job['step']['action']=='sit':
                seat=self.resolve_target(job['step']['target']);cells=self.grid.sweep(obs['position_m'],seat)
                if not self.grid.reserve(handle,cells,self.positions,obs['position_m'],seat):self.block(rid,job);return
                job['native_task_id']=super().start(handle,job['step']);job['phase']='sit';job['status']='running';job['continuous_active']=False
                self.emit('traffic_native_started',route_id=rid,native_task_id=job['native_task_id'],action='sit');return
            else:self.complete(rid,job,'succeeded');return
        if self.corridor_profile and self.start_continuous_corridor(handle,rid,job,obs):return
        history_enabled=self.corridor_profile and len(self.instances)>12
        if history_enabled and job.get('history_goal_index')!=job['goal_index']:
            job['grid_visits']={};job['history_goal_index']=job['goal_index']
        blocked=self.grid.blocked(handle,self.positions)
        starts=heapq.nsmallest(12,self.grid.nodes,key=lambda n:math.dist(self.grid.point(n)[:2],obs['position_m'][:2]))
        start=next((n for n in starts if n not in blocked and self.grid.can_reserve(handle,self.grid.sweep(obs['position_m'],self.grid.point(n)),self.positions,obs['position_m'],self.grid.point(n))
                    and self.grid_connection(obs['position_m'],self.grid.point(n))),None)
        goal_cells=self.grid.footprint(goal)
        if start is None:self.block(rid,job);return
        ends=heapq.nsmallest(12,self.grid.nodes,key=lambda n:math.dist(self.grid.point(n)[:2],goal[:2]))
        end=next((n for n in ends if n not in blocked and self.grid_connection(self.grid.point(n),goal,node_is_start=True)),None)
        path=(history_path(self.grid,start,end,blocked,job.get('grid_visits',{})) if history_enabled else self.grid.path(start,end,blocked)) if end is not None else None
        if not path:self.block(rid,job);return
        here=obs['position_m'];center=self.grid.point(start)
        if math.dist(here[:2],center[:2])>.35:destination=center
        elif len(path)==1:
            if goal_cells & blocked:self.block(rid,job);return
            destination=goal
        else:
            direction=(path[1][0]-path[0][0],path[1][1]-path[0][1]);last=1
            for index in range(2,min(len(path),9 if job['step'].get('gait')=='run' else 5)):
                if (path[index][0]-path[index-1][0],path[index][1]-path[index-1][1])!=direction:break
                last=index
            destination=self.grid.point(path[last])
        cells=self.grid.sweep(here,destination)
        if not self.grid.reserve(handle,cells,self.positions,here,destination):self.block(rid,job);return
        if job['status']=='blocked':self.emit('traffic_wait_ended',route_id=rid,wait_sim_s=self.now-job['blocked_since'])
        job.update(status='running',blocked_since=None,segment_goal=destination,continuous_active=False,history_segment=history_enabled)
        spec={'action':'move_to','target':destination,'gait':job['step'].get('gait','walk')}
        if 'speed_mps' in job['step']:spec['speed_mps']=job['step']['speed_mps']
        job['native_task_id']=super().start(handle,spec)
        self.emit('traffic_native_started',route_id=rid,native_task_id=job['native_task_id'],action='move_to',target_m=destination,reserved_cells=len(cells),replan_history_nodes=len(job.get('grid_visits',{})))

    def start_continuous_corridor(self,handle,rid,job,obs):
        candidate=job.get('corridor_candidate')
        if candidate and candidate['goal_index']==job['goal_index'] and math.dist(candidate['start'],obs['position_m'])<=.02:
            points=[obs['position_m'],*candidate['points'][1:]];dense_count=candidate['dense_count']
            next_goal=candidate['next_goal_index'];horizon=candidate['horizon_m']
        else:
            points=[obs['position_m']];goal_offsets=[];total=0
            for goal in job['goals'][job['goal_index']:]:
                segment=self.segment(points[-1],goal)
                if not segment:return False
                for point in segment[1:]:
                    length=math.dist(points[-1],point)
                    if length>1e-4:total+=length;points.append(point)
                goal_offsets.append(total)
            # Reserving an entire cross-factory journey unnecessarily prevents
            # other actors from crossing long after the owner has passed. Large
            # crowds use bounded corridors, still with exclusive clearance and
            # native final braking. Small quality comparisons retain full paths.
            horizon=(18. if job['step'].get('gait')=='run' else 12.) if len(self.instances)>12 else None
            next_goal=min(len(job['goals'])-1,job['goal_index']+sum(offset<=horizon+1e-6 for offset in goal_offsets)) if horizon else len(job['goals'])-1
            dense_count=len(points)
            if horizon:points=polyline_prefix(points,horizon)
            points=simplify_polyline(points,.01)
            job['corridor_candidate']={'goal_index':job['goal_index'],'start':list(obs['position_m']),'points':points,'dense_count':dense_count,
                                       'next_goal_index':next_goal,'horizon_m':horizon}
        if len(points)<2 or not self.grid.reserve_polyline(handle,points,self.positions):return False
        if job['status']=='blocked':self.emit('traffic_wait_ended',route_id=rid,wait_sim_s=self.now-job['blocked_since'])
        spec={'action':'move_to','target':points[-1],'gait':job['step'].get('gait','walk')}
        if len(points)>2:spec['via']=points[1:-1]
        if 'speed_mps' in job['step']:spec['speed_mps']=job['step']['speed_mps']
        job.update(status='running',blocked_since=None,segment_goal=points[-1],continuous_active=True,continuous_next_goal_index=next_goal,history_segment=False)
        job['native_task_id']=super().start(handle,spec)
        self.emit('traffic_native_started',route_id=rid,native_task_id=job['native_task_id'],action='continuous_corridor',
                  points_m=points,dense_navmesh_samples=dense_count,reserved_cells=len(self.grid.claims[handle]),final_auto_brake=True,horizon_m=horizon)
        return True
