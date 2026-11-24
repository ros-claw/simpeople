"""Versioned seat geometry and read-only contact checks in public metre frame."""
from dataclasses import dataclass,asdict
import hashlib
import json
import math

@dataclass(frozen=True)
class SeatProfile:
    profile_id:str
    position_m:tuple
    yaw_rad:float=0.0
    seat_top_m:float=.48
    seat_depth_m:float=.6
    hips_offset_m:tuple=(0,0,.56)
    back_center_local_m:tuple=(0,.25,.78)
    back_half_extent_m:tuple=(.3,.05,.325)
    back_tilt_rad:float=0.0
    revision:str='seat-v1'
    def signature(self,asset_hash,motion_hash):
        return hashlib.sha256(json.dumps([asdict(self),asset_hash,motion_hash],sort_keys=True).encode()).hexdigest()
    def clearance(self,world,radius=0.0):
        """Signed distance to oriented back box; negative means penetration."""
        dx=world[0]-self.position_m[0];dy=world[1]-self.position_m[1];c=math.cos(self.yaw_rad);s=math.sin(self.yaw_rad)
        p=[c*dx+s*dy,-s*dx+c*dy,world[2]-self.position_m[2]]
        p=[p[i]-self.back_center_local_m[i] for i in range(3)]
        c=math.cos(self.back_tilt_rad);s=math.sin(self.back_tilt_rad);y,z=p[1],p[2]
        p[1]=c*y-s*z;p[2]=s*y+c*z
        q=[abs(p[i])-self.back_half_extent_m[i] for i in range(3)]
        return math.sqrt(sum(max(v,0)**2 for v in q))+min(max(q),0)-radius
    def proxy_clearances(self,joints):
        tests={}
        for tag,radius in [('Head',.085),('Neck',.045),('Neck1',.045),('Neck2',.045)]:
            if tag in joints:tests[tag]=self.clearance(joints[tag],radius)
        # Sample the chest-to-neck capsule; back contact is permitted but tracked.
        chest=joints.get('Chest',joints.get('Spine2'));neck=joints.get('Neck1',joints.get('Head'))
        if chest and neck:tests['chest_back_capsule']=min(self.clearance([chest[k]+(neck[k]-chest[k])*i/8 for k in range(3)],.09) for i in range(9))
        return tests
    def as_dict(self):return asdict(self)
