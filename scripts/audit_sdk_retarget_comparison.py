"""Recompute frozen SDK round trips from arrays; never certify playback."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


# These frozen SDK probes load soma_prepared.usda with an explicit Root above
# the 77 model joints. Keep that channel in raw SDK arrays; never drop it to
# make a model-space shape check pass. HumanMotionLibrary has 81 SDK joints.
SDK_TARGET_JOINTS = {'soma': 78, 'human': 81}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pose(value, shape, label, norm_tolerance=1e-4):
    value = np.asarray(value, dtype=float)
    if value.shape != shape or not np.isfinite(value).all():
        raise ValueError('invalid pose shape/finite values: ' + label)
    if np.max(abs(np.linalg.norm(value[..., 3:], axis=-1) - 1)) > norm_tolerance:
        raise ValueError('non-unit quaternion: ' + label)
    return value


def parents(paths):
    if len(set(paths)) != len(paths) or any(not isinstance(p, str) or not p for p in paths):
        raise ValueError('invalid joint paths')
    indices = {p: i for i, p in enumerate(paths)}
    result = []
    for i, path in enumerate(paths):
        ancestor = path.rpartition('/')[0]
        while ancestor and ancestor not in indices:
            ancestor = ancestor.rpartition('/')[0]
        parent = indices.get(ancestor, -1)
        if parent >= i:
            raise ValueError('joints not in parent-first order')
        result.append(parent)
    if result.count(-1) != 1:
        raise ValueError('one skeleton root required')
    return result


def measure(source, recovered, paths):
    """Use saved world poses directly, without the probe's retarget/FK code."""
    topology = parents(paths)
    delta = np.linalg.norm(source[..., :3] - recovered[..., :3], axis=-1)
    a = Rotation.from_quat(source[..., 3:].reshape(-1, 4))
    b = Rotation.from_quat(recovered[..., 3:].reshape(-1, 4))
    angle = np.degrees((a.inv() * b).magnitude()).reshape(delta.shape)
    bones = []
    for joint, parent in enumerate(topology):
        if parent >= 0:
            before = np.linalg.norm(source[:, joint, :3] - source[:, parent, :3], axis=-1)
            after = np.linalg.norm(recovered[:, joint, :3] - recovered[:, parent, :3], axis=-1)
            bones.append(float(abs(after - before).max()))
    return {
        'max_joint_position_error_m': float(delta.max()),
        'max_joint_angle_error_deg': float(angle.max()),
        'worst_position_joint': paths[np.unravel_index(delta.argmax(), delta.shape)[1]],
        'worst_angle_joint': paths[np.unravel_index(angle.argmax(), angle.shape)[1]],
        'max_bone_length_change_m': max(bones, default=0),
        'roundtrip_within_entry_tolerance': bool(delta.max() <= .02 and angle.max() <= 2),
        'joint_errors': [{'joint': path, 'position_m': float(delta[:, i].max()),
                          'angle_deg': float(angle[:, i].max())} for i, path in enumerate(paths)],
    }


def root_basis(poses, rotation):
    result = poses.copy()
    result[:, 0, :3] = rotation.apply(poses[:, 0, :3])
    result[:, 0, 3:] = (rotation * Rotation.from_quat(poses[:, 0, 3:])).as_quat()
    return result


def source_space(asset):
    # OpenUSD data inspection only; no Kit, stage mutation or renderer.
    from pxr import Usd, UsdGeom
    path = Path(asset['source_uri'])
    if sha(path) != asset['content_hash']:
        raise ValueError('source asset revision mismatch')
    stage = Usd.Stage.Open(str(path))
    return float(UsdGeom.GetStageMetersPerUnit(stage)), str(UsdGeom.GetStageUpAxis(stage))


def normalized_input(world, paths, meters, axis):
    topology = parents(paths); local = world.copy()
    for joint, parent in enumerate(topology):
        if parent >= 0:
            inverse = Rotation.from_quat(world[:, parent, 3:]).inv()
            local[:, joint, :3] = inverse.apply(world[:, joint, :3] - world[:, parent, :3])
            local[:, joint, 3:] = (inverse * Rotation.from_quat(world[:, joint, 3:])).as_quat()
    if axis == 'Y':
        local = root_basis(local, Rotation.from_euler('x', -90, degrees=True))
    elif axis != 'Z':
        raise ValueError('unsupported source axis')
    if not np.isfinite(meters) or meters <= 0:
        raise ValueError('invalid source units')
    local[..., :3] /= meters
    origin = local[0, 0, :3].copy(); local[:, 0, :3] -= origin
    return local, origin


def recover_world(local, paths, meters, axis, origin):
    local = local.copy(); local[:, 0, :3] += origin; local[..., :3] *= meters
    if axis == 'Y':
        local = root_basis(local, Rotation.from_euler('x', 90, degrees=True))
    world = local.copy()
    for joint, parent in enumerate(parents(paths)):
        if parent >= 0:
            rotation = Rotation.from_quat(world[:, parent, 3:])
            world[:, joint, :3] = world[:, parent, :3] + rotation.apply(local[:, joint, :3])
            world[:, joint, 3:] = (rotation * Rotation.from_quat(local[:, joint, 3:])).as_quat()
    return world


def audit(folder, plan_path):
    folder, plan_path = Path(folder), Path(plan_path)
    errors, results, bindings = [], [], {}
    try:
        plan = json.loads(plan_path.read_text())
        read = lambda name: json.loads((folder / name).read_text())
        if folder.name != plan['run_id'] or plan['comparisons'] not in (24, 48) or plan['case_count'] != 6:
            raise ValueError('unexpected frozen experiment')
        snapshot = folder / 'source_snapshot'
        run_manifest = read('source_manifest.json')
        original_manifest = Path(plan['source']) / 'source_manifest.json'
        if sha(original_manifest) != plan['source_manifest_sha256']:
            raise ValueError('original source manifest binding changed')
        original = json.loads(original_manifest.read_text())
        source_files = {n: h for n, h in original.items() if n.split('/')[0] in {'src', 'configs', 'schemas'}}
        if {n: h for n, h in run_manifest.items() if n not in {'inputs.json', 'probe.py'}} != source_files:
            raise ValueError('run manifest differs from frozen runtime source')
        for name, expected in run_manifest.items():
            path = snapshot / name
            if not path.resolve().is_relative_to(snapshot.resolve()) or not path.is_file() or sha(path) != expected:
                raise ValueError('frozen source changed: ' + name)
        for name, key in [('inputs.json', 'inputs_sha256'), ('probe.py', 'probe_sha256')]:
            if sha(snapshot / name) != plan[key]:
                raise ValueError('probe/input binding mismatch: ' + name)
        bindings[str(original_manifest)] = plan['source_manifest_sha256']
        for name, expected in plan.get('input_references_sha256', {}).items():
            if sha(Path(name)) != expected:
                raise ValueError('context reference revision changed: ' + name)
            bindings[name] = expected
        data = read('source_snapshot/inputs.json')
        assets = {a['asset_id']: a for a in data['assets']}
        spaces = {}
        for actor, asset_id in [('operator', 'default'), ('second', 'female_adult_business_02')]:
            asset = assets[asset_id]; spaces[actor] = source_space(asset)
            bindings[asset['source_uri']] = asset['content_hash']
        done, summary = read('completed.json'), read('sdk_metadata_chain_measurements.json')
        if (done.get('harness_completed') is not True or done.get('comparisons') != plan['comparisons']
                or done.get('native_animation_playback_tested') is not False
                or summary.get('harness_completed') is not True
                or summary.get('native_animation_playback_tested') is not False
                or summary.get('qualified_generated_native_rigs') != []):
            raise ValueError('unclosed experiment or unsupported playback claim')
        setups = ['prepared', 'sdk_imported'] if plan['comparisons'] == 48 else ['prepared']
        cases = data['cases']
        if set(cases) != {a + '__' + s for a in ('operator', 'second') for s in ('idle', 'left_low', 'look_left')}:
            raise ValueError('six exact context cases required')
        expected = set(itertools.product(cases, setups, (False, True), ('direct', 'via_human')))
        seen, inputs_by_case = set(), {}
        for row in summary['comparisons']:
            key = row['case'], row.get('soma_setup', 'prepared'), row['preserve_control_rig_api'], row['route']
            if type(key[2]) is not bool or key not in expected or key in seen:
                raise ValueError('duplicate, extra or mistyped comparison')
            seen.add(key)
            case = cases[key[0]]
            samples = case['rows']; paths = samples[0]['joint_paths']
            if len(samples) != 4 or len(paths) != (81 if key[0].startswith('operator__') else 101):
                raise ValueError('all four frames and all actor joints required')
            times = [s['sim_time'] for s in samples]
            if (any(s['joint_paths'] != paths for s in samples)
                    or any(type(t) not in (float, int) or not np.isfinite(t) for t in times)
                    or any(abs(b - a - 1/30) > 1e-6 for a, b in zip(times, times[1:]))
                    or case['active_descriptor']['joints'] != paths):
                raise ValueError('input context topology/timing mismatch')
            shape = (4, len(paths), 7)
            # Preserve the exact raw SDK values. The existing world_to_local
            # input contract allows 1e-3; normalized SDK outputs remain stricter.
            source = pose([s['world_pose'] for s in samples], shape, 'frozen source', 1e-3)
            ident = key[0] + ('__' + key[1] if len(setups) == 2 else '') + '__' + str(key[2]) + '__' + key[3]
            archive = folder / (ident + '.npz'); bindings[archive.name] = sha(archive)
            with np.load(archive, allow_pickle=False) as arrays:
                actual = pose(arrays['source_world'], shape, 'source_world', 1e-3)
                if not np.array_equal(actual, source):
                    raise ValueError('saved comparison source differs from actual frozen input')
                local = pose(arrays['source_local'], shape, 'source_local')
                meters, axis = spaces[key[0].split('__')[0]]
                computed_local, origin = normalized_input(source, paths, meters, axis)
                local_check = measure(computed_local, local, paths)
                if local_check['max_joint_position_error_m'] > 1e-5 or local_check['max_joint_angle_error_deg'] > 1e-4:
                    raise ValueError('SDK input differs from independently converted context')
                if key[0] in inputs_by_case and not np.array_equal(local, inputs_by_case[key[0]]):
                    raise ValueError('unequal source_local across experimental variants')
                inputs_by_case[key[0]] = local.copy()
                edges = [('source', 'soma'), ('soma', 'source')] if key[3] == 'direct' else [
                    ('source', 'human'), ('human', 'soma'), ('soma', 'human'), ('human', 'source')]
                names = {'source_world', 'recovered_world', 'source_local'}
                for i, (a, b) in enumerate(edges):
                    name = f'{i}_{a}_to_{b}'; names.add(name)
                    joints = len(paths) if b == 'source' else SDK_TARGET_JOINTS[b]
                    pose(arrays[name], (4, joints, 7), name)
                if set(arrays.files) != names:
                    raise ValueError('missing or unexpected saved SDK stage')
                recovered = pose(arrays['recovered_world'], shape, 'recovered_world')
                final_name = f'{len(edges)-1}_{edges[-1][0]}_to_source'
                independent = recover_world(arrays[final_name], paths, meters, axis, origin)
                check = measure(independent, recovered, paths)
                if check['max_joint_position_error_m'] > 1e-6 or check['max_joint_angle_error_deg'] > 1e-4:
                    raise ValueError('recovered world differs from actual final SDK stage')
                metrics = measure(source, recovered, paths)
            if (row['frames'] != 4 or row['all_joints'] != len(paths)
                    or row['descriptor_provenance'] != case['descriptor_provenance']
                    or row.get('native_animation_playback_tested') is not False):
                raise ValueError('reported case denominator/provenance mismatch')
            for field, tolerance in [('max_joint_position_error_m', 1e-7), ('max_joint_angle_error_deg', 1e-5)]:
                value = row[field]
                if type(value) not in (int, float) or not np.isfinite(value) or abs(value - metrics[field]) > tolerance:
                    raise ValueError('reported metric differs from raw arrays: ' + field)
            for field in ('worst_position_joint', 'worst_angle_joint'):
                if row[field] != metrics[field]:
                    raise ValueError('reported worst joint differs: ' + field)
            norm_error = row['sdk_quaternion_renormalization_max']
            if type(norm_error) not in (int, float) or not np.isfinite(norm_error) or not 0 <= norm_error <= .01:
                raise ValueError('invalid reported SDK renormalization')
            results.append({'case': key[0], 'soma_setup': key[1], 'preserve_control_rig_api': key[2],
                            'route': key[3], 'descriptor_provenance': case['descriptor_provenance'],
                            'input_quaternion_norm_error_max': float(abs(np.linalg.norm(source[..., 3:], axis=-1)-1).max()),
                            **metrics})
        if seen != expected:
            raise ValueError('comparison matrix incomplete')
        if len(setups) == 2:
            metadata = read('actual_import_setup_metadata.json')
            json.dumps(metadata, allow_nan=False)
            fields = {'joints', 'restTransforms', 'bindTransforms', 'controlRig:retargetTags',
                      'controlRig:retargetTransforms', 'controlRig:upAxis', 'controlRig:forwardAxis', 'control_rig_api'}
            if (set(metadata['before']) != fields or set(metadata['after']) != fields
                    or metadata['before']['control_rig_api'] is not True
                    or metadata['after']['control_rig_api'] is not True
                    or type(metadata['should_auto_pose_before']) is not bool):
                raise ValueError('invalid actual SDK import metadata')
            for descriptor in [metadata['before'], metadata['after']]:
                names = descriptor['joints']
                if (not isinstance(names, list) or len(names) != SDK_TARGET_JOINTS['soma']
                        or names[0] != 'Root'):
                    raise ValueError('SDK SOMA must retain Root plus77 model joints')
                parents(names)
            changed = [k for k in metadata['before'] if metadata['before'][k] != metadata['after'][k]]
            if metadata['changed_fields'] != changed or done['sdk_import_setup_changed_fields'] != changed:
                raise ValueError('reported setup changes differ from actual metadata')
            bindings['actual_import_setup_metadata.json'] = sha(folder / 'actual_import_setup_metadata.json')
        for name in ('source_manifest.json', 'source_snapshot/inputs.json', 'source_snapshot/probe.py',
                     'completed.json', 'sdk_metadata_chain_measurements.json'):
            bindings[name] = sha(folder / name)
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        errors.append(str(error))
    return {'run_id': folder.name, 'method_version': 'simpeople.sdk-retarget-array-audit.v1',
            'verified': not errors, 'errors': errors, 'comparisons_recomputed': len(results),
            'comparisons': results, 'inputs_sha256': bindings,
            'plan_sha256': sha(plan_path) if plan_path.is_file() else None,
            'native_animation_playback_tested': False, 'qualified_generated_native_rigs': [],
            'production_source_installed': False,
            'sdk_target_joint_counts': SDK_TARGET_JOINTS.copy(),
            'model_soma_joint_count': 77,
            'scope': 'Array integrity and all-joint round-trip measurements only. '
                     'Entry-tolerance comparisons do not qualify body entry, animation, cancellation or a rig.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run'); parser.add_argument('--plan', required=True); parser.add_argument('--output', required=True)
    args = parser.parse_args(); result = audit(args.run, args.plan)
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps({k: result[k] for k in ('run_id', 'verified', 'comparisons_recomputed', 'errors')}))
    return 0 if result['verified'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
