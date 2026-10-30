"""Main-thread task supervisor. The backend owns every root and bone write.

No wall-clock animation deadlines; tick receives the actual simulation clock.
All transitions are written to the run journal at the point they occur.
"""
import copy
import hashlib
import json
import math
import time
import uuid
from collections import deque
from .management import Management
from .errors import SimPeopleError
from .protocol import TERMINAL, activity, identifier, target, number
from .resources import Resources
from .population import Population, Queues
from .events import Events

READ_METHODS={'inspect_scene','list_assets','list_actions','get_state','validate_activity',
              'session_info','crowd_state','read_events','preflight'}

class Engine(Management):
    def __init__(self,backend,journal):
        self.backend=backend; self.journal=journal
        self.episode_id=uuid.uuid4().hex
        self.session_id=uuid.uuid4().hex
        self.controller_id=None;self.controller_epoch=0
        self.event_sequence=0;self.event_buffer=deque(maxlen=2048)
        self.actors={}; self.tasks={}; self.requests={}
        self.resources=Resources(); self.sim_time=0.0; self.paused=False
        self.population=None;self.queues=Queues()
        self.events=Events(self)
        self.event('episode_started')
        if hasattr(backend,'on_event'):backend.on_event=self.event

    def event(self,kind,**payload):
        self.event_sequence+=1
        event={'kind':kind,'episode_id':self.episode_id,'session_id':self.session_id,
               'cursor':self.event_sequence,'sim_time':self.sim_time,'wall_time':time.time(),**payload}
        self.journal.event(event)
        if kind not in {'tool_call','tool_result'}:self.event_buffer.append(copy.deepcopy(event))

    def call(self,method,params):
        method=method.removeprefix('people.')
        params=copy.deepcopy(params)
        handler=getattr(self,'cmd_'+method,None)
        if handler is None: raise SimPeopleError('METHOD_NOT_FOUND',method)
        if method not in READ_METHODS:
            rid=identifier(params.get('request_id'),'request_id')
            if method!='control_session':self.controller_check(params)
            signature=hashlib.sha256(json.dumps([method,params],sort_keys=True,allow_nan=False).encode()).hexdigest()
            if rid in self.requests:
                prev=self.requests[rid]
                if signature!=prev[0]: raise SimPeopleError('REQUEST_ID_CONFLICT','request_id already has different parameters')
                result=copy.deepcopy(prev[1]); result['idempotent_replay']=True
                return result
        if method not in READ_METHODS and params.get('episode_id') not in {None,self.episode_id}:
            raise SimPeopleError('EPISODE_MISMATCH','request targets an old episode',current_episode_id=self.episode_id)
        if params.get('session_id') not in {None,self.session_id}:
            raise SimPeopleError('SESSION_MISMATCH','request targets another runtime session',session_id=self.session_id)
        self.event('tool_call',method=method,params=params)
        result=handler(params)
        if method not in READ_METHODS: self.requests[rid]=(signature,copy.deepcopy(result))
        self.event('tool_result',method=method,result=result)
        return result

    def actor(self,actor_id):
        if actor_id not in self.actors: raise SimPeopleError('ACTOR_NOT_FOUND',str(actor_id))
        return self.actors[actor_id]

    def cmd_inspect_scene(self,p):
        return {**self.backend.inspect_scene(),'episode_id':self.episode_id,'session_id':self.session_id,
                'sim_time':self.sim_time,'paused':self.paused,'actors':list(self.actors),
                'resources':self.resources.snapshot()}

    def cmd_list_assets(self,p): return {'assets':self.backend.list_assets()}
    def cmd_populate(self,p):
        seed=p.get('seed',42)
        if isinstance(seed,bool) or not isinstance(seed,int):raise SimPeopleError('INVALID_REQUEST','seed must be an integer')
        if self.population is None:self.population=Population(self,seed)
        elif self.population.seed!=seed:raise SimPeopleError('INVALID_REQUEST','reset population before changing its seed')
        return self.population.populate(p)
    def cmd_list_actions(self,p):
        if hasattr(self.backend,'refresh_quality_revisions'):self.backend.refresh_quality_revisions()
        a=self.actor(p['actor_id'])
        return {'actor_id':p['actor_id'],'actions':self.backend.list_actions(a['handle'])}

    def cmd_spawn(self,p):
        aid=identifier(p.get('actor_id'),'actor_id')
        for field in ('role','group'):
            if p.get(field) is not None:identifier(p[field],field)
        if aid in self.actors: raise SimPeopleError('ACTOR_EXISTS',aid)
        handle=self.backend.spawn(aid,p.get('asset_id','default'),target(p.get('spawn_anchor',[0,0,0])))
        self.actors[aid]={'handle':handle,'control_epoch':0,'task_id':None,'seat':None,'cycles':0,
                          'role':p.get('role'),'group':p.get('group'),
                          'release_seat_when_standing':False}
        return {'actor_id':aid,'episode_id':self.episode_id,'backend':'native','prim_path':handle,
                'status':'accepted'}

    def cmd_despawn(self,p):
        aid=p['actor_id']; a=self.actor(aid)
        self.abort_actor(aid,'despawn')
        self.backend.despawn(a['handle']); del self.actors[aid]
        return {'actor_id':aid,'status':'succeeded'}

    def validate(self,p):
        steps=activity(p); a=self.actor(p['actor_id'])
        for step in steps: self.backend.validate(a['handle'],step)
        return steps

    def cmd_validate_activity(self,p):
        return {'valid':True,'steps':self.validate(p)}

    def cmd_move_to(self,p):
        fields={'target','gait','speed_mps','tolerance_m','timeout_s','resource_id','via'}
        return self.cmd_run_activity({**p,'steps':[{'action':'move_to',**{k:v for k,v in p.items() if k in fields}}]})

    def cmd_perform(self,p):
        fields={'action','target','duration_s','distance_m','timeout_s'}
        return self.cmd_run_activity({**p,'steps':[{k:v for k,v in p.items() if k in fields}]})

    def cmd_run_activity(self,p,source='agent'):
        steps=self.validate(p)  # Never cancel a valid old plan for an invalid new plan.
        aid=p['actor_id']; a=self.actor(aid)
        if source=='agent':self.events.manual_override(aid)
        if source=='agent' and self.population and aid in self.population.assignments:
            self.population.assignments[aid]['suspended']=True
        self.abort_actor(aid,'superseded')
        a['control_epoch']+=1
        tid=uuid.uuid4().hex
        task={'task_id':tid,'activity_id':tid,'episode_id':self.episode_id,'actor_id':aid,
              'control_epoch':a['control_epoch'],'status':'accepted','source':source,'steps':steps,'step_index':0,
              'accepted_sim_time':self.sim_time,'accepted_wall_time':time.time(),
              'step_started':None,'step_phase':None,'native_task_id':None,'stable_since':None,
              'started_sim_time':None,'finished_sim_time':None,'error':None,'cancel_requested':False}
        self.tasks[tid]=task; a['task_id']=tid
        self.event('task_accepted',task=copy.deepcopy(task))
        return self.public(task)

    def public(self,t):
        result=copy.deepcopy({k:v for k,v in t.items() if k not in {'stable_since','progress_position','progress_time'}})
        result['backend_task_id']=t.get('native_task_id')
        if isinstance(result.get('native_task_id'),str):result['native_task_id']=None
        return result

    def finish(self,t,status,error=None):
        if t['status'] in TERMINAL:return
        t.update(status=status,error=error,finished_sim_time=self.sim_time,finished_wall_time=time.time())
        aid=t['actor_id']; a=self.actors.get(aid)
        self.queues.remove(aid)
        if status!='succeeded':
            if a and a['seat']:a['release_seat_when_standing']=True
            else:self.resources.release(aid)
        if a:
            if status=='succeeded': a['cycles']+=1
        self.event('task_ended',task=self.public(t))

    def abort_actor(self,aid,reason):
        a=self.actor(aid); old=self.tasks.get(a['task_id'])
        occupied=a['seat']
        if old and old['status'] not in TERMINAL:
            self.backend.stop(a['handle'])
            self.finish(old,'cancelled',{'code':'CANCELLED','message':reason})
        if occupied and reason not in {'despawn','reset','process_shutdown','timeline_rewound'}:
            # Keep physical occupancy reserved throughout the stand-up transition.
            self.backend.stop(a['handle']);a['seat']=occupied
            a['release_seat_when_standing']=True;a['cleanup_started']=self.sim_time
            for key in ['cleanup_task','cleanup_target','cleanup_retry_at','cleanup_error']:a.pop(key,None)
        else:
            self.resources.release(aid); a['seat']=None

    def cmd_cancel(self,p):
        tid=p.get('task_id')
        if not tid:
            tid=self.actor(p.get('actor_id'))['task_id']
        if tid not in self.tasks: raise SimPeopleError('TASK_NOT_FOUND',str(tid))
        t=self.tasks[tid]
        if t['status'] in TERMINAL:return self.public(t)
        a=self.actor(t['actor_id']); a['control_epoch']+=1
        self.events.manual_override(t['actor_id'])
        if self.population and t['actor_id'] in self.population.assignments:
            self.population.assignments[t['actor_id']]['suspended']=True
        self.backend.stop(a['handle'])
        t['cancel_requested']=True
        t['stable_since']=None
        if a['seat']:
            a['release_seat_when_standing']=True;a['cleanup_started']=self.sim_time
            for key in ['cleanup_task','cleanup_target','cleanup_retry_at','cleanup_error']:a.pop(key,None)
        t['cancel_sim_time']=self.sim_time; t['cancel_wall_time']=time.time()
        self.event('cancel_requested',task_id=tid,control_epoch=a['control_epoch'])
        return {**self.public(t),'cancellation':'accepted'}

    def cmd_get_state(self,p):
        if p.get('task_id'):
            if p['task_id'] not in self.tasks: raise SimPeopleError('TASK_NOT_FOUND',p['task_id'])
            t=self.tasks[p['task_id']]
            return {**self.public(t),'observation':self.backend.observe(self.actor(t['actor_id'])['handle'])
                    if t['actor_id'] in self.actors and t['episode_id']==self.episode_id else None}
        ids=[p['actor_id']] if p.get('actor_id') else list(self.actors)
        return {'episode_id':self.episode_id,'sim_time':self.sim_time,'paused':self.paused,
                'events':self.events.snapshot(),
                'actors':[{ 'actor_id':aid,'control_epoch':self.actor(aid)['control_epoch'],
                    'task':self.public(self.tasks[self.actor(aid)['task_id']]) if self.actor(aid)['task_id'] else None,
                    'observation':self.backend.observe(self.actor(aid)['handle']),
                    'seat':self.actor(aid)['seat'],'seat_cleanup_pending':bool(self.actor(aid).get('release_seat_when_standing')),
                    'completed_activities':self.actor(aid)['cycles']} for aid in ids]}

    def cmd_pause(self,p):
        self.backend.pause(); self.paused=True
        return {'paused':True,'sim_time':self.sim_time}

    def cmd_resume(self,p):
        self.backend.resume(); self.paused=False
        return {'paused':False,'sim_time':self.sim_time}

    def cmd_reset(self,p):
        if p.get('episode_id') not in {None,self.episode_id}:raise SimPeopleError('EPISODE_MISMATCH','reset targets stale episode')
        for aid in list(self.actors):
            self.abort_actor(aid,'reset'); self.backend.despawn(self.actors[aid]['handle'])
        self.actors.clear(); self.resources=Resources();self.population=None;self.queues=Queues();self.events=Events(self)
        self.episode_id=uuid.uuid4().hex
        self.event('episode_started',reason='reset')
        return {'episode_id':self.episode_id,'status':'succeeded'}

    def cmd_record(self,p):
        if p.get('mode')=='camera':
            if p.get('view') not in {'overview','follow','seat_side','gait_side'}:raise SimPeopleError('INVALID_REQUEST','invalid camera view')
            if p['view']!='overview':self.actor(p.get('actor_id'))
        return self.backend.record(p)

    def cmd_signal_event(self,p):return self.events.submit(p)

    def cmd_move_prop(self,p):
        position=target(p.get('position_m'))
        if not isinstance(position,list):raise SimPeopleError('INVALID_REQUEST','position_m must be coordinates')
        result=self.backend.move_prop(p.get('prop_id'),position)
        self.event('prop_moved',**result)
        return result

    def tick(self,sim_time,paused=False):
        if sim_time+1e-7<self.sim_time:
            for aid in list(self.actors):self.abort_actor(aid,'timeline_rewound')
            self.episode_id=uuid.uuid4().hex
            self.event('episode_started',reason='timeline_rewound')
        self.sim_time=sim_time; self.paused=paused
        if not paused and hasattr(self.backend,'tick'):self.backend.tick(sim_time)
        for aid,a in list(self.actors.items()):
            if a.get('release_seat_when_standing'):
                self.cleanup_seat(aid,a,paused)
            t=self.tasks.get(a['task_id'])
            if not t or t['status'] in TERMINAL:continue
            if paused:
                if t['status'] in {'accepted','running','blocked'}:t['resume_status']=t['status'];t['status']='paused'
                continue
            if t['status']=='paused':t['status']=t.pop('resume_status','running')
            try:
                obs=self.backend.observe(a['handle'])
                if not obs.get('ready'):
                    if t['cancel_requested']:self.finish(t,'cancelled',{'code':'CANCELLED','message':'controller absent'})
                    elif not paused and sim_time-t['accepted_sim_time']>10:
                        self.finish(t,'failed',{'code':'SIM_NOT_READY','message':'agent absent for 10 simulation seconds'})
                    continue
                if t['cancel_requested']:
                    physically_stopped=obs['speed_mps']<0.15 and not a.get('release_seat_when_standing')
                    if self.settled(t,physically_stopped):self.finish(t,'cancelled',{'code':'CANCELLED','message':'stopped'})
                    elif not paused and sim_time-t['cancel_sim_time']>15:
                        self.finish(t,'failed',{'code':'STOP_FAILED','message':'native stop did not settle within 15 simulation seconds'})
                    continue
                if t['control_epoch']!=a['control_epoch']:continue
                if t['started_sim_time'] is None:
                    t['started_sim_time']=sim_time;t['started_wall_time']=time.time()
                    t['status']='running';self.event('task_started',task_id=t['task_id'],actor_id=aid)
                self.step(t,a,obs)
            except SimPeopleError as e:
                self.backend.stop(a['handle']);self.finish(t,'failed',e.as_dict())
            except Exception as e:
                self.backend.stop(a['handle']);self.finish(t,'failed',{'code':'BACKEND_ERROR','message':str(e)})
        self.events.tick()
        if self.population:self.population.tick()

    def settled(self,t,condition,duration=0.5):
        if not condition:t['stable_since']=None;return False
        if t['stable_since'] is None:t['stable_since']=self.sim_time
        return self.sim_time-t['stable_since']>=duration-1e-7

    def advance(self,t):
        s=t['steps'][t['step_index']]
        assignment=self.population.assignments.get(t['actor_id']) if self.population else None
        if assignment and assignment.get('role')=='responder' and t['source']=='scheduler' and t['step_index']==0:
            self.event('scheduled_role_event',actor_id=t['actor_id'],event_type='work_call',
                       response_target=t['steps'][1].get('target'))
        self.event('step_ended',task_id=t['task_id'],actor_id=t['actor_id'],index=t['step_index'],action=s['action'])
        if s.get('resource_id'):self.resources.release(t['actor_id'],s['resource_id'])
        t['step_index']+=1;t['step_started']=None;t['step_phase']=None;t['native_task_id']=None;t['stable_since']=None
        for key in ['arrival_native_kind','queue_retry_at','queue_egress_target','queue_slot','service_started']:
            t.pop(key,None)
        if t['step_index']==len(t['steps']):self.finish(t,'succeeded')

    def start_arrival(self,t,a,goal,obs,step=None):
        # The SDK rejects some zero-distance MoveTo requests. Settle through a real
        # Idle transition instead, and still verify the measured pose for 0.5 s.
        spec=copy.deepcopy(step) if step else {'action':'move_to','target':goal,'gait':'walk'}
        if spec.get('via'):
            # A leading point at the current position makes this local SDK's
            # MoveAlong finish immediately. Retain all later route points.
            while spec['via'] and math.dist(obs['position_m'][:2],self.backend.resolve_target(spec['via'][0])[:2])<=.3:
                spec['via'].pop(0)
            if not spec['via']:spec.pop('via')
        already=math.dist(obs['position_m'][:2],self.backend.resolve_target(goal)[:2])<=spec.get('tolerance_m',.3)
        idle=already and obs['speed_mps']<.15 and not spec.get('via')
        t['arrival_native_kind']='idle_at_target' if idle else 'move_along' if spec.get('via') else 'move_to'
        t['native_task_id']=self.backend.start(a['handle'],{'action':'settle'} if idle else spec)
        if isinstance(t['native_task_id'],str):t['arrival_native_kind']='reservation_route'
        t['stable_since']=None

    def arrival_native_valid(self,t,state):
        return state=='succeeded' or (t.get('arrival_native_kind')=='idle_at_target' and state=='running')

    def step(self,t,a,obs):
        s=t['steps'][t['step_index']]; action=s['action']; aid=t['actor_id']
        if a.get('release_seat_when_standing'):
            t['status']='blocked'
            if self.sim_time-a.get('cleanup_started',self.sim_time)>15:
                raise SimPeopleError('STOP_FAILED','previous seated action has not completed stand-up')
            return
        if action=='queue':
            self.queue_step(t,a,s,obs);return
        if t['step_started'] is None:
            resource=s.get('resource_id') or (s['target'] if action=='sit' else None)
            if resource and not self.resources.acquire(resource,aid):
                t['status']='blocked'
                if t.get('resource_wait_started') is None:t['resource_wait_started']=self.sim_time
                if self.sim_time-t['resource_wait_started']>s.get('timeout_s',120):
                    raise SimPeopleError('RESOURCE_BUSY','resource wait timed out',resource=resource)
                return
            t['status']='running';t['resource_wait_started']=None
            if action=='sit':a['seat']=s['target']
            t['step_started']=self.sim_time;t['stable_since']=None;t['step_phase']='executing'
            t['progress_time']=self.sim_time;t['progress_position']=obs['position_m']
            if action=='move_to':self.start_arrival(t,a,s['target'],obs,s)
            else:t['native_task_id']=self.backend.start(a['handle'],s)
            if action=='leave_seat' and a['seat']:
                a['release_seat_when_standing']=True;a['cleanup_started']=self.sim_time
            self.event('step_started',task_id=t['task_id'],actor_id=aid,index=t['step_index'],step=s,
                       backend_task_id=t['native_task_id'],native_task_id=t['native_task_id'] if isinstance(t['native_task_id'],int) else None,
                       native_kind=t.get('arrival_native_kind',action))
        elapsed=self.sim_time-t['step_started']
        if elapsed>s.get('timeout_s',max(120,s.get('duration_s',0)+30)):
            raise SimPeopleError('TIMEOUT','step timed out',step=t['step_index'])
        native=self.backend.task_state(a['handle'],t['native_task_id']) if t['native_task_id'] else 'running'
        if native=='failed' and action!='leave_seat' and t['step_phase']!='follow_stopping':
            detail=getattr(self.backend,'task_error',lambda *_:None)(a['handle'],t['native_task_id'])
            raise SimPeopleError('BACKEND_TASK_FAILED','backend task failed',backend_task_id=t['native_task_id'],
                                native_task_id=t['native_task_id'] if isinstance(t['native_task_id'],int) else None,native_error=detail)
        if action=='wait':
            if elapsed>=s['duration_s']:self.advance(t)
        elif action=='move_to':
            goal=self.backend.resolve_target(s['target'])
            distance=math.dist(obs['position_m'][:2],goal[:2])
            block=getattr(self.backend,'blocked_reason',lambda *_:None)(a['handle'],t['native_task_id'])
            if block:
                t['status']='blocked';t['blocked_details']=block;t['progress_time']=self.sim_time
                return
            t['status']='running';t.pop('blocked_details',None)
            if self.settled(t,self.arrival_native_valid(t,native) and distance<=s.get('tolerance_m',0.3) and obs['speed_mps']<0.15):self.advance(t);return
            if math.dist(obs['position_m'][:2],t['progress_position'][:2])>0.10:
                t['progress_time']=self.sim_time;t['progress_position']=obs['position_m']
            elif self.sim_time-t['progress_time']>6 and distance>0.3:
                raise SimPeopleError('TARGET_BLOCKED','no movement progress for 6 simulation seconds',distance_m=distance)
        elif action=='sit':
            aligned=self.backend.is_seated(a['handle'],s['target'],obs)
            entry_ready=getattr(self.backend,'seat_entry_ready',lambda *_:True)(a['handle'],s['target'],obs)
            if aligned and (t['step_phase']=='holding' or self.settled(t,entry_ready)):
                if t.get('pose_violation_started') is not None:
                    gap=self.sim_time-t.pop('pose_violation_started')
                    t['hold_paused_s']=t.get('hold_paused_s',0)+gap
                    self.event('seat_pose_recovered',actor_id=aid,task_id=t['task_id'],deviation_duration_s=gap)
                if t['step_phase']!='holding':
                    t['step_phase']='holding';t['hold_started']=self.sim_time;t['hold_paused_s']=0;a['seat']=s['target']
                    self.event('seat_occupied',actor_id=aid,seat=s['target'])
                if self.sim_time-t['hold_started']-t.get('hold_paused_s',0)>=s['duration_s']:self.advance(t)
            elif not aligned:
                t['stable_since']=None
                if t['step_phase']=='holding':
                    if t.get('pose_violation_started') is None:
                        t['pose_violation_started']=self.sim_time
                        self.event('seat_pose_deviation',actor_id=aid,task_id=t['task_id'],
                                   position_m=obs['position_m'],speed_mps=obs['speed_mps'])
                    elif self.sim_time-t['pose_violation_started']>=.3:
                        raise SimPeopleError('SEAT_ALIGNMENT_LOST','seated pose invalid continuously for 0.3 simulation seconds')
        elif action=='leave_seat':
            if not a.get('release_seat_when_standing') and self.backend.is_standing(a['handle'],obs) and self.settled(t,obs['speed_mps']<0.15):
                self.resources.release(aid);a['seat']=None;self.advance(t)
        elif action=='look_at':
            goal=self.backend.resolve_target(s['target']);p=obs['position_m'];f=obs['facing_direction']
            delta=[goal[i]-p[i] for i in range(2)];norm=math.hypot(*delta)
            aligned=norm<0.05 or sum(f[i]*delta[i] for i in range(2))/max(norm,1e-9)>math.cos(math.radians(15))
            if self.settled(t,aligned and obs['speed_mps']<0.15):self.advance(t)
        elif action=='follow':
            if elapsed>=s['duration_s']:
                if t['step_phase']!='follow_stopping':
                    self.backend.stop(a['handle']);t['step_phase']='follow_stopping';t['stable_since']=None
                elif self.settled(t,obs['speed_mps']<.15):self.advance(t)
        elif action=='custom_action':
            if native=='succeeded':self.advance(t)

    def cleanup_seat(self,aid,a,paused):
        if paused:return
        a.setdefault('cleanup_started',self.sim_time)
        try:
            obs=self.backend.observe(a['handle'])
            if not obs.get('ready'):return
            if not a.get('cleanup_task') and not self.backend.is_standing(a['handle'],obs):return
            if self.sim_time<a.get('cleanup_retry_at',0):return
            if 'cleanup_target' not in a:
                clear_here=getattr(self.backend,'can_release_seat_here',lambda *_:False)(a['handle'],a['seat'],obs)
                a['cleanup_target']=None if clear_here else self.backend.seat_egress(a['seat'],a['handle']) if hasattr(self.backend,'seat_egress') else None
            egress=a['cleanup_target']
            if egress:
                if not a.get('cleanup_task'):
                    a['cleanup_task']=self.backend.start(a['handle'],{'action':'move_to','target':egress,'gait':'walk'})
                    self.event('seat_egress_started',actor_id=aid,seat=a['seat'],target=egress)
                    return
                state=self.backend.task_state(a['handle'],a['cleanup_task'])
                if state=='failed':
                    self.event('seat_egress_blocked',actor_id=aid,seat=a['seat'],target=egress)
                    self.backend.stop(a['handle']);a.pop('cleanup_task',None);a.pop('cleanup_target',None)
                    a['cleanup_retry_at']=self.sim_time+2
                    return
                if state!='succeeded':return
                if math.dist(obs['position_m'][:2],self.backend.resolve_target(egress)[:2])>.3 or obs['speed_mps']>=.15:return
            self.resources.release(aid)
            self.event('seat_released',actor_id=aid,seat=a['seat'])
            a['seat']=None;a['release_seat_when_standing']=False
            a.pop('cleanup_task',None);a.pop('cleanup_started',None)
            a.pop('cleanup_error',None)
            a.pop('cleanup_target',None)
            a.pop('cleanup_retry_at',None)
        except SimPeopleError as e:
            if not a.get('cleanup_error'):
                a['cleanup_error']=e.as_dict();self.event('seat_cleanup_error',actor_id=aid,error=e.as_dict())

    def queue_step(self,t,a,s,obs):
        aid=t['actor_id'];qid=s['target'];slots=self.backend.queue_slots(qid)
        if t['step_started'] is None:
            t['step_started']=self.sim_time
            t['step_phase']='queue_waiting';t['queue_slot']=None;t['stable_since']=None
            self.event('step_started',task_id=t['task_id'],actor_id=aid,index=t['step_index'],step=s,native_task_id=None)
        if self.sim_time-t['step_started']>s.get('timeout_s',120):raise SimPeopleError('TIMEOUT','queue timed out')
        if self.sim_time<t.get('queue_retry_at',0):return
        try:self.queues.join(qid,aid,len(slots))
        except SimPeopleError as err:
            if err.code!='RESOURCE_BUSY':raise
            t['status']='blocked';t['queue_retry_at']=self.sim_time+2;return
        if t['step_phase']=='queue_egress':
            goal=t['queue_egress_target']
            if t['native_task_id'] is None:self.start_arrival(t,a,goal,obs)
            state=self.backend.task_state(a['handle'],t['native_task_id'])
            if state=='failed':self.queue_retry(t,a,qid,'egress');return
            t['status']='running'
            if self.settled(t,self.arrival_native_valid(t,state) and math.dist(obs['position_m'][:2],self.backend.resolve_target(goal)[:2])<=.3 and obs['speed_mps']<.15):
                self.queues.remove(aid);self.advance(t)
            return
        index=self.queues.index(qid,aid)
        if t['queue_slot']!=index or t['native_task_id'] is None:
            self.start_arrival(t,a,slots[index],obs)
            t['queue_slot']=index;t['stable_since']=None;t['step_phase']='queue_waiting'
            self.event('queue_slot_assigned',actor_id=aid,queue=qid,index=index,target=slots[index],native_kind=t['arrival_native_kind'])
        state=self.backend.task_state(a['handle'],t['native_task_id'])
        if state=='failed':self.queue_retry(t,a,qid,'slot');return
        t['status']='running'
        arrived=self.arrival_native_valid(t,state) and math.dist(obs['position_m'][:2],slots[index][:2])<=.3 and obs['speed_mps']<.15
        if index==0 and self.settled(t,arrived):
            if t['step_phase']!='serving':t['step_phase']='serving';t['service_started']=self.sim_time
            if self.sim_time-t['service_started']>=s['duration_s']:
                try:goal=self.backend.queue_egress(qid,a['handle'])
                except SimPeopleError as err:
                    if err.code!='RESOURCE_BUSY':raise
                    self.queue_retry(t,a,qid,'no_free_egress',stop=False);return
                self.start_arrival(t,a,goal,obs)
                t['step_phase']='queue_egress';t['queue_egress_target']=goal;t['stable_since']=None

    def queue_retry(self,t,a,qid,reason,stop=True):
        self.event('queue_blocked',actor_id=t['actor_id'],queue=qid,reason=reason,native_task_id=t['native_task_id'])
        if stop:self.backend.stop(a['handle']);t['native_task_id']=None
        t['status']='blocked';t['stable_since']=None;t['queue_retry_at']=self.sim_time+2
