"""Project measured initial human extents and floor corners into the recorded camera."""
import argparse,json
from pathlib import Path
from pxr import Gf,Usd,UsdGeom
p=argparse.ArgumentParser();p.add_argument('directory');args=p.parse_args();d=Path(args.directory)
stage=Usd.Stage.Open(str(d/'stage.usda'));prim=stage.GetPrimAtPath('/World/Camera')
view=UsdGeom.XformCache().GetLocalToWorldTransform(prim).GetInverse()
f=prim.GetAttribute('focalLength').Get();h=prim.GetAttribute('horizontalAperture').Get();v=prim.GetAttribute('verticalAperture').Get()
def project(point):
 q=view.Transform(Gf.Vec3d(*point));return [q[0]*2*f/(h*-q[2]),q[1]*2*f/(v*-q[2])]
actors={};first=None
for line in (d/'trajectories.jsonl').open():
 r=json.loads(line)
 if first is None:first=r['sim_time']
 if r['sim_time']!=first:break
 if r.get('ready'):
  pos=r['position_m'];points=[project(pos),project([pos[0],pos[1],pos[2]+2])]
  actors[r['actor_id']]={'projected_root_and_head_ndc':points,'inside_with_margin':all(abs(c)<.95 for q in points for c in q)}
corners=[project([x,y,z]) for x in [-22,22] for y in [-22,22] for z in [0,2]]
result={'actors':actors,'initial_actor_count':len(actors),'all_initial_actor_extents_inside':bool(actors) and all(a['inside_with_margin'] for a in actors.values()),
        'floor_44m_and_2m_headroom_inside':all(abs(c)<.95 for q in corners for c in q),'lens':{'focal_mm':f,'horizontal_aperture_mm':h,'vertical_aperture_mm':v},
        'criterion':'world root plus 2m head extent projects inside 95% of the 16:9 camera frame; also inspect actual RGB',
        'ndc_floor_corners':corners}
(d/'framing_audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ['actors','ndc_floor_corners']},indent=2))
