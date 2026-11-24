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
from .arrival_recovery import ArrivalRecoveryMixin
from simpeople.core.errors import SimPeopleError
from simpeople.core.traffic import ReservationGrid, simplify_polyline,polyline_prefix,VerifiedLazyEdges,FairGate,WaitGraph,ClearanceEdges,corridor_retry_delay
from simpeople.core.route_history import history_path
from simpeople.core.runtime_policy import load_policy
from simpeople.core.tail_release import StraightTail,straight_geometry,conservative_swept_cells
from simpeople.core.candidate_paths import conflicts as candidate_conflicts,destination as candidate_destination,alternative as candidate_alternative,goal_leases
from simpeople.core.path_diagnostics import report_search_wait,select_candidate

class ReservationNativeBackend(ArrivalRecoveryMixin,NativeBackend):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.grid=None;self.routes={};self.owner_routes={};self.positions={};self.now=0
        self.static_bounds=[];self.dynamic_prims=[]
        self.corridor_profile=False;self.dynamic_bounds={}
        self.navigation_queries=0;self.action_spaces={};self.local_yield_stops={}
        self.runtime_policy=load_policy(self.config_dir)
        self.fair_gate=FairGate(self.runtime_policy['max_wait_sim_s'])
        self.wait_graph=WaitGraph(self.runtime_policy['cycle_detection_sim_s']);self.last_dependencies=None
    def enable_corridor_profile(self):
        self.corridor_profile=True
    def seat_egress(self,seat,handle):
        legacy=super().seat_egress(seat,handle)
        if not self.runtime_policy['seat_egress_selection_enabled'] or self.grid is None or legacy is None:return legacy
        from simpeople.core.seat_egress import select_exit
        obs=self.observe(handle)
        if not obs.get('ready'):raise SimPeopleError('SIM_NOT_READY','seat exit selection requires actual native readback')
        config=self.semantics[seat];candidates=config.get('egress_targets',[config.get('egress')])
        result=select_exit(candidates,legacy,obs['position_m'],self.resolve_target,self.segment,
            lambda a,b:self.grid.can_reserve(handle,self.grid.sweep(a,b),self.positions,a,b))
        self.emit('seat_egress_selected',agent=handle,actor_id=self.actor_label(handle),seat=seat,
                  origin_m=obs['position_m'],legacy_target=legacy,**result)
        return result['chosen_target']
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
        handle=super().spawn(aid,asset_id,anchor);self.instances[handle]['traffic_instance_id']=uuid.uuid4().hex
        return handle
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
    def check_action_space(self,handle,step):
        from simpeople.core.action_space import action_cells
        center=self.observe(handle)['position_m'];radius=self.custom_actions[step['target']]['clearance_radius_m'];cells=action_cells(self.grid,center,radius);bounds=[*self.static_bounds,*self.dynamic_bounds.values()]
        if any(math.hypot(max(b[0]-center[0],0,center[0]-b[2]),max(b[1]-center[1],0,center[1]-b[3]))<radius for b in bounds):raise SimPeopleError('TARGET_INVALID','activity area overlaps an obstacle',clip=step['target'],radius_m=radius)
        if cells & self.grid.claimed(handle) or any(math.dist(center[:2],p[:2])<radius+.5 for h,p in self.positions.items() if h!=handle):raise SimPeopleError('RESOURCE_BUSY','full-body clip needs a clear activity area',clip=step['target'],radius_m=radius)
        return center,radius,cells

    def start(self,handle,step):
        if self.action_admission_block(handle) is not None:
            raise SimPeopleError('RESOURCE_BUSY','previous Native custom/yield stop is still settling')
        if step['action']=='custom_action':
            center,radius,cells=self.check_action_space(handle,step)
            self.cancel_route(handle)
            tid=super().start(handle,step)
            self.grid.claims[handle]=cells
            bay=next((key for key,value in self.semantics.items() if value.get('kind')=='activity_bay'
                      and value.get('clip')==step['target'] and math.dist(self.resolve_target(key),center)<.3),None)
            self.action_spaces[handle]={'task_id':tid,'center':center,'radius_m':radius,'stopped_at':None,'activity_bay':bay}
            self.emit('custom_action_space_reserved',agent=handle,clip=step['target'],center_m=center,radius_m=radius,native_task_id=tid)
            return tid
        if step['action'] not in {'move_to','sit'}:
            if handle in self.action_spaces:
                self.action_spaces[handle]['stopped_at']=self.now
                return super().start(handle,step)
            self.cancel_route(handle);return super().start(handle,step)
        if handle in self.action_spaces:
            self.action_spaces.pop(handle);self.grid.release(handle)
        obs=self.observe(handle)
        if not obs.get('ready'):raise SimPeopleError('SIM_NOT_READY','native agent absent')
        if step['action']=='sit':
            goals=[self.resolve_target(self.semantics[step['target']]['approach'])]
        else:goals=[self.resolve_target(p) for p in [*step.get('via',[]),step['target']]]
        static_path=self.segment(obs['position_m'],goals[-1])
        if not static_path:raise SimPeopleError('TARGET_UNREACHABLE','no NavMesh path to route target')
        self.cancel_route(handle)
        rid='route-'+uuid.uuid4().hex
        retry_actor_id=self.actor_label(handle)
        self.routes[rid]={'handle':handle,'step':dict(step),'goals':goals,'goal_index':0,'status':'running',
                          'native_task_id':None,'retries':0,'blocked_since':None,'retry_at':0,'phase':'travel',
                          'retry_actor_id':retry_actor_id,'retry_delay_s':corridor_retry_delay(retry_actor_id),
                          'intent_points':simplify_polyline(polyline_prefix(static_path,18 if step.get('gait')=='run' else 12)),
                          'requested_sim_time':self.now,'recovery_attempts':0}
        self.owner_routes[handle]=rid
        self.emit('traffic_route_started',route_id=rid,agent=handle,goals_m=goals,
                  retry_actor_id=retry_actor_id,retry_delay_s=self.routes[rid]['retry_delay_s'])
        return rid
    def cancel_route(self,handle):
        rid=self.owner_routes.pop(handle,None)
        if rid:self.fair_gate.cancel(rid)
        if rid and self.routes[rid]['status'] not in {'succeeded','failed','cancelled'}:
            self.routes[rid]['status']='cancelled';self.emit('traffic_route_cancelled',route_id=rid,agent=handle)
        from .local_yield_stop import retain
        if self.grid and not retain(self,handle,rid):self.grid.release(handle)
    def stop(self,handle):
        if handle in self.action_spaces:self.action_spaces[handle]['stopped_at']=self.now
        else:self.cancel_route(handle)
        super().stop(handle)
    def despawn(self,handle):
        self.action_spaces.pop(handle,None);self.cancel_route(handle);super().despawn(handle)
        # Body removal, not a moving-body settlement, ends this incarnation.
        self.local_yield_stops.pop(handle,None)
        if self.grid:self.grid.release(handle)
    def action_admission_block(self,handle):
        self.assert_thread()
        custom=super().action_admission_block(handle)
        if custom is not None:return custom
        stop=self.local_yield_stops.get(handle)
        if stop is None:return None
        return {'reason':'cancelled_yield_still_settling',
                'since_sim_time':stop['started_sim_time'],
                'previous_route_id':stop['route_id'],
                'body_instance_id':stop['body_generation']}
    def is_standing(self,handle,obs):
        # Seat cleanup also waits for the retained body; activity admission is checked separately.
        from .local_yield_stop import may_start
        return may_start(self,handle) and super().is_standing(handle,obs)
    def task_state(self,handle,tid):
        if isinstance(tid,str) and tid.startswith('route-'):
            state=self.routes[tid]['status'];return 'running' if state=='blocked' else 'failed' if state=='cancelled' else state
        return super().task_state(handle,tid)
    def task_error(self,handle,tid):
        if isinstance(tid,str) and tid.startswith('route-'):return self.routes[tid].get('error')
        return super().task_error(handle,tid)
    def blocked_reason(self,handle,tid):
        job=self.routes.get(tid)
        return dict(job.get('blocked_details',{'reason':'traffic_reservation','since_sim_time':job['blocked_since']})) if job and job['status']=='blocked' else None
    def request_recovery(self,handle,rid):
        job=self.routes.get(rid)
        if self.owner_routes.get(handle)!=rid or not job:raise SimPeopleError('TASK_STALE','recovery does not own the current route')
        if job['phase']=='arrival_braking':return {'accepted':False,'reason':'native_arrival_stop_in_progress'}
        if job['status']!='blocked' or job['phase'] in {'recovery_braking','tail_braking'}:return {'accepted':False,'reason':'route_not_waiting'}
        if job['recovery_attempts']>=self.runtime_policy['max_recovery_attempts']:raise SimPeopleError('RECOVERY_EXHAUSTED','route recovery budget exhausted')
        if job.get('local_yield'):return {'accepted':False,'reason':'local_yield_still_owned'}
        if self.runtime_policy.get('cycle_drainage_enabled',False):
            from .local_yield import propose,start
            proposal=propose(self,handle,rid,job)
            if proposal:
                job['recovery_attempts']+=1
                return start(self,handle,rid,job,proposal,lambda spec:super(ReservationNativeBackend,self).start(handle,spec))
        job.update(recovery_attempts=job['recovery_attempts']+1,phase='recovery_braking',recovery_stable_since=None)
        super().stop(handle)
        self.emit('traffic_recovery_requested',route_id=rid,agent=handle,attempt=job['recovery_attempts'],
                  strategy='stop_release_future_and_replan_same_goal',target_m=job['goals'][-1])
        return {'accepted':True,'strategy':'stop_release_future_and_replan_same_goal','attempt':job['recovery_attempts'],'original_target_m':job['goals'][-1]}
    def actor_label(self,handle):
        return super().actor_label(handle)
    def admit_reservation(self,handle,rid,job,points,polyline=False,drain_exit_cells=None):
        cells=set().union(*(self.grid.sweep(a,b) for a,b in zip(points,points[1:]))) if len(points)>1 else self.grid.footprint(points[0])
        speed=job['step'].get('speed_mps',2.8 if job['step'].get('gait')=='run' else 1.2)
        extra_cells=conservative_swept_cells(self.grid,points) if polyline and self.runtime_policy['diagonal_tail_release_enabled'] and straight_geometry(self.grid,points,speed,True) is None else set()
        cells.update(extra_cells)
        intent=job.get('intent_points') or points
        intent_cells=set().union(*(self.grid.sweep(a,b) for a,b in zip(intent,intent[1:]))) if len(intent)>1 else cells
        intent_cells.update(extra_cells)
        goal=job['goals'][job['goal_index']]
        goal_occupants={h for h,p in self.positions.items() if h!=handle and math.dist(p[:2],goal[:2])<.9}
        goal_claimers=set(goal_leases(self.grid,handle,goal)) if self.runtime_policy['goal_claim_wait_enabled'] else set()
        # An occupied destination is a different resource from an available
        # corridor. Fence that destination, not unrelated access needed for its
        # occupant to leave. Expand to corridor scope when it becomes available,
        # retaining original priority and recognizing current drainers.
        scope='occupied_goal' if goal_occupants or goal_claimers else 'corridor'
        if goal_occupants or goal_claimers:intent_cells=self.grid.footprint(goal)
        drainers={self.owner_routes[h] for h in self.owner_routes if h!=handle and
                  (self.grid.claims.get(h,set()) & intent_cells or self.grid.footprint(self.positions[h]) & intent_cells)}
        drainers.update(self.instances[h]['traffic_instance_id'] for h,p in self.positions.items() if h!=handle and
                        (self.grid.footprint(p) & intent_cells or self.grid.claims.get(h,set()) & intent_cells))
        for guard in self.fair_gate.pending.values():
            if guard['key']!=rid and guard['cells'] & intent_cells and guard['occupant_token'] is not None:
                drainers.add(guard['occupant_token'])
        self.fair_gate.request(rid,handle,intent_cells,self.now,drainers,occupant_token=self.instances[handle]['traffic_instance_id'],
                               origin_cells=self.grid.footprint(points[0]),goal_cells=self.grid.footprint(goal),scope=scope)
        if job.get('guard_scope')!=scope:
            job['guard_scope']=scope
            self.emit('traffic_guard_scope_changed',route_id=rid,agent=handle,scope=scope,
                blocker_ids=sorted(self.actor_label(h) for h in goal_occupants|goal_claimers),target_m=goal,
                priority_since_sim_time=self.fair_gate.pending[rid]['since'])
        # A verified full escape may need an initial centering segment inside
        # the protected zone. Its preexisting occupant must be able to begin it.
        exit_cells=drain_exit_cells if drain_exit_cells is not None else self.grid.footprint(points[-1])
        older=self.fair_gate.blockers(rid,cells,exit_cells) if self.runtime_policy['traffic_fairness_enabled'] else []
        claimers={h for h,c in self.grid.claims.items() if h!=handle and c & cells}
        bodies={h for h,p in self.positions.items() if h!=handle and any(not self.grid.clearance(handle,a,b,{h:p}) for a,b in zip(points,points[1:]))}
        blockers=claimers|bodies|{r['actor'] for r in older}
        physical_feasible=not claimers and not bodies
        job['blocked_details']={'reason':'fairness_drain' if older else 'traffic_reservation' if claimers else 'actor_clearance',
            'admission_scope':scope,'goal_blocker_ids':sorted(self.actor_label(h) for h in goal_occupants|goal_claimers),
            'since_sim_time':self.fair_gate.pending[rid]['wait_since'] if self.fair_gate.pending[rid]['wait_since'] is not None else self.now,
            'priority_since_sim_time':self.fair_gate.pending[rid]['since'],'blocker_ids':sorted(self.actor_label(h) for h in blockers),
            'blocker_handles':sorted(blockers),'resource_id':'navmesh_corridor','ticket_rank':len(older),
            'retry_at_sim_time':job['retry_at'],'physically_feasible':physical_feasible,'max_wait_sim_s':self.runtime_policy['max_wait_sim_s'],
            'max_conflicting_bypasses':0,'native_retry_count':job['retries'],'recovery_attempts':job['recovery_attempts']}
        if older and physical_feasible and job.get('last_fair_deferred')!=tuple(r['key'] for r in older):
            job['last_fair_deferred']=tuple(r['key'] for r in older)
            self.emit('traffic_fairness_deferred',route_id=rid,agent=handle,older_route_ids=list(job['last_fair_deferred']),
                      candidate_points_m=points,blocked_details=job['blocked_details'])
        reserved=not older and (self.grid.reserve_polyline(handle,points,self.positions,extra_cells=extra_cells) if polyline else self.grid.reserve(handle,cells,self.positions,points[0],points[-1]))
        if reserved:
            wait=self.fair_gate.grant(rid,self.now)
            if wait['wait_sim_s']>0:self.emit('traffic_admission_granted',route_id=rid,agent=handle,**wait)
            if drain_exit_cells is not None:
                drained=self.fair_gate.blockers(rid,cells,self.grid.footprint(points[-1]))
                if drained:self.emit('traffic_drainage_granted',route_id=rid,agent=handle,
                    older_route_ids=[r['key'] for r in drained],candidate_points_m=points,
                    verified_escape_points_m=job['drain_escape_points'],reason='existing_occupant_begins_verified_escape')
        else:self.fair_gate.waiting(rid,self.now)
        if not physical_feasible:
            signature=(tuple(tuple(round(x/.05) for x in p) for p in points),tuple(sorted(claimers|bodies)))
            if signature!=job.get('rejected_candidate_signature') or self.now-job.get('rejected_candidate_at',-10)>=2:
                job.update(rejected_candidate_signature=signature,rejected_candidate_at=self.now)
                self.emit('traffic_candidate_rejected',route_id=rid,agent=handle,points_m=points,
                    target_m=goal,guard_priority_since_sim_time=self.fair_gate.pending[rid]['since'],
                    **candidate_conflicts(self.grid,handle,points,self.positions,extra_cells=extra_cells))
        return reserved
    def block(self,rid,job):
        if self.corridor_profile:
            job['retry_at']=self.now+job['retry_delay_s']
        if job['status']!='blocked':
            job['status']='blocked';job['blocked_since']=self.now
            super().stop(job['handle']);self.emit('traffic_wait_started',route_id=rid,agent=job['handle'],blocked_details=job.get('blocked_details'),
                retry_at_sim_time=job['retry_at'] if self.corridor_profile else None,
                retry_delay_s=job['retry_delay_s'] if self.corridor_profile else None,
                retry_actor_id=job['retry_actor_id'])
        if job.get('blocked_details'):job['blocked_details']['retry_at_sim_time']=job['retry_at']
    def complete(self,rid,job,status,error=None):
        if status=='succeeded' and job.get('local_yield'):
            from .local_yield import restore_original
            restore_original(self,job['handle'],rid,job)
            return
        job.update(status=status,error=error);self.grid.release(job['handle'])
        self.fair_gate.cancel(rid)
        self.emit('traffic_route_ended',route_id=rid,agent=job['handle'],status=status,error=error)
    def tick(self,sim_time):
        self.now=sim_time
        observations={h:self.observe(h) for h in self.instances}
        self.positions={h:(o['position_m'] if o.get('ready') else self.instances[h]['spawn_position_m']) for h,o in observations.items()}
        if not self.positions:return
        from .local_yield_stop import advance_stops
        advance_stops(self,observations)
        if self.grid is None:self.make_grid(next(iter(self.positions.values())))
        for handle,space in list(self.action_spaces.items()):
            if space['stopped_at'] is None and super().task_state(handle,space['task_id'])!='running':space['stopped_at']=self.now
            if not space.get('activity_bay') and space['stopped_at'] is not None and self.now-space['stopped_at']>=1 and self.is_standing(handle,observations[handle]):
                self.grid.release(handle);self.action_spaces.pop(handle)
                self.emit('custom_action_space_released',agent=handle)
        for prim in self.dynamic_prims:
            bounds=self.bounds(prim)
            key='obstacle:'+str(prim.GetPath())
            if not self.performance_optimized or self.dynamic_bounds.get(key)!=bounds:
                self.dynamic_bounds[key]=bounds
                self.grid.claims[key]={n for n in self.grid.nodes if self.inside(self.grid.point(n),bounds)}
        obstacle_cells=set().union(*(self.grid.claims['obstacle:'+str(p.GetPath())] for p in self.dynamic_prims)) if self.dynamic_prims else set()
        ordered=sorted(self.owner_routes.items(),key=lambda pair:(self.fair_gate.pending.get(pair[1],{}).get('since',self.now),pair[0]))
        for handle,rid in ordered:
            try:
                job=self.routes[rid]
                if job['status'] in {'running','blocked'} and job['phase']=='travel' and job['native_task_id'] is not None and self.grid.claims.get(handle,set()) & obstacle_cells:
                    super().stop(handle)
                    job.update(native_task_id=None,phase='braking',status='blocked',blocked_since=self.now,brake_stable_since=None)
                    job['blocked_details']={'reason':'dynamic_obstacle','since_sim_time':self.now,'blocker_ids':sorted(self.dynamic_bounds),
                        'blocker_handles':sorted(self.dynamic_bounds),'resource_id':'navmesh_corridor','retry_at_sim_time':self.now}
                    self.emit('traffic_obstacle_brake',route_id=rid,agent=handle)
                self.tick_route(handle,rid,observations[handle])
            except SimPeopleError as err:
                super().stop(handle);self.complete(rid,self.routes[rid],'failed',err.as_dict())
        graph={h:set(self.routes[r].get('blocked_details',{}).get('blocker_handles',[])) for h,r in self.owner_routes.items() if self.routes[r]['status']=='blocked'}
        for cycle in self.wait_graph.update(graph,self.now):
            self.emit('traffic_wait_cycle',**cycle)
            try:
                import time
                from simpeople.core.wait_snapshot import capture_wait_snapshot
                began=time.perf_counter()
                snapshot=capture_wait_snapshot(self.grid,self.fair_gate,self.routes,self.owner_routes,
                    self.instances,self.positions,observations,self.now,cycle,self.static_bounds,self.dynamic_bounds)
                snapshot['build_wall_ms']=(time.perf_counter()-began)*1000
                self.emit('traffic_wait_cycle_snapshot',snapshot=snapshot)
            except Exception as error:
                # A diagnostic serialization error cannot alter arbitration or
                # fail an otherwise live actor. Report its explicit absence.
                self.emit('traffic_wait_cycle_snapshot_unavailable',cycle=cycle,error_type=type(error).__name__,message=str(error))
        edges=sorted((self.actor_label(h),self.actor_label(b)) for h,others in graph.items() for b in others)
        if edges!=self.last_dependencies:
            self.last_dependencies=edges;self.emit('traffic_wait_dependencies',edges=edges)
        for violation in self.fair_gate.violations(self.now):
            rid=violation.pop('key');handle=violation.pop('actor');job=self.routes.get(rid,{})
            self.emit('traffic_wait_budget_exceeded',route_id=rid,agent=handle,blocked_details=job.get('blocked_details'),**violation)

    def tick_route(self,handle,rid,obs):
        job=self.routes[rid]
        if job['status'] in {'succeeded','failed','cancelled'}:return
        if handle in self.local_yield_stops:
            job.update(status='blocked',blocked_details={'reason':'cancelled_yield_still_settling',
                       'since_sim_time':self.local_yield_stops[handle]['started_sim_time'],
                       'blocker_ids':[],'blocker_handles':[]})
            return
        if (job.get('blocked_details') or {}).get('reason')=='cancelled_yield_still_settling':
            job.update(status='running',blocked_since=None)
            job.pop('blocked_details',None)
        if job.get('local_yield'):
            from .local_yield import advance,begin_brake
            if job['phase']=='braking':begin_brake(self,handle,rid,job,'dynamic_obstacle')
            native=super().task_state(handle,job['native_task_id']) if job['native_task_id'] is not None else None
            if not advance(self,handle,rid,job,obs,native,lambda:super(ReservationNativeBackend,self).stop(handle)):return
        if not obs.get('ready') or self.now<job['retry_at']:return
        if self._tick_arrival_recovery(handle,rid,job,obs):return
        if job['phase']=='tail_braking':
            if obs['speed_mps']>=.15:job['tail_stop_since']=None;return
            if job['tail_stop_since'] is None:job['tail_stop_since']=self.now
            if self.now-job['tail_stop_since']<.5:return
            self.complete(rid,job,'failed',{'code':'TRAJECTORY_DEVIATED','stage':'execution',
                'message':'native corridor tail safety guard stopped the actor','details':{'reason':job['tail_brake_reason'],'physical_stop_verified':True}})
            return
        if job['phase']=='recovery_braking':
            if obs['speed_mps']>=.15:job['recovery_stable_since']=None;return
            if job['recovery_stable_since'] is None:job['recovery_stable_since']=self.now
            if self.now-job['recovery_stable_since']<.5:return
            self.grid.release(handle)
            job.update(native_task_id=None,phase='travel',corridor_candidate=None,continuous_active=False)
            job['grid_visits']={};self.emit('traffic_recovery_applied',route_id=rid,agent=handle,attempt=job['recovery_attempts'],
                target_m=job['goals'][-1],physical_stop_verified=True,wait_age_preserved=rid in self.fair_gate.pending)
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
            if native=='running' and job.get('continuous_active'):
                if not self.update_tail(handle,rid,job,obs):return
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
            if self._arrival_shortfall(handle,rid,job,obs):return
            if math.dist(obs['position_m'][:2],job['segment_goal'][:2])>.3 or obs['speed_mps']>=.15:return
            if job.get('continuous_active'):
                # A bounded corridor may end before the next mandatory via.
                # Native success only confirms this submitted target list.
                job['goal_index']=job['continuous_next_goal_index'];job['continuous_active']=False
            if self.corridor_profile and job.get('history_segment'):
                visits=job.setdefault('grid_visits',{});node=self.grid.nearest(obs['position_m'])
                visits[node]=visits.get(node,0)+1
            self.grid.release(handle);job['native_task_id']=None
        goal=job['goals'][job['goal_index']]
        if math.dist(obs['position_m'][:2],goal[:2])<=.3 and obs['speed_mps']<.15:
            if job['goal_index']+1<len(job['goals']):job['goal_index']+=1;goal=job['goals'][job['goal_index']]
            elif job['step']['action']=='sit':
                seat=self.resolve_target(job['step']['target']);cells=self.grid.sweep(obs['position_m'],seat)
                if not self.admit_reservation(handle,rid,job,[obs['position_m'],seat]):self.block(rid,job);return
                job['native_task_id']=super().start(handle,job['step']);job['phase']='sit';job['status']='running';job['continuous_active']=False
                self.emit('traffic_native_started',route_id=rid,native_task_id=job['native_task_id'],action='sit');return
            else:self.complete(rid,job,'succeeded');return
        if self.corridor_profile and not job.get('arrival_segment_fallback',False) and self.start_continuous_corridor(handle,rid,job,obs):return
        if self.runtime_policy['goal_claim_wait_enabled']:
            occupied=goal_leases(self.grid,handle,goal)
            if occupied:
                if rid not in self.fair_gate.pending:self.admit_reservation(handle,rid,job,[obs['position_m'],goal])
                signature=tuple(sorted(occupied))
                if signature!=job.get('goal_claim_signature') or self.now-job.get('goal_claim_reported_at',-10)>=2:
                    job.update(goal_claim_signature=signature,goal_claim_reported_at=self.now)
                    self.emit('traffic_goal_lease_wait',route_id=rid,agent=handle,target_m=goal,
                        position_m=obs['position_m'],claim_owners={self.actor_label(h):cells for h,cells in occupied.items()},
                        claim_routes={self.actor_label(h):self.owner_routes.get(h) for h in occupied},
                        claim_owner_positions_m={self.actor_label(h):self.positions.get(h) for h in occupied},
                        guard_priority_since_sim_time=self.fair_gate.pending[rid]['since'])
                self.block(rid,job);return
        # A small queue can replan back and forth around changing claims too.
        # Keep the existing bounded positive history cost at every crowd size.
        history_enabled=self.corridor_profile
        if history_enabled and job.get('history_goal_index')!=job['goal_index']:
            job['grid_visits']={};job['history_goal_index']=job['goal_index']
        blocked=self.grid.blocked(handle,self.positions)
        starts=heapq.nsmallest(12,self.grid.nodes,key=lambda n:math.dist(self.grid.point(n)[:2],obs['position_m'][:2]))
        start,start_checks=select_candidate(starts,blocked,
            lambda n:self.grid.can_reserve(handle,self.grid.sweep(obs['position_m'],self.grid.point(n)),self.positions,obs['position_m'],self.grid.point(n)),
            lambda n:self.grid_connection(obs['position_m'],self.grid.point(n)))
        goal_cells=self.grid.footprint(goal)
        if start is None:
            report_search_wait(self,handle,rid,job,obs,'start_candidate_unavailable',goal,starts,blocked,start_checks=start_checks)
            self.block(rid,job);return
        ends=heapq.nsmallest(12,self.grid.nodes,key=lambda n:math.dist(self.grid.point(n)[:2],goal[:2]))
        end,goal_checks=select_candidate(ends,blocked,
            lambda n:self.grid.can_reserve(handle,self.grid.sweep(self.grid.point(n),goal),self.positions,self.grid.point(n),goal),
            lambda n:self.grid_connection(self.grid.point(n),goal,node_is_start=True),
            connector_first=True,clearance_required=self.runtime_policy['dynamic_edges_enabled'])
        edges=ClearanceEdges(self.grid,handle,self.positions) if self.runtime_policy['dynamic_edges_enabled'] else None
        path=(history_path(self.grid,start,end,blocked,job.get('grid_visits',{}),edges=edges) if history_enabled else self.grid.path(start,end,blocked,edges=edges)) if end is not None else None
        if not path:
            report_search_wait(self,handle,rid,job,obs,'goal_candidate_unavailable' if end is None else 'grid_path_unavailable',
                               goal,starts,blocked,start=start,ends=ends,end=end,start_checks=start_checks,goal_checks=goal_checks)
            self.block(rid,job);return
        here=obs['position_m']
        if len(path)==1 and math.dist(here[:2],self.grid.point(start)[:2])<=.35 and goal_cells & blocked:
            report_search_wait(self,handle,rid,job,obs,'goal_footprint_blocked',goal,starts,blocked,start=start,ends=ends,end=end,goal_cells=goal_cells,start_checks=start_checks,goal_checks=goal_checks)
            self.block(rid,job);return
        destination=candidate_destination(self.grid,path,here,goal,job['step'].get('gait')=='run')
        cells=self.grid.sweep(here,destination)
        # Verify the whole escape independently of the search toggle. This
        # permits an honest edge-filter ablation: a node-only result can use
        # exactly the same exception if all its edges actually are clear.
        escape=[here,*[self.grid.point(n) for n in path],goal]
        clear_escape=all(self.grid.can_reserve(handle,self.grid.sweep(a,b),self.positions,a,b) for a,b in zip(escape,escape[1:]))
        job['drain_escape_points']=escape if clear_escape else None
        drain_exit=goal_cells if clear_escape else None
        reserved=self.admit_reservation(handle,rid,job,[here,destination],drain_exit_cells=drain_exit)
        if not reserved and self.runtime_policy['candidate_repair_enabled'] and not job['blocked_details']['physically_feasible']:
            rejected=[here,destination]
            repair=candidate_alternative(self.grid,handle,here,goal,self.positions,start,ends,blocked,
                job.get('grid_visits',{}) if history_enabled else {},
                lambda a,b:self.grid_connection(a,b,node_is_start=True),job['step'].get('gait')=='run')
            if repair:
                destination=repair['destination_m'];path=repair['path'];cells=self.grid.sweep(here,destination)
                escape=[here,*[self.grid.point(n) for n in path],goal]
                clear_escape=all(self.grid.can_reserve(handle,self.grid.sweep(a,b),self.positions,a,b) for a,b in zip(escape,escape[1:]))
                job['drain_escape_points']=escape if clear_escape else None
                reserved=self.admit_reservation(handle,rid,job,[here,destination],drain_exit_cells=goal_cells if clear_escape else None)
                self.emit('traffic_candidate_repair',route_id=rid,agent=handle,original_candidate_m=rejected,
                    alternative_candidate_m=[here,destination],verified_path_m=escape,target_m=goal,
                    admitted=reserved,guard_priority_since_sim_time=self.fair_gate.pending[rid]['since'],
                    search_attempts=1,strategy='physical_rejection_only')
        if not reserved:self.block(rid,job);return
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
        if len(points)<2:return False
        job['intent_points']=points
        if not self.admit_reservation(handle,rid,job,points,polyline=True):return False
        if job['status']=='blocked':self.emit('traffic_wait_ended',route_id=rid,wait_sim_s=self.now-job['blocked_since'])
        spec={'action':'move_to','target':points[-1],'gait':job['step'].get('gait','walk')}
        if len(points)>2:spec['via']=points[1:-1]
        if 'speed_mps' in job['step']:spec['speed_mps']=job['step']['speed_mps']
        job.update(status='running',blocked_since=None,segment_goal=points[-1],continuous_active=True,continuous_next_goal_index=next_goal,history_segment=False)
        job['native_task_id']=super().start(handle,spec)
        job.pop('tail',None);job.pop('tail_freeze_reported',None)
        if self.runtime_policy['tail_release_enabled']:
            job['tail']=StraightTail(self.grid,points,self.grid.claims[handle],self.now,
                spec.get('speed_mps',2.8 if spec['gait']=='run' else 1.2),
                allow_diagonal=self.runtime_policy['diagonal_tail_release_enabled'])
            job['tail_native_task_id']=job['native_task_id']
            self.emit('traffic_tail_tracking',route_id=rid,agent=handle,native_task_id=job['native_task_id'],
                    eligible=job['tail'].disabled is None,reason=job['tail'].disabled,points_m=points,trail_m=StraightTail.TRAIL_M,
                    diagonal_straight_enabled=self.runtime_policy['diagonal_tail_release_enabled'],
                    original_cells=sorted(self.grid.claims[handle]))
        self.emit('traffic_native_started',route_id=rid,native_task_id=job['native_task_id'],action='continuous_corridor',
                  points_m=points,dense_navmesh_samples=dense_count,reserved_cells=len(self.grid.claims[handle]),final_auto_brake=True,horizon_m=horizon)
        return True

    def update_tail(self,handle,rid,job,obs):
        tail=job.get('tail')
        if not tail or self.owner_routes.get(handle)!=rid or job.get('tail_native_task_id')!=job['native_task_id']:return True
        proof=tail.observe(obs['position_m'],self.now,obs.get('ready',False))
        reason=proof.get('brake')
        if reason:
            return self.stop_tail(handle,rid,job,obs,reason)
        if proof.get('frozen'):
            if not self.grid.footprint(obs['position_m'])<=self.grid.claims.get(handle,set()):
                return self.stop_tail(handle,rid,job,obs,'forward_sample_outside_owned_cells')
            if not job.get('tail_freeze_reported'):
                job['tail_freeze_reported']=True
                self.emit('traffic_tail_tracking_frozen',route_id=rid,agent=handle,reason=proof['frozen'],
                    native_task_id=job['native_task_id'],position_m=obs['position_m'],speed_mps=proof['speed_mps'],
                    remaining_cells=sorted(self.grid.claims[handle]),body_instance_id=self.instances[handle]['traffic_instance_id'])
            return True
        remove=proof['remove']
        if not remove:return True
        owned=self.grid.claims.get(handle,set())
        if owned!=tail.original-tail.released:
            if tail.released:return self.stop_tail(handle,rid,job,obs,'claim_generation_changed')
            tail.disabled='claim_generation_changed';return True
        if remove & self.grid.footprint(obs['position_m']):
            return self.stop_tail(handle,rid,job,obs,'current_body_cell_in_tail_proposal')
        if not self.fair_gate.trim_active(rid,remove,self.instances[handle]['traffic_instance_id']):
            if tail.released:return self.stop_tail(handle,rid,job,obs,'inactive_or_replaced_guard')
            tail.disabled='inactive_or_replaced_guard';return True
        self.grid.claims[handle]=owned-remove;tail.commit(remove)
        self.emit('traffic_tail_released',route_id=rid,agent=handle,native_task_id=job['native_task_id'],
            body_instance_id=self.instances[handle]['traffic_instance_id'],position_m=obs['position_m'],
            original_points_m=tail.points,removed_cells=sorted(remove),remaining_cells=sorted(self.grid.claims[handle]),
            trail_m=tail.TRAIL_M,**{k:v for k,v in proof.items() if k!='remove'})
        return True

    def stop_tail(self,handle,rid,job,obs,reason):
        # Retain the remaining claim while the sole native writer stops.
        super().stop(handle)
        job.update(phase='tail_braking',native_task_id=None,status='blocked',tail_stop_since=None,tail_brake_reason=reason)
        job['blocked_details']={'reason':'tail_safety_stop','since_sim_time':self.now,'blocker_ids':[],
            'blocker_handles':[],'resource_id':'navmesh_corridor','safety_reason':reason,'target_m':job['goals'][-1]}
        self.emit('traffic_tail_safety_brake',route_id=rid,agent=handle,reason=reason,
            position_m=obs['position_m'],released_cells=sorted(job['tail'].released))
        return False
