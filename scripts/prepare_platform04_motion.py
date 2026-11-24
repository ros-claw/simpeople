"""Named/tagged import assets for the supplied CC0 sprint and crouch clips.

Only source rigs are normalized here. The 101-joint production rig is retargeted
by the installed Behavior importer, never by copying source bone indices.
"""
import importlib.util,json,hashlib,sys
from pathlib import Path
import numpy as np
from pxr import Usd,UsdGeom,UsdSkel,Gf,Vt,Sdf
ROOT=Path(__file__).resolve().parents[1];KIT=ROOT/'.runtime/platform04/kit';OUT=ROOT/'.runtime/platform04/prepared02';OUT.mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('bank_builder',KIT/'motion/build_pose_bank.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
def normalize(src,dest,kind):
    original=Usd.Stage.Open(str(src));stage=Usd.Stage.CreateNew(str(dest));stage.GetRootLayer().TransferContent(original.Flatten());UsdGeom.SetStageMetersPerUnit(stage,.01);UsdGeom.SetStageUpAxis(stage,'Y');UsdGeom.Xformable(stage.GetDefaultPrim()).ClearXformOpOrder()
    sk=next(UsdSkel.Skeleton(p) for p in stage.Traverse() if p.IsA(UsdSkel.Skeleton))
    for attr in [sk.GetRestTransformsAttr(),sk.GetBindTransformsAttr()]:
        values=[]
        for m in attr.Get():
            n=Gf.Matrix4d(m);n.SetTranslateOnly(m.ExtractTranslation()*100);values.append(n)
        attr.Set(Vt.Matrix4dArray(values))
    for p in stage.Traverse():
        if p.IsA(UsdGeom.Mesh):
            mesh=UsdGeom.Mesh(p);mesh.GetPointsAttr().Set(Vt.Vec3fArray([v*100 for v in mesh.GetPointsAttr().Get()]));mesh.GetExtentAttr().Clear()
        if p.IsA(UsdSkel.Animation):
            attr=UsdSkel.Animation(p).GetTranslationsAttr()
            for t in [Usd.TimeCode.Default(),*attr.GetTimeSamples()]:attr.Set(Vt.Vec3fArray([v*100 for v in attr.Get(t)]),t)
    labels={'DEF_hips':'Hips','DEF_spine_001':'Spine1','DEF_spine_002':'Spine2','DEF_spine_003':'Chest','DEF_neck':'Neck1','DEF_head':'Head'}
    for s,label in [('L','Left'),('R','Right')]:
        for bone,tag in [('thigh','Leg'),('shin','Shin'),('foot','Foot'),('toe','ToeBase'),('shoulder','Shoulder'),('upper_arm','Arm'),('forearm','ForeArm'),('hand','Hand')]:labels['DEF_'+bone+'_'+s]=label+tag
    tags=[labels.get(n.rsplit('/',1)[-1],'') for n in sk.GetJointsAttr().Get()];prim=sk.GetPrim();prim.AddAppliedSchema('ControlRigAPI');prim.CreateAttribute('controlRig:retargetTags',Sdf.ValueTypeNames.TokenArray).Set(Vt.TokenArray(tags));prim.CreateAttribute('controlRig:retargetTransforms',Sdf.ValueTypeNames.Matrix4dArray).Set(sk.GetRestTransformsAttr().Get());prim.CreateAttribute('controlRig:upAxis',Sdf.ValueTypeNames.Token).Set('Y');prim.CreateAttribute('controlRig:forwardAxis',Sdf.ValueTypeNames.Token).Set('Z');stage.GetRootLayer().Save();return stage,sk
actions={}
for key,src in [('sprint',KIT/'motion/sprint_proxy.usdc'),('infected_sprint',KIT/'motion/infected_sprint_previs.usda')]:
    dest=OUT/(key+'_skeleton.usdc')
    if dest.exists():raise FileExistsError(dest)
    stage,sk=normalize(src,dest,'ual1');anim=next(p for p in stage.Traverse() if p.IsA(UsdSkel.Animation));clip=Usd.Stage.CreateNew(str(OUT/(key+'_clip.usdc')));Sdf.CopySpec(stage.GetRootLayer(),anim.GetPath(),clip.GetRootLayer(),'/Root');clip.SetDefaultPrim(clip.GetPrimAtPath('/Root'));clip.SetTimeCodesPerSecond(30);clip.SetStartTimeCode(0);clip.SetEndTimeCode(20);UsdGeom.SetStageMetersPerUnit(clip,.01);UsdGeom.SetStageUpAxis(clip,'Y');clip.GetRootLayer().Save();actions[key]={'skeleton':str(dest),'clip':str(OUT/(key+'_clip.usdc')),'clearance_radius_m':1.,'in_place':True}
# The exact same named 53-joint source rest rig; export Crouch from pinned GLB.
g,read,member,sha=builder.load(ROOT/'.runtime/platform04/UAL1_Standard.zip',0);nodes=g['nodes'];J=g['skins'][0]['joints'];rank={n:i for i,n in enumerate(J)};source_stage=Usd.Stage.Open(str(OUT/'sprint_skeleton.usdc'));sk=UsdSkel.Skeleton.Get(source_stage,'/SprintProxy/Skeleton');names=list(sk.GetJointsAttr().Get());rawnames=[nodes[j]['name'].replace('-','_').replace('.','_') for j in J];assert [n.rsplit('/',1)[-1] for n in names]==rawnames
take=next(a for a in g['animations'] if a['name']=='Crouch_Fwd_Loop');times=read(take['samplers'][0]['input']).ravel();F=len(times);values={k:np.repeat(np.array([[nodes[j].get(k,d) for j in J]],float),F,axis=0) for k,d in [('translation',[0,0,0]),('rotation',[0,0,0,1]),('scale',[1,1,1])]}
for ch in take['channels']:values[ch['target']['path']][:,rank[ch['target']['node']]]=read(take['samplers'][ch['sampler']]['output'])
stage=Usd.Stage.CreateNew(str(OUT/'crouch_clip.usdc'));a=UsdSkel.Animation.Define(stage,'/Root');a.CreateJointsAttr(names);stage.SetDefaultPrim(a.GetPrim());stage.SetTimeCodesPerSecond(30);stage.SetStartTimeCode(0);stage.SetEndTimeCode(round(times[-1]*30));UsdGeom.SetStageMetersPerUnit(stage,.01);UsdGeom.SetStageUpAxis(stage,'Y')
for i,tm in enumerate(times):
    a.CreateTranslationsAttr().Set(Vt.Vec3fArray.FromNumpy((values['translation'][i]*100).astype(np.float32)),float(tm*30));a.CreateRotationsAttr().Set(Vt.QuatfArray([Gf.Quatf(float(q[3]),Gf.Vec3f(*map(float,q[:3]))) for q in values['rotation'][i]]),float(tm*30));a.CreateScalesAttr().Set(Vt.Vec3hArray([Gf.Vec3h(1)]*len(names)),float(tm*30))
stage.GetRootLayer().Save();actions['crouch']={'skeleton':str(OUT/'sprint_skeleton.usdc'),'clip':str(OUT/'crouch_clip.usdc'),'clearance_radius_m':1.,'in_place':True}
(OUT/'custom_actions.json').write_text(json.dumps({'actions':actions},indent=2));(OUT/'provenance.json').write_text(json.dumps({'source_joint_count':53,'retarget_labels':22,'source_archive_sha256':hashlib.sha256((ROOT/'.runtime/platform04/UAL1_Standard.zip').read_bytes()).hexdigest(),'rig_matching':'named source joints checked; production target is SDK-retargeted','source_assets':[str(p) for p in [KIT/'motion/sprint_proxy.usdc',KIT/'motion/infected_sprint_previs.usda']]},indent=2));print(OUT)
