"""Cinematic performance timing. Pure maths, not a runtime pursuit capability.

An attack has a captured target and a recovery. Calling score out of order must
not change the pose, target or root. Root travel has exactly one owner.
"""
from dataclasses import dataclass
import math
import numpy as np


def smooth(x):
    x=float(np.clip(x,0,1));return x*x*(3-2*x)


def window(t,start,end,fade=.15):
    return smooth((t-start)/fade)*(1-smooth((t-end)/fade))


@dataclass(frozen=True)
class Knot:
    t: float
    p: tuple
    v: tuple


class Trajectory:
    def __init__(self,knots):
        self.knots=[Knot(float(t),tuple(map(float,p)),tuple(map(float,v))) for t,p,v in knots]
        if any(b.t<=a.t for a,b in zip(self.knots,self.knots[1:])):
            raise ValueError('trajectory times must increase')

    def sample(self,t):
        if t<=self.knots[0].t:return np.array(self.knots[0].p),np.array(self.knots[0].v)
        if t>=self.knots[-1].t:return np.array(self.knots[-1].p),np.array(self.knots[-1].v)
        k=next(i for i,b in enumerate(self.knots[1:]) if t<b.t)
        a,b=self.knots[k:k+2];dt=b.t-a.t;u=(t-a.t)/dt;p0,p1,v0,v1=map(np.asarray,[a.p,b.p,a.v,b.v])
        p=(2*u**3-3*u*u+1)*p0+(u**3-2*u*u+u)*dt*v0+(-2*u**3+3*u*u)*p1+(u**3-u*u)*dt*v1
        v=(6*u*u-6*u)/dt*p0+(3*u*u-4*u+1)*v0+(-6*u*u+6*u)/dt*p1+(3*u*u-2*u)*v1
        return p,v


class DoorScore:
    """Ten seconds of authored film; no agent may read this as live perception."""
    duration=10.
    commit_t=4.65
    launch_t=5.10
    def __init__(self):
        self.paths={
            'H01':Trajectory([(0,(8.2,1.82),(2.8,0)),(4.45,(20.66,1.82),(2.8,0)),
                (4.90,(21.55,1.87),(1.0,.35)),(5.25,(21.72,2.12),(.35,1.05)),
                (6.20,(22.32,3.75),(1.1,2.2)),(7.5,(24.0,6.0),(.25,1.8)),
                (8.3,(24.0,7.55),(.4,1.8)),(9.,(25.3,8.15),(1.9,.8)),
                (10.,(27.6,9.0),(1.6,.8))]),
            'F02':Trajectory([(0,(4.9,-1.35),(4.5,0)),(3.4,(20.2,-1.35),(4.5,0)),
                (4.35,(22.33,-1.35),(0,0)),(5.10,(22.33,-1.35),(0,0)),
                (6.15,(23.25,1.65),(.8,3.0)),(6.55,(23.50,2.60),(.45,1.75)),
                (7.05,(23.66,3.20),(.20,.75)),(7.50,(23.70,3.36),(0,0)),
                (10.,(23.70,3.36),(0,0))]),
            'F01':Trajectory([(0,(6.0,5.8),(3.0,0)),(3.1,(15.3,5.8),(3.0,0)),(3.7,(17.1,6.5),(1.3,1.2)),
                (4.35,(17.3,7.8),(0,0)),(5.6,(17.4,8.0),(0,0)),
                (6.25,(18.7,7.95),(1.4,0)),(6.7,(18.95,7.70),(.3,-1.1)),(7.3,(19.1,6.5),(.5,-1.5)),
                (10.,(21.3,4.65),(.8,-.4))])}
        # Before the heroine's evasive choice. Frozen prediction, never a
        # per-frame hand attraction to the heroine's current transform.
        p,v=self.paths['H01'].sample(self.commit_t)
        self.committed_target=np.r_[p+v*.77,1.12]
        self.events=[
            {'t':4.35,'actor':'F02','state':'door_brace','trigger':'arrived at interception door'},
            {'t':4.45,'actor':'H01','state':'notice_threat','trigger':'visible red shoulder at D03'},
            {'t':4.65,'actor':'F02','state':'attack_committed','target_m':self.committed_target.tolist(),'root_owner':'film trajectory'},
            {'t':4.85,'actor':'H01','state':'brake_plant','trigger':'choose open platform rather than former route'},
            {'t':5.10,'actor':'F02','state':'lunge','trigger':'commitment; ignores later target motion'},
            {'t':5.25,'actor':'H01','state':'cut_away','trigger':'planned evasive choice'},
            {'t':6.15,'actor':'F02','state':'miss_and_first_recovery_step','target_m':self.committed_target.tolist()},
            {'t':6.55,'actor':'F02','state':'second_recovery_step'},
            {'t':7.50,'actor':'F02','state':'balance_restored'},
            {'t':8.0,'actor':'F02','state':'search_old_direction','trigger':'missed committed target; no live target feed'},
            {'t':4.35,'actor':'F01','state':'search_wrong_side','trigger':'cinematic occlusion beat; not autonomous nav acceptance'}]

    def root(self,aid,t):
        p,v=self.paths[aid].sample(t);speed=float(np.linalg.norm(v));yaw=math.atan2(v[1],v[0]) if speed>1e-5 else 0.
        if aid=='F02':
            initial=math.atan2(6*3./1.05**2-2*3./1.05,6*.92/1.05**2-2*.8/1.05)
            if 4.35<=t<=5.10:yaw=initial*smooth((t-4.35)/.75)
            if t>=7.5:yaw=math.atan2(.75,.20)-.7*smooth((t-8)/1.3)
        if aid=='F01' and 4.35<=t<6.25:yaw=.9*smooth((t-4.35)/.6)-1.2*smooth((t-5.7)/.55)
        return p,yaw,speed

    def state(self,aid,t):
        if aid=='H01':return 'escape_run' if t<4.45 else 'notice_and_brake' if t<5.25 else 'evasive_cut' if t<6.2 else 'resume_escape'
        if aid=='F02':return 'pursuit_burst' if t<3.4 else 'door_brace' if t<5.1 else 'committed_lunge' if t<6.15 else 'recovery_steps' if t<7.5 else 'search_old_direction'
        return 'approach_column' if t<4.35 else 'search_wrong_side' if t<6.25 else 'reacquire_from_other_side'

    def attack_target(self,t):
        return self.committed_target.copy() if t>=self.commit_t else None


class SameDirectionScore(DoorScore):
    """Negative control: shared destination, no avoidance or committed attack."""
    def __init__(self):
        super().__init__();self.paths={'H01':Trajectory([(0,(8.2,1.82),(2.45,0)),(10.,(32.7,1.82),(2.45,0))]),'F02':Trajectory([(0,(4.9,3.0),(2.45,0)),(10.,(29.4,3.0),(2.45,0))])};self.events=[]
    def root(self,aid,t):
        p,v=self.paths[aid].sample(t);return p,0.,float(np.linalg.norm(v))
    def state(self,aid,t):return 'shared_destination'
    def attack_target(self,t):return None
