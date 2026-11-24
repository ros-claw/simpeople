"""Offline out-and-back assets from actual native Idle into measured IK goals."""
import argparse, copy, hashlib, json, math, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser()
p.add_argument('--native-run', required=True)
p.add_argument('--targets-run', required=True)
p.add_argument('--upstream', required=True)
p.add_argument('--output', required=True)
p.add_argument('--device', default='cuda:3')
p.add_argument('--goals-run')
args = p.parse_args()
out = Path(args.output).resolve();out.mkdir(parents=True, exist_ok=False)
snap = out / 'source_snapshot';snap.mkdir()
for name in ['src', 'workers', 'schemas']:
    shutil.copytree(ROOT / name, snap / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
native = ROOT / 'runs' / args.native_run
targets = ROOT / 'runs' / args.targets_run
(snap / 'native').mkdir();(snap / 'targets').mkdir()
for actor in ['operator', 'second']:
    for suffix in ['model_context', 'actual_context']:
        shutil.copy2(native / (actor + '_' + suffix + '.json'), snap / 'native')
shutil.copy2(native / 'source_manifest.json', snap / 'native/source_manifest.json')
shutil.copy2(native / 'source_snapshot/inputs/model_rig.json', out / 'rig.json')
shutil.copy2(native / 'source_snapshot/inputs/soma_native.usda', out / 'soma_native.usda')
shutil.copy2(targets / 'source_snapshot/executed_samples.json', snap / 'targets/executed_samples.json')
if args.goals_run:
    shutil.copy2(ROOT / 'runs' / args.goals_run / 'standing_goals.json', snap / 'targets/authored_goals.json')
for actor in ['operator', 'second']:
    for phase in ['left_low', 'look_left']:
        shutil.copy2(targets / (actor + '__' + phase + '_roundtrip.npz'), snap / 'targets')
(out / 'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)): hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()}, indent=2) + '\n')
sys.path.insert(0, str(snap / 'src'));sys.path.insert(0, str(snap / 'workers/motionbricks'))
import numpy as np
from worker import ArtifactBackend
from simpeople.motion.contracts import validate_spec, digest
from simpeople.motion.validation import validate_artifact
from simpeople.motion.rig import convert_root, forward_kinematics

rig = json.loads((out / 'rig.json').read_text())
histories = json.loads((snap / 'targets/executed_samples.json').read_text())
authored_goals = json.loads((snap / 'targets/authored_goals.json').read_text()) if args.goals_run else None
if authored_goals:assert authored_goals['passed']
args.rig = str(out / 'rig.json');args.cache_dir = str(Path(args.upstream).resolve() / '.trt-cache');args.fault_before_publish_s = 0
backend = ArtifactBackend(args);cases = []

def heading(row):
    f = row['actual_observation']['facing_direction'];return math.atan2(f[0], -f[1])

try:
    for actor in ['operator', 'second']:
        observed = json.loads((snap / 'native' / (actor + '_model_context.json')).read_text())
        native_rows = json.loads((snap / 'native' / (actor + '_actual_context.json')).read_text())
        origin = np.array(native_rows[-1]['world_pose'][0][:3])
        context = np.array(observed['context']['local_poses'])
        idle = context[-1:].copy()
        for goal in ['idle_cycle', 'left_low', 'look_left']:
            key = actor + '__' + goal;directory = out / key;directory.mkdir()
            target = idle.copy()
            goal_source = native_rows[-1]
            if authored_goals:
                authored = next(c for c in authored_goals['cases'] if c['case_id'] == key)
                assert authored['source_context_sha256'] == digest(observed['context'])
                target = np.array(authored['soma_goal']);goal_source = authored['native_goal_reference']
            elif goal != 'idle_cycle':
                goal_source = histories[actor + '__' + goal][-1]
                with np.load(snap / 'targets' / (actor + '__' + goal + '_roundtrip.npz'), allow_pickle=False) as data:
                    target = data['soma_local'][-1:].copy()
                target[:, 0, :3] -= np.array(goal_source['world_pose'][0][:3])
                angle = heading(native_rows[-1]) - heading(goal_source)
                target = convert_root(target, [0, 0, math.sin(angle / 2), math.cos(angle / 2)])
                target[:, 0, :3] += origin
            directions = []
            for label in ['outbound', 'return']:
                part = directory / label;part.mkdir()
                if label == 'outbound':
                    ctx = copy.deepcopy(observed['context']);binding = copy.deepcopy(observed['binding']);end = target
                else:
                    # Offline authored hold, not a claim that the outbound asset
                    # has executed or that its predicted poses are observations.
                    ctx = {'source': 'authored_fixture', 'sample_times_s': [i / 30 for i in range(4)], 'local_poses': np.repeat(target, 4, axis=0).tolist()}
                    binding = None;end = idle
                spec = {'schema_version': 'simpeople.motion-spec.v1', 'request_id': key + '_' + label,
                        'rig_sha256': rig['rig_sha256'], 'context': ctx, 'target': {'local_poses': end.tolist()}, 'binding': binding}
                validate_spec(spec, rig)
                (part / 'spec.json').write_text(json.dumps(spec, indent=2) + '\n')
                artifact = backend.generate(spec, part / 'generated')
                quality = validate_artifact(artifact, rig, part)
                with np.load(artifact['corrected']['path'], allow_pickle=False) as data:
                    poses = data['local_poses']
                world = forward_kinematics(poses, rig['parents'])
                source_world = forward_kinematics(np.array(ctx['local_poses'])[-1:], rig['parents'])[0]
                target_world = forward_kinematics(end, rig['parents'])[0]
                errors = [float(np.linalg.norm(world[0, :, :3] - source_world[:, :3], axis=-1).max()), float(np.linalg.norm(world[-1, :, :3] - target_world[:, :3], axis=-1).max())]
                directions.append({'direction': label, 'frames': len(poses), 'passed': max(errors) <= .005,
                                   'endpoint_errors_m': errors, 'input_source': ctx['source'], 'artifact_validation': quality})
            np.savez(directory / 'endpoints.npz', idle=idle, target=target)
            result = {'case_id': key, 'actor_id': actor, 'goal': goal, 'passed': all(d['passed'] for d in directions),
                      'directions': directions, 'native_entry_source': native_rows[-1], 'native_goal_source': goal_source,
                      'source_context_sha256': digest(observed['context'])}
            (directory / 'result.json').write_text(json.dumps(result, indent=2) + '\n');cases.append(result)
            print('CANONICAL_GENERATED', key, result['passed'], flush=True)
finally:
    backend.close()
(out / 'canonical_generation.json').write_text(json.dumps({'passed': bool(cases) and all(c['passed'] for c in cases), 'cases': cases,
    'scope': 'Offline preloaded out-and-back assets. Outbound uses four executed native Idle samples; return uses an explicitly authored target hold. No runtime queue or late execution authorization.'}, indent=2) + '\n')
raise SystemExit(0 if cases and all(c['passed'] for c in cases) else 2)
