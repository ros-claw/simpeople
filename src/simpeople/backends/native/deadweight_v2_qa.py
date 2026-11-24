"""Read deformed shoe vertices from actual target rigs; no toe-only pass."""
import numpy as np
from .deadweight_v2_actor import SkinnedStride

def measure_costume_gaits(director):
    rows=[]
    for source_index in range(11):
        aid=next(a for a in director.actors if director.sources[a]==source_index);actor=director.actors[aid];stride=SkinnedStride(actor);prev=None;peak=0.;min_sole=1.;count=0
        for k in range(2*stride.period+1):
            delta=stride.displacement(k);actor.update(*director.cache.pose(k),delta);local=actor.foot_points();now={side:points+delta for side,points in local.items()};min_sole=min(min_sole,min(float(x[:,2].min()) for x in now.values()))
            if prev is not None:
                side=stride.support[(k-1)%stride.period];a,b=prev[side],now[side];mask=(a[:,2]<.025)&(b[:,2]<.03)
                if mask.sum()>=3:peak=max(peak,float(np.linalg.norm(b[mask,:2]-a[mask,:2],axis=1).max()));count+=1
            prev=now
        rows.append({'source_index':source_index,'actor_id':aid,'frames':2*stride.period+1,'measured_contact_intervals':count,'selected_deformed_shoe_patch_max_step_slip_m':peak,'min_deformed_shoe_z_m':min_sole,'stride_m':stride.travel[-1].tolist(),'passed':peak<.03 and min_sole>=-.005 and count>=stride.period})
    return {'passed':all(r['passed'] for r in rows),'rigs':rows,'scope':'contact-corrected cinematic gait; support selected from source cycle; root translation derived from shoe displacement, residual on actual deformed vertices; not independent contact forces or full locomotion validation'}
