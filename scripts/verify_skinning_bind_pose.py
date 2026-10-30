"""Independent bind-pose reference check for the audit skinning math.

Does not replace native animation acceptance. Runs without Kit; uses USD assets
and a minimal read-only stand-in for the SDK transform output structure.
"""
import argparse,json,sys,types
from pathlib import Path
import numpy as np
from pxr import Usd,UsdGeom,UsdSkel,Gf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
class Vector:
 def __init__(self,*v):self.x,self.y,self.z=v[:3];self.w=v[3] if len(v)>3 else None
sys.modules['carb']=types.SimpleNamespace(Float3=Vector,Float4=Vector)
from simpeople.backends.native.body_geometry import HeadNeckGeometry
from simpeople.core.seats import SeatProfile
from simpeople.core.asset_paths import resolve_asset_path

def check(path):
 source=Usd.Stage.Open(path);s=Usd.Stage.CreateInMemory();UsdGeom.SetStageUpAxis(s,'Z');UsdGeom.SetStageMetersPerUnit(s,1)
 model=UsdGeom.Xform.Define(s,'/Model');model.GetPrim().GetReferences().AddReference(path)
 transform=Gf.Matrix4d().SetScale(UsdGeom.GetStageMetersPerUnit(source))
 if UsdGeom.GetStageUpAxis(source)=='Y':transform*=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1,0,0),90))
 model.MakeMatrixXform().Set(transform)
 skel=next(UsdSkel.Skeleton(p) for p in s.Traverse() if p.IsA(UsdSkel.Skeleton))
 handle=next(str(p.GetPath()) for p in s.Traverse() if p.IsA(UsdSkel.Root));g=HeadNeckGeometry(s,handle)
 bind=skel.GetBindTransformsAttr().Get();world=UsdGeom.XformCache().GetLocalToWorldTransform(skel.GetPrim())
 head=next(i for i,n in enumerate(g.names) if n.rsplit('/',1)[-1].lower()=='head')
 class BindPoseAgent:
  def get_joint_index(self,tag):return head
  def get_joint_world_transform(self,index,p,q):
   m=bind[index]*world;v=m.ExtractTranslation();r=m.RemoveScaleShear().ExtractRotationQuat()
   p.x,p.y,p.z=v;q.x,q.y,q.z=r.GetImaginary();q.w=r.GetReal();return True
 profile=SeatProfile('reference',(0,0,0));actual=g.evaluate(BindPoseAgent(),profile,1)
 expected=min(profile.clearance((point@np.asarray(world))[:3]) for mesh in g.meshes for point in mesh['points'])
 error=abs(expected-actual['worst']['clearance_m'])
 assert error<1e-5,(path,error)
 return {'asset':Path(path).stem,'selected_vertices':g.vertex_count,'distance_error_m':error,'passed':True}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',default='.runtime/optimization_1031/skinning-bind-validation.json');a=p.parse_args()
 paths=[str(ROOT/'assets/cache/behavior/Characters/Human/Default.usd')]+[resolve_asset_path(x['source_uri'],ROOT) for x in json.loads((ROOT/'configs/assets.json').read_text())['assets'][:11]]
 results=[check(x) for x in paths];Path(a.output).write_text(json.dumps(results,indent=2));print(json.dumps({'assets':len(results),'max_distance_error_m':max(r['distance_error_m'] for r in results)}))
