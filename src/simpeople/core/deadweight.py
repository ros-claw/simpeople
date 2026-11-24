"""Fictional film interlocks and exclusive passenger identities, not a physics solver."""
from dataclasses import dataclass, field
import math


@dataclass
class DeadweightDispatch:
    length_m: float = 112
    travel_s: float = 34
    threshold_kg: float = 1745.94
    passengers: dict = field(default_factory=dict)
    slots: dict = field(default_factory=dict)
    upper_closed: bool = False
    lower_closed: bool = False
    booth_closed: bool = False
    driver_release: bool = False
    departure_s: float | None = None
    events: list = field(default_factory=list)
    last_sim_s: float | None = None

    def __post_init__(self):
        if any(not math.isfinite(v) or v<=0 for v in [self.length_m,self.travel_s,self.threshold_kg]):
            raise ValueError('film dimensions, travel duration and dispatch threshold must be finite and positive')

    def observe_boarding(self, actor_id, slot_id, mass_kg, *, inside, feet_supported, stable_s, speed_mps, sim_time):
        if self.departure_s is not None:raise ValueError('boarding after departure is forbidden')
        if actor_id in self.passengers:return False
        if slot_id in self.slots:raise ValueError('passenger slot already occupied')
        if not math.isfinite(mass_kg) or mass_kg<=0:raise ValueError('invalid fictional mass')
        if not math.isfinite(sim_time):raise ValueError('invalid boarding time')
        if not (inside and feet_supported and stable_s>=.5 and 0<=speed_mps<.15):return False
        self.passengers[actor_id]={'slot_id':slot_id,'mass_kg':mass_kg,'sim_time':sim_time}
        self.slots[slot_id]=actor_id
        self.events.append({'event':'boarding_observed','actor_id':actor_id,'sim_time':sim_time})
        return True

    @property
    def load_kg(self):return sum(p['mass_kg'] for p in self.passengers.values())

    def advance(self, sim_time):
        if not math.isfinite(sim_time) or self.last_sim_s is not None and sim_time<self.last_sim_s:
            raise ValueError('simulation clock must be finite and monotonic')
        self.last_sim_s=sim_time
        ready=self.load_kg>=self.threshold_kg and self.upper_closed and self.lower_closed and self.booth_closed and self.driver_release
        if self.departure_s is None and ready:
            self.departure_s=sim_time;self.events.append({'event':'dispatch','sim_time':sim_time,'actor_ids':sorted(self.passengers),'configured_load_kg':self.load_kg})
        if self.departure_s is None:return {'upper_s_m':0.,'lower_s_m':self.length_m,'moving':False}
        u=max(0,min(1,(sim_time-self.departure_s)/self.travel_s))
        if u<1 and not (self.upper_closed and self.lower_closed and self.booth_closed):
            raise ValueError('door contact lost during travel; abort the film take')
        distance=self.length_m*(u*u*u*(10+u*(-15+6*u)))
        return {'upper_s_m':distance,'lower_s_m':self.length_m-distance,'moving':0<u<1}


def cabin_handoff(world_matrix, cabin_world_matrix):
    """Return a local transform preserving the same world pose (row-vector matrices)."""
    import numpy as np
    return np.asarray(world_matrix) @ np.linalg.inv(np.asarray(cabin_world_matrix))
