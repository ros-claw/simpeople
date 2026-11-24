"""Frozen request traces and denominator-preserving replay, without Kit imports."""
import copy,hashlib,json,math
from .errors import SimPeopleError
from .protocol import activity,identifier,number,TERMINAL

def case_hash(case):
    return hashlib.sha256(json.dumps(case,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def validate_case(case, *, allow_diagnostic_triggers=False):
    if case.get('schema_version')!='simpeople.benchmark.v1':raise ValueError('unsupported benchmark schema')
    identifier(case.get('case_id'),'case_id');number(case.get('duration_s'),'duration_s',.1)
    if case.get('submission_mode') not in {'open_arrival','closed_loop'}:raise ValueError('invalid submission_mode')
    if case.get('busy_policy') not in {'reject','queue','supersede'}:raise ValueError('invalid busy_policy')
    if case['busy_policy']=='supersede' and case.get('category') not in {'replacement','cancellation'}:raise ValueError('supersede requires a replacement/cancellation case')
    cap=case.get('max_pending_per_actor',8)
    if isinstance(cap,bool) or not isinstance(cap,int) or not 1<=cap<=100:raise ValueError('invalid queue bound')
    for required in ['scene','actors','requests','capture_profile']:
        if required not in case:raise ValueError('missing '+required)
    if case['capture_profile'] not in {'full','no_encode','render_only','none'}:raise ValueError('invalid capture profile')
    if 'stop_when_complete' in case and not isinstance(case['stop_when_complete'],bool):raise ValueError('invalid early completion policy')
    if case.get('stop_when_complete') and not case.get('finite',True):raise ValueError('continuous workloads must retain their full observation window')
    if not isinstance(case['scene'],dict) or not all(isinstance(case['scene'].get(k),str) and case['scene'][k] for k in ['id','revision']):raise ValueError('missing scene identity/revision')
    if not 1<=len(case['actors'])<=100:raise ValueError('invalid actor count')
    actors=[a['actor_id'] for a in case['actors']]
    if len(set(actors))!=len(actors):raise ValueError('duplicate actor')
    known=set()
    event_ids=set()
    for event in case.get('events',[]):
        if 'trigger' in event and not allow_diagnostic_triggers:
            raise ValueError('event-bound faults require the explicitly enabled diagnostic native driver')
        identifier(event.get('event_id'),'event_id');number(event.get('at_s'),'at_s',0,case['duration_s'])
        methods={'cancel','move_prop'}
        if allow_diagnostic_triggers and isinstance(event.get('trigger'),dict) and event['trigger'].get('kind') in {'native_local_yield_motion','activity_succeeded'}:methods.add('run_activity')
        if event['event_id'] in event_ids or event.get('method') not in methods or not isinstance(event.get('params'),dict):raise ValueError('invalid frozen fault event')
        event_ids.add(event['event_id'])
    labels=set()
    for checkpoint in case.get('checkpoints',[]):
        identifier(checkpoint.get('label'),'checkpoint label');number(checkpoint.get('at_s'),'at_s',0,case['duration_s'])
        if checkpoint['label'] in labels or checkpoint.get('kind')!='queue_exit_blocked':raise ValueError('invalid checkpoint')
        labels.add(checkpoint['label'])
    for r in case['requests']:
        identifier(r.get('request_case_id'),'request_case_id')
        if r['request_case_id'] in known or r['actor_id'] not in actors:raise ValueError('duplicate request or unknown actor')
        number(r.get('at_s',0),'at_s',0,case['duration_s']);number(r['deadline_s'],'deadline_s',.1,case['duration_s'])
        if r['deadline_s']<=r.get('at_s',0):raise ValueError('deadline before arrival')
        number(r.get('think_s',0),'think_s',0,case['duration_s'])
        if r.get('expected_outcome','succeeded') not in TERMINAL:raise ValueError('invalid expected outcome')
        if 'expected_error_code' in r:identifier(r['expected_error_code'],'expected_error_code')
        if 'expected_physical_stop' in r and not isinstance(r['expected_physical_stop'],bool):raise ValueError('invalid expected physical stop')
        if any(d not in known for d in r.get('depends_on',[])):raise ValueError('dependencies must precede successor; cycles forbidden')
        if case['submission_mode']=='open_arrival' and r.get('depends_on'):raise ValueError('open arrival cannot depend on completion')
        activity({'actor_id':r['actor_id'],'steps':r['steps'],'on_blocked':r.get('on_blocked','report')});known.add(r['request_case_id'])
    return copy.deepcopy(case)

class WorkloadReplay:
    def __init__(self,case,client,origin_sim_time=0., *, allow_diagnostic_triggers=False):
        self.case=validate_case(case,allow_diagnostic_triggers=allow_diagnostic_triggers);self.client=client;self.origin=origin_sim_time;self.hash=case_hash(self.case);self.now=0.;self.trace=[]
        self.order=sorted(enumerate(self.case['requests']),key=lambda x:(x[1].get('at_s',0),x[0],x[1]['request_case_id']))
        self.results={r['request_case_id']:{'request_case_id':r['request_case_id'],'actor_id':r['actor_id'],'state':'scheduled','scheduled_at_s':r.get('at_s',0),
            'eligible_at_s':None,'submitted_at_s':None,'admitted_at_s':None,'task_id':None,'error':None,'deadline_s':r['deadline_s'],'depends_on':r.get('depends_on',[])} for r in self.case['requests']}
        self.pending=set()

    def _event(self,kind,**kw):self.trace.append({'kind':kind,'sim_time_s':self.now,**kw})

    def _deadline_due(self,deadline):
        # A continuous observation window censors work still running at its end.
        # Earlier, explicitly scheduled request deadlines remain failures.
        return self.now>=deadline and (self.case.get('finite',True) or deadline<self.case['duration_s'])

    def tick(self,sim_time_s):
        if sim_time_s<self.now:raise ValueError('benchmark clock rewound')
        self.now=float(sim_time_s);states={}
        for result in self.results.values():
            if result['state']!='admitted':continue
            try:t=self.client.call('get_state',{'task_id':result['task_id']})
            except SimPeopleError as err:
                result.update(state='observation_failed',error=err.as_dict());continue
            if t['status'] in TERMINAL:
                finished=t.get('finished_sim_time',self.origin+self.now)-self.origin
                if not self.case.get('finite',True) and result['deadline_s']==self.case['duration_s'] and finished>self.case['duration_s']:
                    result['observed_completion_after_window_s']=finished
                    continue
                result.update(state=t['status'] if finished<=result['deadline_s']+1e-7 else 'deadline_late',finished_at_s=finished,error=t.get('error'))
                self._event('request_terminal',**result)
            elif self._deadline_due(result['deadline_s']):
                result.update(state='deadline_unfinished',observed_task_status=t['status'],unfinished_wait_lower_bound_s=self.now-result['admitted_at_s']);self._event('request_deadline',**result)
        for _,request in self.order:
            key=request['request_case_id'];result=self.results[key]
            if result['state'] not in {'scheduled','waiting'}:continue
            if self._deadline_due(request['deadline_s']):
                result.update(state='not_submitted_deadline',unfinished_wait_lower_bound_s=max(0,self.now-request.get('at_s',0)));self.pending.discard(key);continue
            if self.now>=self.case['duration_s']:continue
            deps=[self.results[x] for x in request.get('depends_on',[])]
            if any(d['state'] not in {'scheduled','waiting','admitted','succeeded'} for d in deps):result['state']='not_submitted_dependency_failed';self.pending.discard(key);continue
            if self.now<request.get('at_s',0) or any(d['state']!='succeeded' for d in deps):continue
            if deps and self.now<max(d['finished_at_s'] for d in deps)+request.get('think_s',0):continue
            if result['eligible_at_s'] is None:result['eligible_at_s']=self.now;self._event('request_eligible',request_case_id=key)
            aid=request['actor_id'];policy=self.case['busy_policy']
            if aid not in states:states[aid]=self.client.call('get_state',{'actor_id':aid})['actors'][0]
            actor=states[aid];task=actor.get('task');busy=bool(task and task['status'] not in TERMINAL or actor.get('seat_cleanup_pending') or actor.get('queue_cleanup_pending'))
            if busy and policy!='supersede':
                if policy=='reject':result['state']='rejected_busy';result['error']={'code':'ACTOR_BUSY','stage':'admission','source':'replay_policy'}
                elif key not in self.pending and sum(self.results[k]['actor_id']==aid for k in self.pending)>=self.case.get('max_pending_per_actor',8):
                    result['state']='rejected_queue_full';result['error']={'code':'ADMISSION_FULL','stage':'admission','source':'replay_policy'}
                else:result['state']='waiting';self.pending.add(key)
                continue
            self.pending.discard(key);result['submitted_at_s']=self.now;result['state']='submitted'
            params={'request_id':'bench-'+hashlib.sha256((self.case['case_id']+':'+key).encode()).hexdigest(),
                'command_id':self.case['case_id'],'attempt_id':'attempt1','actor_id':aid,'steps':copy.deepcopy(request['steps']),
                'if_busy':'supersede' if policy=='supersede' else 'reject'}
            if 'on_blocked' in request:params['on_blocked']=request['on_blocked']
            self._event('request_submitted',request_case_id=key,params=params)
            try:
                receipt=self.client.call('run_activity',params);result.update(state='admitted',task_id=receipt['task_id'],admitted_at_s=self.now)
                states[aid]={**actor,'task':receipt}
            except SimPeopleError as err:result.update(state='rejected',error=err.as_dict())

    def summary(self,at_s=None):
        end=self.now if at_s is None else at_s
        if not self.case.get('finite',True):end=min(end,self.case['duration_s'])
        rows=copy.deepcopy(list(self.results.values()));counts={}
        for r in rows:
            if r['state'] in {'scheduled','waiting','admitted'}:
                r['unfinished_wait_lower_bound_s']=max(0,end-(r['admitted_at_s'] if r['admitted_at_s'] is not None else r['scheduled_at_s']))
                if end>=r['deadline_s'] and (self.case.get('finite',True) or r['deadline_s']<self.case['duration_s']):r['state']='deadline_unfinished' if r['task_id'] else 'not_submitted_deadline'
                else:r['censored']=True
            counts[r['state']]=counts.get(r['state'],0)+1
        total=len(rows);succeeded=counts.get('succeeded',0);censored=sum(bool(r.get('censored')) for r in rows);unsuccessful=total-succeeded-censored
        return {'case_id':self.case['case_id'],'case_sha256':self.hash,'submission_mode':self.case['submission_mode'],'busy_policy':self.case['busy_policy'],
            'scheduled':total,'submitted':sum(r['submitted_at_s'] is not None for r in rows),'admitted':sum(r['task_id'] is not None for r in rows),
            'counts':counts,'denominator':total,'succeeded':succeeded,'unsuccessful':unsuccessful,'censored':censored,
            'unsuccessful_fraction':unsuccessful/total if total and not censored else None,
            'conservation_passed':sum(counts.values())==total,'requests':rows,'timing':'relative simulation seconds; eligible/submitted are observed actual times; no implicit supersede'}

def actor_cycle_seed(seed,actor_id,cycle):
    return int.from_bytes(hashlib.sha256(f'{seed}:{actor_id}:{cycle}'.encode()).digest()[:8],'big')
