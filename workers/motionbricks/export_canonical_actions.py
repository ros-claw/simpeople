"""Compose offline generated out-and-back assets into one native clip each."""
import argparse, hashlib, json, math, shutil, sys
from pathlib import Path
import numpy as np
from pxr import Usd, UsdGeom, UsdSkel, Gf, Vt

ROOT = Path(__file__).resolve().parents[2];sys.path.insert(0, str(ROOT / 'src'))
from simpeople.motion.rig import convert_root, inverse, validate_poses
p = argparse.ArgumentParser();p.add_argument('--generation-run', required=True);p.add_argument('--output', required=True);p.add_argument('--end-hold-frames',type=int,default=15);p.add_argument('--playback-mode',choices=['out_and_back','transition_then_hold','loop'],default='out_and_back');p.add_argument('--adaptive-retime',action='store_true',help='Offline full-rig local SLERP subdivision; original model poses retained, longer authored action');args = p.parse_args()
assert 1<=args.end_hold_frames<=30
source = ROOT / 'runs' / args.generation_run
out = Path(args.output).resolve();out.mkdir(parents=True, exist_ok=False)
result = json.loads((source / 'canonical_generation.json').read_text());assert result['passed']
rig = json.loads((source / 'rig.json').read_text())
shutil.copy2(source / 'soma_native.usda', out / 'soma_native.usda')
stage = Usd.Stage.Open(str(out / 'soma_native.usda'));joints = list(UsdSkel.Skeleton(stage.GetPrimAtPath('/Soma/Skeleton')).GetJointsAttr().Get())
registry = {'schema_version': 'simpeople.custom_actions.v1', 'scope': 'Offline composed preload assets; not a native queue, hot reload, or live generation.',
            'actions': {}, 'canonical_bases':{}, 'canonical_cases': sorted({c['goal'] for c in result['cases']}), 'canonical_sequences': {}, 'canonical_sources': {}}
for case in result['cases']:
    key = case['case_id'];directory = source / key
    with np.load(directory / 'endpoints.npz', allow_pickle=False) as data:
        idle, target = data['idle'], data['target']
    parts = []
    artifacts = {}
    for label in ['outbound', 'return']:
        path = directory / label / 'generated/artifact.json';artifact = json.loads(path.read_text())
        artifacts[label] = hashlib.sha256(path.read_bytes()).hexdigest()
        with np.load(artifact['corrected']['path'], allow_pickle=False) as data:
            parts.append(data['local_poses'])
    retiming = None
    if args.adaptive_retime:
        from simpeople.motion.retime import adaptive_retime
        retiming = {}
        for i, label in enumerate(['outbound', 'return']):
            parts[i], retiming[label] = adaptive_retime(parts[i], rig['parents'])
        (out / ('canonical_' + key + '_retiming.json')).write_text(json.dumps(retiming, indent=2) + '\n')
    prefix = 180 if retiming else 75;goal_hold = 90 if retiming else 75;tail = 180 if retiming else 75
    poses = np.concatenate([np.repeat(idle, prefix, axis=0), parts[0][1:], np.repeat(target, goal_hold, axis=0), parts[1][1:], np.repeat(idle, tail, axis=0)])
    validate_poses(poses, 77)
    forward_start = prefix - 1;forward_end = forward_start + len(parts[0]) - 1;return_start = forward_end + goal_hold;return_end = return_start + len(parts[1]) - 1
    row = case['native_entry_source'];origin = np.array(row['world_pose'][0][:3]);f = row['actual_observation']['facing_direction'];yaw = math.atan2(f[0], -f[1])
    poses[:, 0, :3] -= origin;poses = convert_root(poses, [0, 0, math.sin(-yaw / 2), math.cos(-yaw / 2)])
    name = 'canonical_' + key;np.savez(out / (name + '_poses.npz'), local_poses=poses)
    native = convert_root(poses, inverse(rig['model_to_runtime_xyzw']))
    path = out / (name + '.usda');clip = Usd.Stage.CreateNew(str(path));UsdGeom.SetStageMetersPerUnit(clip, .01);UsdGeom.SetStageUpAxis(clip, 'Y');clip.SetFramesPerSecond(30);clip.SetTimeCodesPerSecond(30);clip.SetStartTimeCode(0);clip.SetEndTimeCode(len(poses) - 1)
    animation = UsdSkel.Animation.Define(clip, '/Root');clip.SetDefaultPrim(animation.GetPrim());animation.CreateJointsAttr(joints)
    for tick, pose in enumerate(native):
        pose = np.concatenate([np.array([[0, 0, 0, 0, 0, 0, 1]]), pose]);validate_poses(pose[None], 78)
        animation.CreateTranslationsAttr().Set(Vt.Vec3fArray([Gf.Vec3f(*map(float, v[:3] * 100)) for v in pose]), tick)
        animation.CreateRotationsAttr().Set(Vt.QuatfArray([Gf.Quatf(float(v[6]), Gf.Vec3f(*map(float, v[3:6]))) for v in pose]), tick)
        animation.CreateScalesAttr().Set(Vt.Vec3hArray([Gf.Vec3h(1, 1, 1)] * 78), tick)
    clip.GetRootLayer().Save()
    registry['actions'][name] = {'skeleton': str(out / 'soma_native.usda'), 'clip': str(path), 'clearance_radius_m': 1,
        'playback_mode': args.playback_mode, 'endpoint_hold_frames':args.end_hold_frames, 'motion_kind': 'offline_composed_official_generated_out_and_back',
        'source_model_artifact_sha256': artifacts, 'source_rig_sha256': rig['rig_sha256'], 'duration_semantics': {'out_and_back':'native_goal_loop_duration','transition_then_hold':'hold_after_complete_authored_start','loop':'one_complete_native_loop'}[args.playback_mode], 'frame_count': len(poses), 'sample_rate': 30}
    if args.playback_mode=='loop':registry['actions'][name]['native_loop_duration_s']=(len(poses)-1)/30
    registry['actions'][name]['canonical_entry']={'source_asset_sha256':row['source_asset_sha256'],'joint_paths':row['joint_paths'],'world_pose':row['world_pose'],'facing_direction':row['actual_observation']['facing_direction'],'scope':'Flat calibrated canonical Idle; compare actual SDK pose immediately before native start.'}
    registry['actions'][name]['entry_base_action']='canonical_base_'+case['actor_id']
    if retiming:
        registry['actions'][name]['offline_retiming']={'proof_file':name+'_retiming.json','proof_sha256':hashlib.sha256((out/(name+'_retiming.json')).read_bytes()).hexdigest(),
            'purpose':'Bound full-FK source step changes before native playback; keep every original model pose. Longer prefix/tail provide explicit Idle margins. No rendered-video interpolation or native quality claim.'}
    if args.playback_mode=='out_and_back':registry['actions'][name]['native_phase_ranges']={'ActionStart':[0,forward_end],'ActionLoop':[forward_end,return_start],'ActionEnd':[return_start,len(poses)-1]}
    registry['canonical_sequences'][key] = {'frame_count': len(poses), 'prefix_frames': prefix, 'outbound': [forward_start, forward_end], 'target_hold': [forward_end + 1, return_start], 'return': [return_start, return_end], 'tail': [return_end + 1, len(poses) - 1]}
    registry['canonical_sources'][key] = {'entry': case['native_entry_source'], 'goal': case['native_goal_source']}
    if case['actor_id'] not in registry['canonical_bases']:
        base_name='canonical_base_'+case['actor_id'];base_path=out/(base_name+'.usda');base=Usd.Stage.CreateNew(str(base_path));UsdGeom.SetStageMetersPerUnit(base,.01);UsdGeom.SetStageUpAxis(base,'Y');base.SetFramesPerSecond(30);base.SetTimeCodesPerSecond(30);base.SetStartTimeCode(0);base.SetEndTimeCode(89);held=UsdSkel.Animation.Define(base,'/Root');base.SetDefaultPrim(held.GetPrim());held.CreateJointsAttr(joints)
        for source_attr,destination in [(animation.GetTranslationsAttr(),held.CreateTranslationsAttr()),(animation.GetRotationsAttr(),held.CreateRotationsAttr()),(animation.GetScalesAttr(),held.CreateScalesAttr())]:
            value=source_attr.Get(0)
            for t in range(90):destination.Set(value,t)
        base.GetRootLayer().Save();registry['canonical_bases'][case['actor_id']]=base_name;registry['actions'][base_name]={'skeleton':str(out/'soma_native.usda'),'clip':str(base_path),'clearance_radius_m':1,'playback_mode':'loop','motion_kind':'authored_canonical_entry_hold','source_asset_sha256':row['source_asset_sha256']}
(out / 'actions.json').write_text(json.dumps(registry, indent=2) + '\n')
(out / 'export_manifest.json').write_text(json.dumps({'generation_run':args.generation_run,'options':vars(args),'exporter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'retime_module_sha256':hashlib.sha256((ROOT/'src/simpeople/motion/retime.py').read_bytes()).hexdigest() if args.adaptive_retime else None,
    'scope':'Offline authored cache; model artifacts unchanged. Native playback and quality must be separately verified.'},indent=2)+'\n');print('CANONICAL_ACTIONS_EXPORTED', len(registry['actions']))
