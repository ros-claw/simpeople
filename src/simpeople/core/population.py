"""Seeded activity programs. Runs locally without per-frame model calls."""
import random
from .errors import SimPeopleError
from .protocol import identifier

ROLES=['commuter','patrol','visitor','rest','queue','runner','responder']

def patrol_stops(ordinal):
    """Independent stops for the configured fifteen industrial patrol groups."""
    if not 0<=ordinal<15:raise ValueError('patrol ordinal outside configured groups')
    if ordinal==14:
        # The fifteenth group uses open interior bays instead of crowding the
        # north/west corner or a perimeter home/queue slot.
        return [[-12.5,-6.25,0],[17.5,16.25,0],[12.5,-6.25,0]]
    along=-18.75+ordinal*2.5
    return [[-17.5,along,0],[-17.5+ordinal*2.5,16.25,0],[17.5,along,0]]

def responder_stop(ordinal):
    """Independent response bays in the open strip south of the workstations."""
    if not 0<=ordinal<16:raise ValueError('responder ordinal outside configured bays')
    columns=[-13.75,-11.25,-8.75,-6.25,-3.75,8.75,11.25,13.75]
    return [columns[ordinal%8],-2.5*(ordinal//8),0]

def home_slot(index):
    """Perimeter bays keep resting actors outside service and circulation areas."""
    ring=index//56;k=index%56;edge=k//14;n=k%14
    outside=20-ring*1.2;along=-18.5+n*2.7
    return ([along,-outside,0] if edge==0 else [outside,along,0] if edge==1
            else [-along,outside,0] if edge==2 else [-outside,-along,0])

class Population:
    def __init__(self,engine,seed):
        self.engine=engine;self.rng=random.Random(seed);self.seed=seed;self.assignments={}

    def populate(self,p):
        count=p.get('count',p.get('people',10))
        if isinstance(count,bool) or not isinstance(count,int) or not 1<=count<=100:
            raise SimPeopleError('INVALID_REQUEST','count must be an integer in [1,100]')
        pools=p.get('asset_pool') or ['default']
        known={a['asset_id'] for a in self.engine.backend.list_assets()}
        if not isinstance(pools,list) or not pools or any(a not in known for a in pools):
            raise SimPeopleError('ASSET_INCOMPATIBLE','asset_pool contains unknown assets')
        prefix=identifier(p.get('prefix','person'),'prefix')
        roles=p.get('roles',ROLES)
        if not isinstance(roles,list) or not roles or any(r not in ROLES for r in roles):
            raise SimPeopleError('INVALID_REQUEST','unsupported role list')
        patrol_count=sum(x['role']=='patrol' for x in self.assignments.values())+sum(roles[i%len(roles)]=='patrol' for i in range(count))
        if patrol_count>15:
            raise SimPeopleError('INVALID_REQUEST','industrial layout has fifteen independent patrol stop groups',requested_patrols=patrol_count)
        responder_count=sum(x['role']=='responder' for x in self.assignments.values())+sum(roles[i%len(roles)]=='responder' for i in range(count))
        if responder_count>16:
            raise SimPeopleError('INVALID_REQUEST','industrial layout has sixteen independent responder bays',requested_responders=responder_count)
        results=[]
        for i in range(count):
            aid=f'{prefix}_{i+1:03d}';role=roles[i%len(roles)];asset=pools[i%len(pools)]
            spawn=home_slot(i)
            try:
                result=self.engine.cmd_spawn({'actor_id':aid,'asset_id':asset,'spawn_anchor':spawn})
                self.assignments[aid]={'role':role,'asset_id':asset,'index':i,'home_m':spawn,'suspended':False,'suspended_reason':None,
                    'next_start':self.engine.sim_time+self.rng.uniform(0,8),'cycle':0,'failures':0,'last_task':None}
                results.append({**result,'role':role})
            except SimPeopleError as e:results.append({'actor_id':aid,'error':e.as_dict()})
        return {'seed':self.seed,'results':results,'created':sum('error' not in r for r in results),
                'rejected':sum('error' in r for r in results),
                'patrol_stop_profile':'legacy-five-stop-v1' if self.legacy_patrol_layout() else 'independent-grid-v2',
                'responder_stop_profile':'legacy-three-station-v1' if self.legacy_responder_layout() else 'independent-grid-v3'}

    def legacy_responder_layout(self):
        return (len(self.assignments)<=30 and
                all(x['role']==ROLES[x['index']%len(ROLES)] for x in self.assignments.values()))

    def legacy_patrol_layout(self):
        return (sum(x['role']=='patrol' for x in self.assignments.values())<=5 and
                all(x['role']==ROLES[x['index']%len(ROLES)] for x in self.assignments.values()))

    def program(self,assignment):
        i=assignment['index'];role=assignment['role'];rng=self.rng
        # Long industrial routes include native deceleration at reserved segment
        # ends and finite traffic waits. The 120 s generic action deadline cut
        # off a progressing 30-person patrol twice; keep a finite explicit 240 s
        # budget here. The 6 s unexpected no-progress guard still applies.
        def move(target,gait='walk',**extra):return {'action':'move_to','target':target,'gait':gait,'timeout_s':240,**extra}
        def wait(lo=3,hi=8):return {'action':'wait','duration_s':rng.uniform(lo,hi)}
        base=self.engine.backend.resolve_target(f'work_{i%8:02d}')
        work=[base[0]+((i//8)%3-1)*1.3,base[1]-(i//24)*1.3,0]
        home=assignment.get('home_m',home_slot(i))
        inward=[move(home)]
        if role=='commuter':return [move(work),wait(6,14)]+inward+[wait()]
        if role=='patrol':
            patrols=[x for x in self.assignments.values() if x['role']=='patrol']
            if self.legacy_patrol_layout():
                # Retain the already-validated 10/30-person recipe exactly.
                stops=[[-17,-2+i%5*1.3,0],[-3+i%5*1.5,16.5,0],[17,-2+i%5*1.3,0]]
            else:
                ordinal=next(n for n,value in enumerate(patrols) if value is assignment)
                stops=patrol_stops(ordinal)
            return [move(stops[0]),move(stops[1]),wait(),move(stops[2])]+inward+[wait()]
        if role=='visitor':return [{'action':'queue','target':f'queue_{i%3}','duration_s':rng.uniform(3,6)},move(work),wait()]+inward
        if role=='rest':return [move(work),wait(),{'action':'sit','target':f'seat_{i%6:02d}','duration_s':rng.uniform(5,12)},
                                {'action':'leave_seat'}]+inward+[wait()]
        if role=='queue':return [{'action':'queue','target':f'queue_{i%3}','duration_s':rng.uniform(2,5)},move(home),wait()]
        if role=='runner':
            offset=(i//len(ROLES))*1.2
            return [move([-18+offset,18,0]),move([18-offset,18,0],'run'),
                             move([18-offset,16.5,0]),wait()]+inward+[wait()]
        # Response role waits for a scheduled local event, then moves to a known station.
        response_target=f'event_station_{i%3}'
        if not self.legacy_responder_layout():
            responders=[x for x in self.assignments.values() if x['role']=='responder']
            response_target=responder_stop(next(n for n,value in enumerate(responders) if value is assignment))
        return [wait(5,12),move(response_target),wait(2,4),move(work),wait()]+inward

    def tick(self):
        e=self.engine
        if e.paused:return
        for aid,assignment in self.assignments.items():
            if aid not in e.actors or assignment['suspended']:continue
            actor=e.actors[aid];task=e.tasks.get(actor['task_id'])
            if task and task['status'] not in {'succeeded','failed','cancelled'}:continue
            if task and task['task_id']!=assignment['last_task']:
                assignment['last_task']=task['task_id']
                if task['status']=='succeeded':assignment['cycle']+=1;assignment['failures']=0
                else:
                    assignment['failures']+=1
                    if assignment['failures']>=3:
                        assignment['suspended']=True;assignment['suspended_reason']='three_failed_cycles'
                        e.event('population_actor_suspended',actor_id=aid,reason='three consecutive failed cycles');continue
                assignment['next_start']=e.sim_time+self.rng.uniform(1,4)
            if e.sim_time<assignment['next_start']:continue
            steps=self.program(assignment)
            try:
                result=e.cmd_run_activity({'request_id':f'population-{aid}-{assignment["cycle"]}-{assignment["failures"]}',
                    'actor_id':aid,'steps':steps},source='scheduler')
                e.event('population_activity',actor_id=aid,role=assignment['role'],task_id=result['task_id'])
            except SimPeopleError as err:
                assignment['suspended']=True;e.event('population_actor_suspended',actor_id=aid,error=err.as_dict())

class Queues:
    def __init__(self):self.members={}
    def join(self,queue,actor,capacity):
        members=self.members.setdefault(queue,[])
        if actor in members:return members.index(actor)
        if len(members)>=capacity:raise SimPeopleError('RESOURCE_BUSY','queue is full',queue=queue)
        members.append(actor);return len(members)-1
    def index(self,queue,actor):return self.members[queue].index(actor)
    def remove(self,actor):
        for members in self.members.values():
            if actor in members:members.remove(actor)
