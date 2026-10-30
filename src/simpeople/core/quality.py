"""Runtime geometry audit. Flags are evidence, not mesh-contact measurements."""
import math

def nearby_pairs(ready,radii):
    """Broad phase; the exact old radius/height test remains in tick()."""
    cell=max(.01,1.6*max((radii.get(o.get('asset_id'),.25) for o in ready.values()),default=.25))
    buckets={}
    for aid,obs in ready.items():
        p=obs['position_m'];key=(math.floor(p[0]/cell),math.floor(p[1]/cell))
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for other in buckets.get((key[0]+dx,key[1]+dy),()):yield other,aid
        buckets.setdefault(key,[]).append(aid)

DEFINITION={'horizontal_overlap_ratio':.8,'same_floor_delta_z_m':.8,
            'continuous_duration_s':.3,'jump_max_speed_mps':5,'jump_margin_m':.15,
            'measurement':'actual runtime roots and native radii; conservative capsule proxy, not exact mesh collision'}

class QualityAudit:
    def __init__(self,on_event=None,broad_phase=True):
        self.on_event=on_event;self.contacts={};self.flags=[];self.previous={};self.last_time=None;self.episode_id=None
        self.broad_phase=broad_phase

    def flag(self,kind,**data):
        flag={'kind':kind,**data};self.flags.append(flag)
        if self.on_event:self.on_event('quality_flag',issue=kind,**data)

    def tick(self,sim_time,observations,radii,episode_id=None):
        if episode_id!=self.episode_id:
            self.contacts.clear();self.previous.clear();self.last_time=None;self.episode_id=episode_id
        if self.last_time is not None and sim_time<=self.last_time:return
        self.last_time=sim_time;ready={a:o for a,o in observations.items() if o.get('ready')};pairs=set()
        for aid,obs in ready.items():
            previous=self.previous.get(aid)
            if previous:
                dt=sim_time-previous[0];distance=math.dist(obs['position_m'][:2],previous[1][:2])
                if distance>5*dt+.15:self.flag('root_discontinuity',actor_id=aid,sim_time=sim_time,distance_m=distance,dt_s=dt)
            self.previous[aid]=(sim_time,obs['position_m'])
        ids=list(ready)
        candidates=nearby_pairs(ready,radii) if self.broad_phase else ((a,b) for i,a in enumerate(ids) for b in ids[i+1:])
        for a,b in candidates:
            one,two=ready[a],ready[b];p,q=one['position_m'],two['position_m'];pair=tuple(sorted([a,b]))
            distance=math.dist(p[:2],q[:2]);threshold=.8*(radii.get(one.get('asset_id'),.25)+radii.get(two.get('asset_id'),.25))
            if abs(p[2]-q[2])>=.8 or distance>=threshold:continue
            pairs.add(pair)
            contact=self.contacts.setdefault(pair,{'start':sim_time,'flagged':False})
            if sim_time-contact['start']>=.3-1e-7 and not contact['flagged']:
                contact['flagged']=True
                self.flag('sustained_root_overlap',actors=list(pair),start_sim_time=contact['start'],
                          sim_time=sim_time,distance_m=distance,threshold_m=threshold,
                          positions_m=[p,q])
        for pair in list(self.contacts):
            if pair not in pairs:self.contacts.pop(pair)

    def report(self):return {'definition':DEFINITION,'flags':self.flags,'critical_count':len(self.flags)}
