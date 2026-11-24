"""Export safe full-context/reference-decode holds for actual Behavior comparison."""
import argparse,hashlib,json,math,shutil,sys
from pathlib import Path
import numpy as np
from pxr import Usd,UsdGeom,UsdSkel,Gf,Vt

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from simpeople.motion.rig import decode_reference_pose,convert_root,inverse,validate_poses
p=argparse.ArgumentParser();p.add_argument('--bridge-run',required=True);p.add_argument('--output',required=True);args=p.parse_args()
source=ROOT/'runs'/args.bridge_run;out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
rig=json.loads((source/'source_snapshot/rig.json').read_text());samples=json.loads((source/'source_snapshot/executed_samples.json').read_text())
shutil.copy2(source/'source_snapshot/soma_native.usda',out/'soma_native.usda');stage=Usd.Stage.Open(str(out/'soma_native.usda'));skel=UsdSkel.Skeleton(stage.GetPrimAtPath('/Soma/Skeleton'));joints=list(skel.GetJointsAttr().Get())
manifest={'schema_version':'simpeople.custom_actions.v1','scope':'Offline native readback roundtrip; no new model inference or online application.','actions':{},'roundtrip_sources':{}}
if any('__' in key for key in samples):manifest['roundtrip_cases']=sorted({row[-1]['phase'] for row in samples.values()})
for actor,rows in samples.items():
    path=source/(actor+'_roundtrip.npz')
    with np.load(path,allow_pickle=False) as data:full=data['soma_local'];model=data['model_context']
    reference=decode_reference_pose(model,rig)
    expected=rows[-1];origin=np.array(expected['world_pose'][0][:3]);f=expected['actual_observation']['facing_direction'];yaw=math.atan2(f[0],-f[1]);normalizer=np.array([0,0,math.sin(-yaw/2),math.cos(-yaw/2)])
    manifest['roundtrip_sources'][actor]=expected
    for variant,poses in [('full',full),('reference',reference)]:
        name=f'rt_{actor}_{variant}';poses=poses.copy();poses[:,0,:3]-=origin;poses=convert_root(poses,normalizer);poses=np.repeat(poses[-1:],90,axis=0)
        # A mathematical point-preserving projection can stretch fingers. This
        # probe only uses full context or the official reference-length decoder.
        ref=np.array(rig['reference_local']);lengths=np.linalg.norm(ref[1:,:3],axis=-1);observed=np.linalg.norm(poses[:,1:,:3],axis=-1);mask=lengths>1e-6
        worst=float(np.abs(observed[:,mask]/lengths[mask]-1).max());assert worst<.05,(name,worst)
        np.savez(out/(name+'_poses.npz'),local_poses=poses);poses=convert_root(poses,inverse(rig['model_to_runtime_xyzw']))
        clip=Usd.Stage.CreateNew(str(out/(name+'.usda')));UsdGeom.SetStageMetersPerUnit(clip,.01);UsdGeom.SetStageUpAxis(clip,'Y');clip.SetFramesPerSecond(30);clip.SetTimeCodesPerSecond(30);clip.SetStartTimeCode(0);clip.SetEndTimeCode(89)
        animation=UsdSkel.Animation.Define(clip,'/Root');clip.SetDefaultPrim(animation.GetPrim());animation.CreateJointsAttr(joints)
        for tick,pose in enumerate(poses):
            pose=np.concatenate([np.array([[0,0,0,0,0,0,1]]),pose]);validate_poses(pose[None],78)
            animation.CreateTranslationsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*map(float,t[:3]*100)) for t in pose]),tick)
            animation.CreateRotationsAttr().Set(Vt.QuatfArray([Gf.Quatf(float(t[6]),Gf.Vec3f(*map(float,t[3:6]))) for t in pose]),tick)
            animation.CreateScalesAttr().Set(Vt.Vec3hArray([Gf.Vec3h(1,1,1)]*78),tick)
        clip.GetRootLayer().Save()
        manifest['actions'][name]={'skeleton':str(out/'soma_native.usda'),'clip':str(out/(name+'.usda')),'clearance_radius_m':1,'actor_source':actor,'variant':variant,'source_bridge_run':args.bridge_run,'source_npz_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_rig_sha256':rig['rig_sha256'],'max_all_nonzero_bone_length_error':worst,'motion_kind':'authored_readback_pose_hold','sample_rate':30,'frame_count':90}
(out/'actions.json').write_text(json.dumps(manifest,indent=2)+'\n');print('NATIVE_ROUNDTRIP_HOLDS_EXPORTED',len(manifest['actions']))
