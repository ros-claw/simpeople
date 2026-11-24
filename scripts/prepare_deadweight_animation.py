"""Adapt supplied combined glTF/USD into explicit, tagged SDK import assets."""
import json
from pathlib import Path
from pxr import Usd,UsdSkel,UsdGeom,Sdf,Gf,Vt
ROOT=Path(__file__).resolve().parents[1]
base=ROOT/'.runtime/deadweight/Deadweight_Feasibility_Assets'
out=ROOT/'.runtime/deadweight/prepared';out.mkdir(exist_ok=True)
source=Usd.Stage.Open(str(base/'zombie_walk_mannequin.usdc'))
stage=Usd.Stage.CreateNew(str(out/'zombie_skeleton.usdc'));stage.GetRootLayer().TransferContent(source.Flatten())
UsdGeom.SetStageMetersPerUnit(stage,.01);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.y)
UsdGeom.Xformable(stage.GetDefaultPrim()).ClearXformOpOrder()
sk=next(UsdSkel.Skeleton(p) for p in stage.Traverse() if p.IsA(UsdSkel.Skeleton))
for attr in [sk.GetRestTransformsAttr(),sk.GetBindTransformsAttr()]:
 matrices=[]
 for m in attr.Get():
  q=Gf.Matrix4d(m);q.SetTranslateOnly(m.ExtractTranslation()*100);matrices.append(q)
 attr.Set(Vt.Matrix4dArray(matrices))
for p in stage.Traverse():
 if p.IsA(UsdGeom.Mesh):
  mesh=UsdGeom.Mesh(p);mesh.GetPointsAttr().Set(Vt.Vec3fArray([v*100 for v in mesh.GetPointsAttr().Get()]));mesh.GetExtentAttr().Clear()
 if p.IsA(UsdSkel.Animation):
  attr=UsdSkel.Animation(p).GetTranslationsAttr()
  for t in [Usd.TimeCode.Default(),*attr.GetTimeSamples()]:attr.Set(Vt.Vec3fArray([v*100 for v in attr.Get(t)]),t)
names=list(sk.GetJointsAttr().Get());mapping={'pelvis':'Hips','spine_01':'Spine1','spine_02':'Spine2','spine_03':'Chest','neck_01':'Neck1','Head':'Head'}
for side,label in [('l','Left'),('r','Right')]:
 for bone,tag in [('thigh','Leg'),('calf','Shin'),('foot','Foot'),('ball','ToeBase'),('clavicle','Shoulder'),('upperarm','Arm'),('lowerarm','ForeArm'),('hand','Hand')]:mapping[bone+'_'+side]=label+tag
tags=[mapping.get(n.rsplit('/',1)[-1],'') for n in names]
prim=sk.GetPrim();prim.AddAppliedSchema('ControlRigAPI');prim.CreateAttribute('controlRig:retargetTags',Sdf.ValueTypeNames.TokenArray).Set(Vt.TokenArray(tags));prim.CreateAttribute('controlRig:retargetTransforms',Sdf.ValueTypeNames.Matrix4dArray).Set(sk.GetRestTransformsAttr().Get());prim.CreateAttribute('controlRig:upAxis',Sdf.ValueTypeNames.Token).Set('Y');prim.CreateAttribute('controlRig:forwardAxis',Sdf.ValueTypeNames.Token).Set('Z')
stage.GetRootLayer().Save()
animation=next(p for p in stage.Traverse() if p.IsA(UsdSkel.Animation))
clip=Usd.Stage.CreateNew(str(out/'zombie_clip.usdc'));Sdf.CopySpec(stage.GetRootLayer(),animation.GetPath(),clip.GetRootLayer(),'/Root');clip.SetDefaultPrim(clip.GetPrimAtPath('/Root'));clip.SetStartTimeCode(0);clip.SetEndTimeCode(40);clip.SetTimeCodesPerSecond(30);UsdGeom.SetStageMetersPerUnit(clip,.01);UsdGeom.SetStageUpAxis(clip,UsdGeom.Tokens.y);clip.GetRootLayer().Save()
config={'schema_version':'simpeople.custom_actions.v1','actions':{'zombie_walk':{'label':'丧尸拖步试拍','skeleton':str(out/'zombie_skeleton.usdc'),'clip':str(out/'zombie_clip.usdc'),'clearance_radius_m':2}}}
(ROOT/'configs/deadweight/actions.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n');print('prepared tagged skeleton and standalone animation',len(names),sum(bool(t) for t in tags))
