"""Explicit external events, safe action boundaries and bounded local responses.

These events are supplied by an agent or a sensor integration; this module does
not pretend that a robot, region detector or collision sensor is present.
"""
import copy
import uuid
from .errors import SimPeopleError
from .protocol import TERMINAL,identifier,number,target

POLICIES={
    'robot_nearby':{'priority':20,'debounce_s':3,'response':'wait','resume':'remaining_activity'},
    'passage_blocked':{'priority':50,'debounce_s':2,'response':'wait_or_detour','resume':'remaining_activity'},
    'call_person':{'priority':40,'debounce_s':1,'response':'visit','resume':'remaining_activity'},
    'region_closed':{'priority':60,'debounce_s':1,'response':'leave','resume':'hold_for_new_instruction'},
}

class Events:
    def __init__(self,engine):
        self.engine=engine;self.records={};self.pending=[];self.active={};self.last_seen={}

    def submit(self,p):
        e=self.engine;kind=p.get('kind')
        if kind not in POLICIES:raise SimPeopleError('INVALID_REQUEST','unknown event kind',supported=list(POLICIES))
        ids=p.get('actor_ids') or ([p['actor_id']] if p.get('actor_id') else None)
        if not isinstance(ids,list) or not ids or len(ids)>100:raise SimPeopleError('INVALID_REQUEST','actor_ids must contain 1–100 actors')
        ids=list(dict.fromkeys(ids))
        for aid in ids:identifier(aid,'actor_id');e.actor(aid)
        source=identifier(p.get('source_id','agent'),'source_id');policy=POLICIES[kind]
        duration=number(p.get('duration_s',3),'duration_s',.01,60)
        goal=target(p['target']) if 'target' in p else None
        if kind in {'call_person','region_closed'} and goal is None:
            raise SimPeopleError('INVALID_REQUEST','event requires a reachable target')
        steps=([{'action':'move_to','target':goal}] if goal is not None else [])
        steps.append({'action':'wait','duration_s':duration})
        # Validate all affected actors before enqueuing or interrupting any one.
        for aid in ids:e.validate({'actor_id':aid,'steps':steps})
        event_id=uuid.uuid4().hex;results=[]
        record={'event_id':event_id,'kind':kind,'source_id':source,'policy':copy.deepcopy(policy),
                'accepted_sim_time':e.sim_time,'results':results}
        for aid in ids:
            key=(kind,source,aid);previous=self.last_seen.get(key)
            status='debounced' if previous is not None and e.sim_time-previous<policy['debounce_s'] else 'queued'
            item={'actor_id':aid,'status':status,'event_id':event_id}
            results.append(item)
            if status=='queued':
                self.last_seen[key]=e.sim_time
                self.pending.append({'record':record,'item':item,'steps':copy.deepcopy(steps)})
        self.records[event_id]=record;e.event('external_event_accepted',event=copy.deepcopy(record))
        return copy.deepcopy(record)

    def manual_override(self,aid):
        # An explicit agent command owns the actor from this point onward.
        for job in list(self.pending):
            if job['item']['actor_id']==aid:
                job['item']['status']='superseded';self.pending.remove(job)
        active=self.active.pop(aid,None)
        if active:
            active['item']['status']='superseded'
            self.engine.event('event_superseded',actor_id=aid,event_id=active['record']['event_id'])

    def tick(self):
        e=self.engine
        if e.paused:return
        for aid,job in list(self.active.items()):
            actor=e.actors.get(aid);task=e.tasks.get(job['task_id'])
            if not actor or actor['task_id']!=job['task_id']:
                job['item']['status']='superseded';self.active.pop(aid);continue
            if task['status'] not in TERMINAL:continue
            job['item']['status']=task['status'];self.active.pop(aid)
            restore=task['status']=='succeeded' and job['record']['policy']['resume']=='remaining_activity'
            assignment=e.population.assignments.get(aid) if e.population else None
            if assignment and restore and not job.get('was_suspended',True):
                # A routine restarts from its declared beginning, avoiding stale
                # seat/queue cursors. An interrupted cycle is not counted complete.
                assignment.update(suspended=False,last_task=task['task_id'],next_start=e.sim_time+1)
            elif restore and job.get('remaining'):
                result=e.cmd_run_activity({'actor_id':aid,'steps':job['remaining']},source='event_restore')
                e.event('event_activity_restored',actor_id=aid,event_id=job['record']['event_id'],task_id=result['task_id'])
            e.event('event_response_ended',actor_id=aid,event_id=job['record']['event_id'],
                    status=task['status'],restored=restore)
        self.pending.sort(key=lambda j:(-j['record']['policy']['priority'],j['record']['accepted_sim_time']))
        for job in list(self.pending):
            aid=job['item']['actor_id'];actor=e.actors.get(aid)
            if e.sim_time-job['record']['accepted_sim_time']>120:
                job['item'].update(status='failed',error={'code':'SAFE_BOUNDARY_TIMEOUT','message':'event waited 120 simulation seconds for a safe interaction boundary'})
                self.pending.remove(job);e.event('event_expired',actor_id=aid,event_id=job['record']['event_id']);continue
            if not actor:job['item']['status']='cancelled';self.pending.remove(job);continue
            current=self.active.get(aid)
            if current and current['record']['policy']['priority']>=job['record']['policy']['priority']:continue
            task=e.tasks.get(actor['task_id'])
            action=task['steps'][task['step_index']]['action'] if task and task['status'] not in TERMINAL else None
            # Ordinary events wait for physical seat release and queue clearance.
            if actor.get('seat') or actor.get('release_seat_when_standing') or action in {'sit','leave_seat','queue'}:
                if job['item']['status']!='deferred':
                    job['item']['status']='deferred';e.event('event_deferred',actor_id=aid,event_id=job['record']['event_id'],reason='interaction_boundary')
                continue
            assignment=e.population.assignments.get(aid) if e.population else None
            job['was_suspended']=assignment['suspended'] if assignment else True
            job['remaining']=copy.deepcopy(task['steps'][task['step_index']:]) if task and task['status'] not in TERMINAL and not assignment else []
            if job['remaining'] and job['remaining'][0]['action'] in {'wait','follow'} and task.get('step_started') is not None:
                step=job['remaining'][0]
                step['duration_s']=max(.01,step['duration_s']-(e.sim_time-task['step_started']))
            if current:
                current['item']['status']='superseded';job['remaining']=current.get('remaining',[])
                job['was_suspended']=current.get('was_suspended',True)
            if assignment:assignment['suspended']=True
            result=e.cmd_run_activity({'actor_id':aid,'steps':job['steps']},source='event')
            job['task_id']=result['task_id'];job['item'].update(status='running',task_id=result['task_id'])
            self.active[aid]=job;self.pending.remove(job)
            e.event('event_response_started',actor_id=aid,event_id=job['record']['event_id'],task_id=result['task_id'])

    def snapshot(self):return copy.deepcopy(list(self.records.values()))
