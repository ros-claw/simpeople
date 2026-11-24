"""Queue phases and physical exit cleanup, driven only by Engine simulation time."""
import math
from .errors import SimPeopleError

class QueueRuntime:
    def queue_token(self,t):
        return t.setdefault('queue_token',(*t['lease_token'],t['step_index']))

    def queue_blocked(self,t,qid,reason,**detail):
        old=t.get('blocked_details',{});since=old.get('since_sim_time',self.sim_time) if old.get('reason')==reason else self.sim_time
        ticket=self.queues.ticket(qid,t['actor_id'],self.queue_token(t))
        members=self.queues.members.get(qid,[])
        blockers=members[:members.index(t['actor_id'])] if reason=='queue_predecessor' and t['actor_id'] in members else members if reason=='admission_wait' else detail.get('traffic',{}).get('blocker_ids',[])
        t['blocked_details']={'reason':reason,'since_sim_time':since,'resource_id':qid,
            'ticket_id':ticket['ticket_id'] if ticket else None,'ticket_rank':ticket['rank'] if ticket else None,
            'blocker_ids':[x for x in blockers if x!=t['actor_id']],
            'deadline_sim_time':t['step_started']+t['steps'][t['step_index']].get('timeout_s',120),
            'remaining_sim_s':max(0,t['step_started']+t['steps'][t['step_index']].get('timeout_s',120)-self.sim_time),
            'retry_at_sim_time':t.get('queue_retry_at',self.sim_time),**detail}
        t['status']='blocked'

    def queue_pose_lost(self,t,a,qid,goal,obs,state,phase):
        distance=math.dist(obs['position_m'][:2],self.backend.resolve_target(goal)[:2])
        if self.arrival_native_valid(t,state) and distance>.3:
            self.queue_blocked(t,qid,phase+'_pose_lost',distance_m=distance)
            if obs['speed_mps']<.15:
                t.setdefault('queue_pose_lost_since',self.sim_time)
                if self.sim_time-t['queue_pose_lost_since']>=.5:
                    t.pop('queue_pose_lost_since',None);self.queue_retry(t,a,qid,phase+'_pose_lost')
            else:t.pop('queue_pose_lost_since',None)
            return True
        t.pop('queue_pose_lost_since',None);return False

    def queue_step(self,t,a,s,obs):
        aid=t['actor_id'];qid=s['target'];slots=self.backend.queue_slots(qid);token=self.queue_token(t)
        if t['step_started'] is None:
            t.update(step_started=self.sim_time,step_phase='queue_admission',queue_slot=None,stable_since=None)
            self.event('step_started',task_id=t['task_id'],actor_id=aid,index=t['step_index'],step=s,native_task_id=None)
        if self.sim_time-t['step_started']>s.get('timeout_s',120):
            raise SimPeopleError('TIMEOUT','queue timed out',stage='execution',phase=t['step_phase'],resource_id=qid,
                                 blocked_details=t.get('blocked_details'),ticket=self.queues.ticket(qid,aid,token))
        if self.sim_time<t.get('queue_retry_at',0):return
        try:self.queues.join(qid,aid,len(slots),token=token)
        except SimPeopleError as err:
            if err.code!='RESOURCE_BUSY':raise
            t['queue_retry_at']=self.sim_time+.2;self.queue_blocked(t,qid,'admission_wait');return
        if t['step_phase']=='queue_egress':
            goal=t['queue_egress_target']
            if t['native_task_id'] is None:self.start_arrival(t,a,goal,obs)
            state=self.backend.task_state(a['handle'],t['native_task_id'])
            if state=='failed':self.queue_retry(t,a,qid,'egress');return
            if self.queue_pose_lost(t,a,qid,goal,obs,state,'egress'):return
            block=getattr(self.backend,'blocked_reason',lambda *_:None)(a['handle'],t['native_task_id'])
            if block:self.queue_blocked(t,qid,'queue_exit_traffic',traffic=block);self.try_recovery(t,a,block)
            else:t['status']='running';t.pop('blocked_details',None)
            if self.settled(t,self.arrival_native_valid(t,state) and math.dist(obs['position_m'][:2],self.backend.resolve_target(goal)[:2])<=.3 and obs['speed_mps']<.15):
                self.event('queue_exit_clear',task_id=t['task_id'],actor_id=aid,resource_id=qid)
                self.queues.remove(aid,token=token);self.event('queue_released',task_id=t['task_id'],actor_id=aid,resource_id=qid);self.advance(t)
            return
        index=self.queues.index(qid,aid)
        if t['queue_slot']!=index or t['native_task_id'] is None:
            self.start_arrival(t,a,slots[index],obs)
            t.update(queue_slot=index,stable_since=None,step_phase='queue_waiting')
            self.event('queue_slot_assigned',task_id=t['task_id'],actor_id=aid,queue=qid,index=index,target=slots[index],native_kind=t['arrival_native_kind'])
        state=self.backend.task_state(a['handle'],t['native_task_id'])
        if state=='failed':self.queue_retry(t,a,qid,'slot');return
        if self.queue_pose_lost(t,a,qid,slots[index],obs,state,'slot'):return
        block=getattr(self.backend,'blocked_reason',lambda *_:None)(a['handle'],t['native_task_id'])
        if block:self.queue_blocked(t,qid,'queue_slot_traffic',traffic=block);self.try_recovery(t,a,block)
        elif index>0:self.queue_blocked(t,qid,'queue_predecessor')
        else:t['status']='running';t.pop('blocked_details',None)
        arrived=self.arrival_native_valid(t,state) and math.dist(obs['position_m'][:2],slots[index][:2])<=.3 and obs['speed_mps']<.15
        if arrived and t.get('queue_arrived_index')!=index:
            t['queue_arrived_index']=index;self.event('queue_slot_arrived',task_id=t['task_id'],actor_id=aid,resource_id=qid,index=index,position_m=obs['position_m'])
        if index==0 and self.settled(t,arrived):
            if t['step_phase']!='serving':
                t['step_phase']='serving';self.queues.mark(qid,aid,token,'serving')
                if t.get('service_ended') is None:
                    t['service_started']=self.sim_time
                    self.event('queue_service_started',task_id=t['task_id'],actor_id=aid,resource_id=qid)
            # Reacquiring a displaced queue target after service completion
            # restores occupancy, not a second service transaction.
            if t.get('service_ended') is not None or self.sim_time-t['service_started']>=s['duration_s']:
                if not t.get('service_ended'):
                    t['service_ended']=self.sim_time;self.event('queue_service_ended',task_id=t['task_id'],actor_id=aid,resource_id=qid)
                try:goal=self.backend.queue_egress(qid,a['handle'])
                except SimPeopleError as err:
                    if err.code!='RESOURCE_BUSY':raise
                    self.queue_retry(t,a,qid,'no_free_egress',stop=False,blocker_ids=err.details.get('blocker_ids',[]));return
                self.start_arrival(t,a,goal,obs)
                t.update(step_phase='queue_egress',queue_egress_target=goal,stable_since=None)
                self.queues.mark(qid,aid,token,'exiting');self.event('queue_exit_started',task_id=t['task_id'],actor_id=aid,resource_id=qid,target=goal)

    def queue_retry(self,t,a,qid,reason,stop=True,**detail):
        if stop and reason in {'slot','egress','slot_pose_lost','egress_pose_lost'}:
            if len(t['recovery_attempts'])>=self.policy['max_recovery_attempts']:
                raise SimPeopleError('BACKEND_TASK_FAILED','queue native retry budget exhausted',resource_id=qid,
                    phase=t['step_phase'],max_attempts=self.policy['max_recovery_attempts'],recovery_attempts=t['recovery_attempts'])
            retry={'at_sim_time':self.sim_time,'attempt':len(t['recovery_attempts'])+1,'reason':reason,
                'strategy':'resubmit_queue_native_target','deadline_sim_time':t['step_deadline_sim_time'],
                'remaining_sim_s':max(0,t['step_deadline_sim_time']-self.sim_time)}
            t['recovery_attempts'].append(retry)
            self.event('recovery_attempt',task_id=t['task_id'],actor_id=t['actor_id'],recovery=retry,max_attempts=self.policy['max_recovery_attempts'])
        self.event('queue_blocked',task_id=t['task_id'],actor_id=t['actor_id'],queue=qid,reason=reason,native_task_id=t['native_task_id'])
        if stop:self.backend.stop(a['handle']);t['native_task_id']=None;t.pop('queue_arrived_index',None)
        t['stable_since']=None;t['queue_retry_at']=self.sim_time+2
        self.queue_blocked(t,qid,reason,**detail)

    def begin_queue_cleanup(self,t,a,reason):
        token=t.get('queue_token')
        if not token:return False
        for qid,members in self.queues.members.items():
            row=self.queues.ticket(qid,t['actor_id'],token)
            if t['actor_id'] in members and row and row['inside']:
                if not a.get('queue_cleanup'):
                    a['queue_cleanup']={'resource_id':qid,'lease_token':token,'task_id':t['task_id'],
                        'started_sim_time':self.sim_time,'reason':reason,'native_task_id':None,'attempts':0,'retry_at':0}
                    self.event('queue_cleanup_started',task_id=t['task_id'],actor_id=t['actor_id'],resource_id=qid,reason=reason)
                    self.queues.mark(qid,t['actor_id'],token,'exiting')
                return True
        self.queues.remove(t['actor_id'],token=token,reason=reason)
        return False

    def cleanup_queue(self,aid,a,paused):
        if paused or self.actors.get(aid) is not a:return
        cleanup=a.get('queue_cleanup')
        if not cleanup:return
        qid=cleanup['resource_id'];obs=self.backend.observe(a['handle'])
        if not obs.get('ready'):return
        native_state=self.backend.task_state(a['handle'],cleanup['native_task_id']) if cleanup['native_task_id'] is not None else None
        clear=min(math.dist(obs['position_m'][:2],p[:2]) for p in self.backend.queue_slots(qid))>=.95 and obs['speed_mps']<.15 and native_state!='running'
        if clear:
            if cleanup.get('clear_since') is None:cleanup['clear_since']=self.sim_time
            if self.sim_time-cleanup['clear_since']<.5:return
            self.queues.remove(aid,token=cleanup['lease_token'],reason=cleanup['reason'])
            self.event('queue_exit_clear',task_id=cleanup['task_id'],actor_id=aid,resource_id=qid,cleanup=True)
            self.event('queue_released',task_id=cleanup['task_id'],actor_id=aid,resource_id=qid,cleanup=True)
            a.pop('queue_cleanup',None);return
        cleanup.pop('clear_since',None)
        if self.sim_time-cleanup['started_sim_time']>15 or cleanup['attempts']>=2 and cleanup['native_task_id'] is None:
            if not cleanup.get('error'):
                cleanup['error']={'code':'QUEUE_EXIT_BLOCKED','stage':'cleanup','resource_id':qid,'physical_occupancy_retained':True}
                self.event('queue_cleanup_failed',task_id=cleanup['task_id'],actor_id=aid,error=cleanup['error'])
            return
        if self.sim_time<cleanup['retry_at']:return
        if cleanup['native_task_id'] is not None:
            if native_state=='failed':
                self.backend.stop(a['handle']);cleanup.update(native_task_id=None,retry_at=self.sim_time+1)
            return
        if obs['speed_mps']>=.15:return
        try:
            target=self.backend.queue_egress(qid,a['handle']);old=self.tasks[cleanup['task_id']]
            cleanup['native_task_id']=self.start_native(old,a,{'action':'move_to','target':target,'gait':'walk'})
            cleanup['attempts']+=1
        except SimPeopleError as err:
            cleanup.update(retry_at=self.sim_time+1,last_error=err.as_dict())
