"""Export generated SOMA poses in the original rig's Y-up centimetre frame."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
import numpy as np
from pxr import Usd,UsdGeom,UsdSkel,Gf,Vt
from simpeople.motion.rig import validate_rig,validate_poses,convert_root,inverse

p=argparse.ArgumentParser();p.add_argument('--model-dir',required=True);p.add_argument('--output',required=True);p.add_argument('--canonical-fingers',action='store_true',help='Explicit reference-finger canonical entry; preserves original raw files');p.add_argument('--static-stance',action='store_true',help='Author a native endpoint pose hold for mb_stand, not a model transition');args=p.parse_args()
if args.static_stance and not args.canonical_fingers:p.error('static canonical stance requires explicit reference fingers')
source=Path(args.model_dir).resolve();out=Path(args.output).resolve();out.mkdir(exist_ok=False,parents=True)
rig=json.loads((source/'rig.json').read_text());validate_rig(rig)
source_stage=Usd.Stage.Open(rig['source_usd']);skeleton=UsdSkel.Skeleton(source_stage.GetPrimAtPath(rig['skeleton_prim_path']));joints=list(skeleton.GetJointsAttr().Get())
assert [n.rsplit('/',1)[-1] for n in joints]==rig['joint_names']
# Native Human retargeting requires a non-anatomical root above tagged Hips.
# This derivative changes hierarchy only; original USD and model rig stay intact.
native_joints=['Root']+['Root/'+str(j) for j in joints]
rig_stage=Usd.Stage.CreateNew(str(out/'soma_native.usda'));UsdGeom.SetStageMetersPerUnit(rig_stage,rig['source_meters_per_unit']);UsdGeom.SetStageUpAxis(rig_stage,UsdGeom.Tokens.y)
rig_root=UsdSkel.Root.Define(rig_stage,'/Soma');rig_stage.SetDefaultPrim(rig_root.GetPrim());native_skeleton=UsdSkel.Skeleton.Define(rig_stage,'/Soma/Skeleton')
native_skeleton.CreateJointsAttr(native_joints)
native_skeleton.CreateRestTransformsAttr(Vt.Matrix4dArray([Gf.Matrix4d(1)]+list(skeleton.GetRestTransformsAttr().Get())))
native_skeleton.CreateBindTransformsAttr(Vt.Matrix4dArray([Gf.Matrix4d(1)]+list(skeleton.GetBindTransformsAttr().Get())))
rig_stage.GetRootLayer().Save()
manifest={'schema_version':'simpeople.custom_actions.v1','license_note':'Local internal qualification; source model and evaluation clips are not redistributed.','actions':{}}
for name,case in [('mb_stand','case_12'),('mb_arm','case_14')]:
    npz=source/(case+'.npz')
    with np.load(npz,allow_pickle=False) as archive:poses=validate_poses(archive['local_poses'],len(joints))
    if args.canonical_fingers:
        poses=poses.copy();reference=np.array(rig['reference_local'])
        for index,joint in enumerate(rig['joint_names']):
            if joint.startswith(('LeftHand','RightHand')) and joint not in {'LeftHand','RightHand'}:poses[:,index]=reference[index]
    if args.static_stance and name=='mb_stand':poses=np.repeat(poses[-1:],90,axis=0)
    np.savez(out/(name+'_derived.npz'),local_poses=poses)
    poses=convert_root(poses,inverse(rig['model_to_runtime_xyzw']))
    stage=Usd.Stage.CreateNew(str(out/(name+'.usda')));UsdGeom.SetStageMetersPerUnit(stage,rig['source_meters_per_unit']);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.y)
    stage.SetFramesPerSecond(30);stage.SetTimeCodesPerSecond(30);stage.SetStartTimeCode(0);stage.SetEndTimeCode(len(poses)-1)
    anim=UsdSkel.Animation.Define(stage,'/Root');stage.SetDefaultPrim(anim.GetPrim());anim.CreateJointsAttr(native_joints)
    for t,pose in enumerate(poses):
        pose=np.concatenate([np.array([[0,0,0,0,0,0,1]]),pose],axis=0)
        anim.CreateTranslationsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*map(float,p[:3]/rig['source_meters_per_unit'])) for p in pose]),t)
        anim.CreateRotationsAttr().Set(Vt.QuatfArray([Gf.Quatf(float(p[6]),Gf.Vec3f(*map(float,p[3:6]))) for p in pose]),t)
        anim.CreateScalesAttr().Set(Vt.Vec3hArray([Gf.Vec3h(1,1,1)]*len(native_joints)),t)
    stage.GetRootLayer().Save();clip=out/(name+'.usda')
    manifest['actions'][name]={'skeleton':str(out/'soma_native.usda'),'clip':str(clip),'clearance_radius_m':1.0,'label':name,
        'motion_artifact_sha256':hashlib.sha256(npz.read_bytes()).hexdigest(),'source_rig_sha256':rig['rig_sha256'],'source_case':case,
        'clip_sha256':hashlib.sha256(clip.read_bytes()).hexdigest(),'frame_count':len(poses),'sample_rate':30}
    manifest['actions'][name].update(extra_dof_policy='reference_fingers_canonical_entry' if args.canonical_fingers else 'official_decoded_full_rig',
        derived_poses_sha256=hashlib.sha256((out/(name+'_derived.npz')).read_bytes()).hexdigest(),
        motion_kind='authored_endpoint_hold' if args.static_stance and name=='mb_stand' else 'generated_transition')
(out/'actions.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('NATIVE_SOMA_CLIPS_EXPORTED',list(manifest['actions']))
