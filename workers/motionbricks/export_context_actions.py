"""Preload assets: observed entry hold, genuine generated transition, target hold."""
import argparse,hashlib,json,math,shutil,sys
from pathlib import Path
import numpy as np
from pxr import Usd,UsdGeom,UsdSkel,Gf,Vt
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from simpeople.motion.rig import convert_root,inverse,validate_poses
p=argparse.ArgumentParser();p.add_argument('--generation-run',required=True);p.add_argument('--output',required=True);args=p.parse_args();source=ROOT/'runs'/args.generation_run;out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False)
rig=json.loads((source/'rig.json').read_text());contexts=json.loads((source/'source_snapshot/contexts/executed_samples.json').read_text());neutral=json.loads((source/'source_snapshot/canonical/executed_samples.json').read_text());acceptance=json.loads((source/'actual_context_generation.json').read_text());assert acceptance['passed']
shutil.copy2(source/'soma_native.usda',out/'soma_native.usda');stage=Usd.Stage.Open(str(out/'soma_native.usda'));joints=list(UsdSkel.Skeleton(stage.GetPrimAtPath('/Soma/Skeleton')).GetJointsAttr().Get())
manifest={'schema_version':'simpeople.custom_actions.v1','scope':'Offline generated asset production and preloaded playback, not online context application.','actions':{},'generated_cases':sorted({r[-1]['phase'] for r in contexts.values()}),'generated_sources':{},'generated_sequences':{}}
for row in acceptance['cases']:
    key=row['case_id'];actor=row['actor_id'];directory=source/key;spec=json.loads((directory/'spec.json').read_text());artifact=json.loads((directory/'generated/artifact.json').read_text())
    with np.load(directory/'context.npz',allow_pickle=False) as a:entry=np.repeat(a['local_poses'][-1:],90,axis=0)
    with np.load(directory/'target.npz',allow_pickle=False) as a:target=np.repeat(a['local_poses'][:1],90,axis=0)
    with np.load(artifact['corrected']['path'],allow_pickle=False) as a:motion=validate_poses(a['local_poses'],77)
    reference=contexts[key][-1];origin=np.array(reference['world_pose'][0][:3]);f=reference['actual_observation']['facing_direction'];yaw=math.atan2(f[0],-f[1]);normalizer=[0,0,math.sin(-yaw/2),math.cos(-yaw/2)]
    manifest['generated_sources'][key]={'entry':reference,'target':neutral[actor][-1]};manifest['generated_sequences'][key]={'motion_frames':len(motion),'motion_seconds':(len(motion)-1)/30,'source_worker_artifact_sha256':hashlib.sha256((directory/'generated/artifact.json').read_bytes()).hexdigest()}
    for kind,poses in [('entry',entry),('motion',motion),('target',target)]:
        name=f'gen_{key}_{kind}';poses=poses.copy();poses[:,0,:3]-=origin;poses=convert_root(poses,normalizer);np.savez(out/(name+'_poses.npz'),local_poses=poses);poses=convert_root(poses,inverse(rig['model_to_runtime_xyzw']))
        clip_path=out/(name+'.usda');clip=Usd.Stage.CreateNew(str(clip_path));UsdGeom.SetStageMetersPerUnit(clip,.01);UsdGeom.SetStageUpAxis(clip,'Y');clip.SetFramesPerSecond(30);clip.SetTimeCodesPerSecond(30);clip.SetStartTimeCode(0);clip.SetEndTimeCode(len(poses)-1);animation=UsdSkel.Animation.Define(clip,'/Root');clip.SetDefaultPrim(animation.GetPrim());animation.CreateJointsAttr(joints)
        for tick,pose in enumerate(poses):
            pose=np.concatenate([np.array([[0,0,0,0,0,0,1]]),pose]);validate_poses(pose[None],78)
            animation.CreateTranslationsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*map(float,p[:3]*100)) for p in pose]),tick);animation.CreateRotationsAttr().Set(Vt.QuatfArray([Gf.Quatf(float(p[6]),Gf.Vec3f(*map(float,p[3:6]))) for p in pose]),tick);animation.CreateScalesAttr().Set(Vt.Vec3hArray([Gf.Vec3h(1,1,1)]*78),tick)
        clip.GetRootLayer().Save();manifest['actions'][name]={'skeleton':str(out/'soma_native.usda'),'clip':str(clip_path),'clearance_radius_m':1,'source_key':key,'source_rig_sha256':rig['rig_sha256'],'source_worker_artifact_sha256':manifest['generated_sequences'][key]['source_worker_artifact_sha256'],'playback_mode':'transition_then_hold' if kind=='motion' else 'loop','motion_kind':'official_model_transition' if kind=='motion' else 'authored_observed_pose_hold','duration_semantics':'hold_after_transition' if kind=='motion' else 'native_loop_duration','frame_count':len(poses),'sample_rate':30}
(out/'actions.json').write_text(json.dumps(manifest,indent=2)+'\n');print('GENERATED_NATIVE_ASSETS_EXPORTED',len(manifest['actions']))
