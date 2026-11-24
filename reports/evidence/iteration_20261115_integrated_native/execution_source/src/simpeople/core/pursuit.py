"""Observation-only chase memory. No access to the runner's route or future."""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class ChaseIntent:
    state:str
    target_id:str|None
    target_m:tuple|None
    observation_m:tuple|None
    observation_age_s:float|None

class PursuitMemory:
    def __init__(self,*,memory_s=.70,lead_s=.25,max_estimated_speed=4.5):
        self.memory_s=memory_s;self.lead_s=lead_s;self.max_speed=max_estimated_speed;self.last=None;self.last_t=None;self.target_id=None;self.velocity=(0.,0.,0.);self.clock=None
    def update(self,t,target_id,visible_position):
        if not math.isfinite(t) or self.clock is not None and t<=self.clock:raise ValueError('perception clock must increase')
        self.clock=t
        if visible_position is not None:
            p=tuple(float(x) for x in visible_position)
            if len(p)!=3 or not all(math.isfinite(x) for x in p):raise ValueError('invalid observed position')
            if self.last is not None and self.target_id==target_id and t-self.last_t<.6:
                estimate=tuple((a-b)/(t-self.last_t) for a,b in zip(p,self.last));speed=math.sqrt(sum(v*v for v in estimate));scale=min(1,self.max_speed/max(speed,1e-9));self.velocity=tuple(.55*v+.45*e*scale for v,e in zip(self.velocity,estimate))
            else:self.velocity=(0.,0.,0.)
            self.last=p;self.last_t=t;self.target_id=target_id;state='PURSUE';age=0.;lead=self.lead_s
        elif self.last is not None:
            age=t-self.last_t;state='LAST_SEEN' if age<=self.memory_s else 'SEARCH';lead=min(self.lead_s,age) if state=='LAST_SEEN' else 0.
        else:state='SEARCH';age=None;lead=0.
        target=None if self.last is None else tuple(p+v*lead for p,v in zip(self.last,self.velocity))
        return ChaseIntent(state,self.target_id,target,None if visible_position is None else tuple(visible_position),age)

def segment_hits_box(a,b,low,high):
    enter,leave=0.,1.
    for p,q,m,M in zip(a,b,low,high):
        d=q-p
        if abs(d)<1e-10:
            if not m<=p<=M:return False
        else:
            t,u=(m-p)/d,(M-p)/d
            if t>u:t,u=u,t
            enter=max(enter,t);leave=min(leave,u)
            if enter>leave:return False
    return True

def visible(observer,facing,target,occluders,*,range_m=15.,fov_deg=160.):
    v=tuple(b-a for a,b in zip(observer,target));distance=math.hypot(v[0],v[1]);norm=math.hypot(facing[0],facing[1]);dot=(v[0]*facing[0]+v[1]*facing[1])/max(1e-9,norm*distance)
    if distance>range_m or dot<math.cos(math.radians(fov_deg/2)):return False
    eye=(observer[0],observer[1],observer[2]+1.45);head=(target[0],target[1],target[2]+1.45)
    return not any(segment_hits_box(eye,head,low,high) for low,high in occluders)
