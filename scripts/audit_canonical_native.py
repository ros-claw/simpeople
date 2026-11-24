"""Actual native canonical entry/exit, generated-boundary and sole audit."""
import argparse, hashlib, json, math, shutil, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser();p.add_argument('--run-id', required=True);p.add_argument('--output', required=True);args = p.parse_args()
run = ROOT / 'runs' / args.run_id;out = Path(args.output).resolve();out.mkdir(parents=True, exist_ok=False)
snap = out / 'source_snapshot';snap.mkdir();shutil.copytree(ROOT / 'src', snap / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'));shutil.copy2(__file__, snap / Path(__file__).name);sys.path.insert(0, str(snap / 'src'))
import numpy as np
from pxr import Usd, UsdGeom, UsdSkel, Gf
from simpeople.backends.native.foot_geometry import FootGeometry
from simpeople.motion.rig import rotate, multiply, validate_poses
from simpeople.motion.quality import support_quality

def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for part in iter(lambda: f.read(1 << 20), b''):h.update(part)
    return h.hexdigest()

def angles(a, b):
    a = a / np.linalg.norm(a, axis=-1, keepdims=True);b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    return np.degrees(2 * np.arccos(np.clip(np.abs(np.sum(a * b, axis=-1)), 0, 1)))

def body(row):
    v = np.array(row['world_pose']);f = row['actual_observation']['facing_direction'];a = math.atan2(f[0], -f[1]);q = np.array([0, 0, math.sin(-a / 2), math.cos(-a / 2)])
    return rotate(q, v[:, :3] - v[0, :3]), multiply(q, v[:, 3:])

registry = json.loads((run / 'source_snapshot/inputs/actions.json').read_text());lifecycle = json.loads((run / 'generated_native_acceptance.json').read_text());assets = {a['asset_id']: a for a in json.loads((run / 'asset_manifest.json').read_text())};events = [json.loads(l) for l in (run / 'events.jsonl').open()]
selected_goals=[p['name'].removeprefix('canonical_') for p in lifecycle['phases'] if p['name'].startswith('canonical_')]
rows = {'operator': [], 'second': []}
for line in (run / 'native_pose_history.jsonl').open():
    row = json.loads(line)
    if row['actor_id'] in rows:rows[row['actor_id']].append(row)
results = [];asset_checks = []
for actor, asset_id in [('operator', 'default'), ('second', 'female_adult_business_02')]:
    source = Path(assets[asset_id]['source_uri']);assert sha(source) == assets[asset_id]['content_hash']
    original = Usd.Stage.Open(str(source));stage = Usd.Stage.CreateInMemory();UsdGeom.SetStageMetersPerUnit(stage, 1);UsdGeom.SetStageUpAxis(stage, 'Z');model = UsdGeom.Xform.Define(stage, '/World/Model');model.GetPrim().GetReferences().AddReference(str(source));matrix = Gf.Matrix4d().SetScale(UsdGeom.GetStageMetersPerUnit(original))
    if UsdGeom.GetStageUpAxis(original) == 'Y':matrix *= Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1, 0, 0), 90))
    UsdGeom.Xformable(model).MakeMatrixXform().Set(matrix);root = next(UsdSkel.Root(x) for x in Usd.PrimRange(model.GetPrim()) if x.IsA(UsdSkel.Root));sk = next(UsdSkel.Skeleton(x) for x in Usd.PrimRange(root.GetPrim()) if x.IsA(UsdSkel.Skeleton));names = list(map(str, sk.GetJointsAttr().Get()));assert names == rows[actor][0]['joint_paths'];leaves = [n.rsplit('/', 1)[-1] for n in names]
    feet = {side: leaves.index(short) for side, short in [('left', 'L_Ankle' if 'L_Ankle' in leaves else 'L_Foot'), ('right', 'R_Ankle' if 'R_Ankle' in leaves else 'R_Foot')]};geometry = FootGeometry(stage, str(root.GetPath()), feet);asset_checks.append({'actor_id': actor, 'asset_id': asset_id, 'sha256': sha(source), 'patches': geometry.describe()})
    all_rows = rows[actor]
    for goal in selected_goals:
        phase = 'canonical_' + goal;key = actor + '__' + goal;clip = 'canonical_' + key
        positions = [i for i, r in enumerate(all_rows) if r['phase'] == phase];samples = [all_rows[i] for i in positions];poses = validate_poses([r['world_pose'] for r in samples], len(names));times = np.array([r['sim_time'] for r in samples]);assert np.allclose(np.diff(times), 1 / 30, atol=1e-7, rtol=0)
        start_event = next(e for e in events if e['kind'] == 'step_started' and e.get('actor_id') == actor and e.get('step', {}).get('target') == clip);start = start_event['sim_time'];sequence = registry['canonical_sequences'][key]
        soles = [geometry.evaluate(r['world_pose']) for r in samples];foot_results = {}
        for side in feet:
            points = np.array([s[side] for s in soles]);foot_results[side], contact = support_quality(times, points);np.savez_compressed(out / (key + '_' + side + '_sole.npz'), sim_time=times, points_world_m=points, estimated_contact=contact)
        def delta(before, after):
            a = np.array(before['world_pose']);b = np.array(after['world_pose']);d = np.linalg.norm(b[:, :3] - a[:, :3], axis=-1);q = angles(a[:, 3:], b[:, 3:]);return {'from_sim_time': before['sim_time'], 'to_sim_time': after['sim_time'], 'from_action': before['actual_observation']['action'], 'to_action': after['actual_observation']['action'], 'max_joint_step_m': float(d.max()), 'root_step_m': float(d[0]), 'max_joint_step_deg': float(q.max()), 'passed': float(d.max()) <= .02 and float(q.max()) <= 2}
        active = [i for i, r in enumerate(samples) if r['actual_observation']['action'] == clip];seams = []
        if active:
            first = positions[active[0]];last = positions[active[-1]]
            if first > 0:seams.append({'kind': 'native_entry', **delta(all_rows[first - 1], all_rows[first])})
            if last + 1 < len(all_rows):seams.append({'kind': 'native_exit', **delta(all_rows[last], all_rows[last + 1])})
        # This is task-clock timing with an explicit +/-2-frame inspection band,
        # not a fabricated native playback cursor or continuous queue receipt.
        for kind, frame in [('generated_start', sequence['outbound'][0]), ('goal_arrival', sequence['outbound'][1]), ('return_start', sequence['return'][0]), ('return_arrival', sequence['return'][1])]:
            candidates = [delta(samples[i - 1], samples[i]) for i in range(1, len(samples)) if abs(times[i] - start - frame / 30) <= 2 / 30 + 1e-7 and samples[i]['actual_observation']['action'] == samples[i - 1]['actual_observation']['action'] == clip]
            seams.append({'kind': kind, 'scheduled_source_frame': frame, 'samples_in_band': len(candidates), 'max_joint_step_m': max((c['max_joint_step_m'] for c in candidates), default=None), 'max_joint_step_deg': max((c['max_joint_step_deg'] for c in candidates), default=None), 'passed': bool(candidates) and all(c['passed'] for c in candidates), 'deltas': candidates})
        holds = {}
        for kind, reference, bounds in [('entry', registry['canonical_sources'][key]['entry'], [0, sequence['prefix_frames'] - 1]), ('goal', registry['canonical_sources'][key]['goal'], sequence['target_hold']), ('tail', registry['canonical_sources'][key]['entry'], sequence['tail'])]:
            wanted, wanted_q = body(reference);errors = []
            for row in samples:
                t = row['sim_time'] - start
                if bounds[0] / 30 + .5 <= t <= bounds[1] / 30 - .2 and row['actual_observation']['action'] == clip:
                    actual, actual_q = body(row);errors.append([float(np.linalg.norm(wanted - actual, axis=-1).max()), float(angles(wanted_q, actual_q).max())])
            holds[kind] = {'samples': len(errors), 'max_position_error_m': max((e[0] for e in errors), default=None), 'max_rotation_error_deg': max((e[1] for e in errors), default=None), 'passed': bool(errors) and all(e[0] <= .03 and e[1] <= 5 for e in errors)}
        passed = all(f['passed'] for f in foot_results.values()) and len(seams) == 6 and all(s['passed'] for s in seams) and all(h['passed'] for h in holds.values())
        results.append({'actor_id': actor, 'goal': goal, 'clip': clip, 'samples': len(samples), 'actual_clip_samples': len(active), 'feet': foot_results, 'seams': seams, 'holds': holds, 'passed': passed});print(key, 'PASS' if passed else 'FAIL', flush=True)
result = {'passed': lifecycle['passed'] and bool(results) and all(r['passed'] for r in results), 'run_id': args.run_id, 'tested_goals':selected_goals,'partial_matrix':set(selected_goals)!=set(registry['canonical_cases']), 'native_lifecycle_passed': lifecycle['passed'], 'assets': asset_checks, 'cases': results, 'inputs': {n: sha(run / n) for n in ['source_manifest.json', 'events.jsonl', 'native_pose_history.jsonl', 'generated_native_acceptance.json']}, 'scope': 'Single preloaded out-and-back clips. Actual SDK world seams and fixed skinned sole vertices. Scheduled internal boundaries inspected on task time, not an exposed native playhead. No online, hot reload, contact-force or exhaustive surface claim.'}
(out / 'canonical_quality.json').write_text(json.dumps(result, indent=2) + '\n');raise SystemExit(0 if result['passed'] else 2)
