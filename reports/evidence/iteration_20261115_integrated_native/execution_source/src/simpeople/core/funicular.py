"""One DOF, taut-cable funicular in SI units. This is not PhysX contact.

There is no prescribed position/time curve. Constant-force integration splits
at zero velocity and the governor speed. Passive brakes never cause reversal.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class FunicularParameters:
    length_m: float = 112.
    slope_deg: float = 30.
    empty_A_kg: float = 2500.
    empty_B_kg: float = 2500.
    water_A_kg: float = 0.
    water_B_kg: float = 120.
    rotating_equivalent_kg: float = 160.
    rolling_N: float = 400.
    brake_max_N: float = 11200.
    speed_limit_mps: float = 2.
    docking_deceleration_mps2: float = .35
    g: float = 9.81


class Funicular:
    def __init__(self,params=None,*,q=0.,v=0.,auto_dock=True):
        self.p=params or FunicularParameters()
        values=list(vars(self.p).values())+[q,v]
        if not all(math.isfinite(x) for x in values):raise ValueError('non-finite model input')
        if min(self.p.length_m,self.p.empty_A_kg,self.p.empty_B_kg,self.p.speed_limit_mps,self.p.docking_deceleration_mps2)<=0:raise ValueError('non-positive model input')
        if min(self.p.water_A_kg,self.p.water_B_kg,self.p.rotating_equivalent_kg,self.p.rolling_N,self.p.brake_max_N)<0:raise ValueError('negative mass/resistance')
        if not 0<self.p.slope_deg<90 or not 0<=q<=self.p.length_m:raise ValueError('invalid track')
        self.q=float(q);self.v=float(v);self.t=0.;self.auto_dock=auto_dock
        self.locked=True;self.doors_closed=False;self.authorized=False;self.fault=False
        self.passengers={};self.events=[];self.dissipated_J=0.;self.energy0=None
        self.acceleration=0.;self.force_rolling=0.;self.force_brake=0.;self.reaction=0.;self.mode='parked'

    def add_passenger(self,actor_id,side,mass,*,inside,feet_supported,stable_s,speed_mps):
        if not self.locked or abs(self.v)>1e-9:raise ValueError('loading requires a locked stationary cabin')
        if side not in ['A','B'] or not math.isfinite(mass) or mass<=0:raise ValueError('invalid passenger')
        entry={'side':side,'mass_kg':mass}
        if actor_id in self.passengers:
            if self.passengers[actor_id]!=entry:raise ValueError('duplicate identity has conflicting side/mass')
            return False
        if not (inside and feet_supported and stable_s>=.5 and 0<=speed_mps<.15):return False
        self.passengers[actor_id]=entry;self.events.append({'event':'boarded','id':actor_id,'side':side,'solver_time_s':self.t})
        return True

    @property
    def masses(self):
        return tuple(empty+water+sum(v['mass_kg'] for v in self.passengers.values() if v['side']==side) for side,empty,water in [('A',self.p.empty_A_kg,self.p.water_A_kg),('B',self.p.empty_B_kg,self.p.water_B_kg)])

    @property
    def M(self):return sum(self.masses)+self.p.rotating_equivalent_kg

    @property
    def gravity(self):
        a,b=self.masses;return (a-b)*self.p.g*math.sin(math.radians(self.p.slope_deg))

    def energy(self):return .5*self.M*self.v*self.v-self.gravity*self.q

    def release(self):
        if not self.doors_closed or not self.authorized or self.fault:return False
        if self.q<1e-8 and self.gravity<=self.p.rolling_N:return False
        if self.q>self.p.length_m-1e-8 and self.gravity>=-self.p.rolling_N:return False
        self.locked=False;self.mode='released'
        if self.energy0 is None:self.energy0=self.energy()
        self.events.append({'event':'release','solver_time_s':self.t,'masses_kg':self.masses})
        return True

    def fault_door_contact(self):
        self.doors_closed=False;self.fault=True
        self.events.append({'event':'door_contact_fault','solver_time_s':self.t,'q_m':self.q,'v_mps':self.v})

    def step(self,h,*,brake_N=0.):
        if not math.isfinite(h) or not 0<h<=.1 or not math.isfinite(brake_N) or brake_N<0:raise ValueError('invalid substep/brake')
        if not self.doors_closed and not self.locked:self.fault=True
        self.t+=h
        if self.locked:
            if abs(self.v)>1e-9:raise ValueError('parking lock cannot zero moving velocity')
            self.acceleration=0.;self.reaction=-self.gravity;self.force_brake=self.force_rolling=0.;self.mode='parked';return self.sample()
        left=h
        while left>1e-12:
            direction=math.copysign(1,self.v if abs(self.v)>1e-10 else self.gravity or 1)
            brake=max(brake_N,self.p.brake_max_N if self.fault else 0.)
            remaining=self.p.length_m-self.q if direction>0 else self.q
            mode='braking' if brake else 'free'
            docking=False
            if self.auto_dock and abs(self.v)>1e-8 and remaining<=self.v*self.v/(2*self.p.docking_deceleration_mps2)+.5:
                if remaining<=0:raise ValueError('passed track end before stopping')
                needed=direction*self.gravity-self.p.rolling_N+self.M*self.v*self.v/(2*remaining)
                brake=max(brake,min(self.p.brake_max_N,max(0,needed)));mode='docking';docking=True
            if abs(self.v)>=self.p.speed_limit_mps-1e-9 and direction*self.gravity>self.p.rolling_N and not docking and not brake:
                brake=direction*self.gravity-self.p.rolling_N;mode='governed'
            if abs(self.v)<1e-10 and abs(self.gravity)<=self.p.rolling_N+brake:
                self.v=0.;self.acceleration=0.;self.force_rolling=-self.gravity;self.force_brake=0.;self.reaction=0.;self.mode='static'
                if self.fault:self.locked=True
                break
            self.force_rolling=-direction*self.p.rolling_N;self.force_brake=-direction*brake;self.reaction=0.
            self.acceleration=(self.gravity+self.force_rolling+self.force_brake)/self.M;self.mode=mode
            stop=-self.v/self.acceleration if self.v*self.acceleration<0 else math.inf
            cap=(direction*self.p.speed_limit_mps-self.v)/self.acceleration if self.acceleration*direction>0 and abs(self.v)<self.p.speed_limit_mps-1e-9 else math.inf
            dt=min(left,stop,cap);dq=self.v*dt+.5*self.acceleration*dt*dt
            self.q+=dq;self.v+=self.acceleration*dt;self.dissipated_J+=(self.p.rolling_N+brake)*abs(dq);left-=dt
            if not -1e-6<=self.q<=self.p.length_m+1e-6:raise ValueError('track overrun; no position clamp is permitted')
            if dt==cap:self.v=direction*self.p.speed_limit_mps
            if dt==stop:
                self.v=0.
                if self.fault or docking:
                    self.locked=True;self.mode='stopped';self.events.append({'event':'stopped','solver_time_s':self.t-left,'q_m':self.q});break
        return self.sample()

    def sample(self):
        return {'solver_time_s':self.t,'q_m':self.q,'v_mps':self.v,'a_mps2':self.acceleration,'mass_A_kg':self.masses[0],'mass_B_kg':self.masses[1],
                'gravity_N':self.gravity,'rolling_signed_N':self.force_rolling,'brake_signed_N':self.force_brake,'lock_reaction_N':self.reaction,
                'nongravity_signed_q_N':self.force_rolling+self.force_brake+self.reaction,'locked':self.locked,'mode':self.mode,
                'kinetic_plus_potential_J':self.energy(),'dissipated_J':self.dissipated_J,'energy_residual_J':0 if self.energy0 is None else self.energy()-self.energy0+self.dissipated_J}
