"""Offline audit of actual Behavior readbacks; never edits a live actor/run."""
import argparse, hashlib, json, math, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--run-id', required=True)
p.add_argument('--output', required=True)
args = p.parse_args()
run = ROOT / 'runs' / args.run_id
out = Path(args.output).resolve()
out.mkdir(parents=True, exist_ok=False)
snap = out / 'source_snapshot'
snap.mkdir()
shutil.copytree(ROOT / 'src', snap / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
shutil.copy2(__file__, snap / Path(__file__).name)
sys.path.insert(0, str(snap / 'src'))
import numpy as np
from pxr import Usd, UsdGeom, UsdSkel, Gf
from simpeople.backends.native.foot_geometry import FootGeometry
from simpeople.motion.rig import rotate, multiply


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def angles(a, b):
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    return np.degrees(2 * np.arccos(np.clip(np.abs(np.sum(a * b, axis=-1)), 0, 1)))


def body_frame(values, facing):
    pose = np.array(values)
    yaw = math.atan2(facing[0], -facing[1])
    q = np.array([0, 0, math.sin(-yaw / 2), math.cos(-yaw / 2)])
    return rotate(q, pose[:, :3] - pose[0, :3]), multiply(q, pose[:, 3:])


def intervals(mask):
    edges = np.diff(np.r_[False, mask, False].astype(int))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


registry = json.loads((run / 'source_snapshot/inputs/actions.json').read_text())
acceptance = json.loads((run / 'generated_native_acceptance.json').read_text())
assets = {a['asset_id']: a for a in json.loads((run / 'asset_manifest.json').read_text())}
events = [json.loads(line) for line in (run / 'events.jsonl').open()]
rows = {'operator': [], 'second': []}
for line in (run / 'native_pose_history.jsonl').open():
    row = json.loads(line)
    if row['actor_id'] in rows:
        rows[row['actor_id']].append(row)

results = []
asset_checks = []
for actor, asset_id in [('operator', 'default'), ('second', 'female_adult_business_02')]:
    source = Path(assets[asset_id]['source_uri'])
    original = Usd.Stage.Open(str(source))
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    UsdGeom.SetStageUpAxis(stage, 'Z')
    model = UsdGeom.Xform.Define(stage, '/World/Model')
    model.GetPrim().GetReferences().AddReference(str(source))
    transform = Gf.Matrix4d().SetScale(UsdGeom.GetStageMetersPerUnit(original))
    if UsdGeom.GetStageUpAxis(original) == 'Y':
        transform *= Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1, 0, 0), 90))
    UsdGeom.Xformable(model).MakeMatrixXform().Set(transform)
    root = next(UsdSkel.Root(x) for x in Usd.PrimRange(model.GetPrim()) if x.IsA(UsdSkel.Root))
    sk = next(UsdSkel.Skeleton(x) for x in Usd.PrimRange(root.GetPrim()) if x.IsA(UsdSkel.Skeleton))
    names = list(map(str, sk.GetJointsAttr().Get()))
    assert names == rows[actor][0]['joint_paths'], 'SDK/asset order mismatch'
    leaves = [n.rsplit('/', 1)[-1] for n in names]
    feet = {side: leaves.index(short) for side, short in [
        ('left', 'L_Ankle' if 'L_Ankle' in leaves else 'L_Foot'),
        ('right', 'R_Ankle' if 'R_Ankle' in leaves else 'R_Foot')]}
    geometry = FootGeometry(stage, str(root.GetPath()), feet)
    source_hash = sha(source)
    assert source_hash == assets[asset_id]['content_hash'], 'asset changed since capture'
    asset_checks.append({'actor_id': actor, 'asset_id': asset_id, 'sha256': source_hash, 'sole': geometry.describe()})
    for phase in sorted({r['phase'] for r in rows[actor] if r['phase'].startswith('generated_')}):
        samples = [r for r in rows[actor] if r['phase'] == phase]
        case = phase.removeprefix('generated_')
        key = actor + '__' + case
        poses = np.array([r['world_pose'] for r in samples])
        times = np.array([r['sim_time'] for r in samples])
        assert np.allclose(np.diff(times), 1 / 30, atol=1e-7), 'noncontiguous native readbacks'
        soles = [geometry.evaluate(r['world_pose']) for r in samples]
        foot_results = {}
        for side in feet:
            points = np.array([s[side] for s in soles])
            z = points[:, :, 2].min(axis=1)
            vertical = np.gradient(z, times)
            # Contact selection must not use horizontal speed (would hide slip).
            contact = (np.abs(z) <= .025) & (np.abs(vertical) <= .15)
            supports = []
            for start, end in intervals(contact):
                if times[end - 1] - times[start] < .1 - 1e-7:
                    continue
                for first in range(start, end):
                    last = min(end - 1, first + 60)
                    if times[last] - times[first] < .1 - 1e-7:
                        continue
                    drift = float(np.linalg.norm(points[first:last + 1, :, :2] - points[first, :, :2], axis=-1).max())
                    supports.append({'start_sim_time': float(times[first]), 'duration_s': float(times[last] - times[first]), 'max_selected_vertex_drift_m': drift})
            penetrations = [{'start_sim_time': float(times[a]), 'duration_s': float(times[b - 1] - times[a]), 'minimum_z_m': float(z[a:b].min())} for a, b in intervals(z < -.02) if times[b - 1] - times[a] > .1 + 1e-7]
            long_supports = [s for s in supports if s['duration_s'] >= 2 - 1e-7]
            worst = max(supports, key=lambda s: s['max_selected_vertex_drift_m'], default=None)
            foot_results[side] = {'min_sole_z_m': float(z.min()), 'penetration_failures': penetrations, 'support_windows': len(supports), 'two_second_windows': len(long_supports), 'worst_support': worst, 'passed': not penetrations and bool(long_supports) and all(s['max_selected_vertex_drift_m'] <= .03 for s in supports)}
            np.savez_compressed(out / f'{key}_{side}_sole.npz', sim_time=times, points_world_m=points, estimated_contact=contact)
        endpoints = {}
        for kind, step in [('entry', 0), ('target', 2)]:
            reference = registry['generated_sources'][key][kind]
            target_name = f'gen_{key}_{kind}'
            group = [r for r in samples if r['step_index'] == step and r['actual_observation']['action'] == target_name]
            # Stable last 0.5s of each actual hold, independent of task duration semantics.
            group = [r for r in group if group and group[-1]['sim_time'] - r['sim_time'] <= .5 + 1e-7]
            wanted, wanted_q = body_frame(reference['world_pose'], reference['actual_observation']['facing_direction'])
            errors = []
            for r in group:
                actual, actual_q = body_frame(r['world_pose'], r['actual_observation']['facing_direction'])
                errors.append((float(np.linalg.norm(wanted - actual, axis=-1).max()), float(angles(wanted_q, actual_q).max())))
            endpoints[kind] = {'samples': len(errors), 'max_position_error_m': max((e[0] for e in errors), default=None), 'max_rotation_error_deg': max((e[1] for e in errors), default=None), 'passed': bool(errors) and all(e[0] <= .03 and e[1] <= 5 for e in errors)}
        seams = []
        for event in events:
            if event['kind'] != 'step_started' or event.get('actor_id') != actor or event.get('index') not in [1, 2] or not event.get('step', {}).get('target', '').startswith('gen_' + key + '_'):
                continue
            i = int(np.argmin(abs(times - event['sim_time'])))
            if i + 1 >= len(samples):
                continue
            delta = np.linalg.norm(poses[i + 1, :, :3] - poses[i, :, :3], axis=-1)
            angular = angles(poses[i, :, 3:], poses[i + 1, :, 3:])
            seams.append({'step_index': event['index'], 'sim_time': event['sim_time'], 'sample_time': float(times[i]), 'native_task_id': event.get('native_task_id'), 'root_step_m': float(delta[0]), 'max_joint_step_m': float(delta.max()), 'max_joint_step_deg': float(angular.max()), 'passed': float(delta.max()) <= .02 and float(angular.max()) <= 2})
        passed = all(f['passed'] for f in foot_results.values()) and all(e['passed'] for e in endpoints.values()) and len(seams) == 2 and all(s['passed'] for s in seams)
        results.append({'actor_id': actor, 'case': case, 'samples': len(samples), 'feet': foot_results, 'endpoints': endpoints, 'seams': seams, 'passed': passed})
        print(key, 'PASS' if passed else 'FAIL', flush=True)

inputs = {name: sha(run / name) for name in ['native_pose_history.jsonl', 'events.jsonl', 'source_manifest.json', 'generated_native_acceptance.json', 'asset_manifest.json']}
result = {'passed': acceptance['passed'] and bool(results) and all(r['passed'] for r in results), 'native_lifecycle_passed': acceptance['passed'], 'run_id': args.run_id, 'input_sha256': inputs, 'assets': asset_checks, 'cases': results, 'scope': 'Actual SDK poses, world-space seam deltas, fixed skinned sole patches with independently checked LBS. Estimated support uses height/vertical speed only. Not contact-force, GPU-buffer, live-streaming or exhaustive surface certification.'}
(out / 'generated_quality.json').write_text(json.dumps(result, indent=2) + '\n')
raise SystemExit(0 if result['passed'] else 2)
