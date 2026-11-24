import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation


spec = importlib.util.spec_from_file_location('sdk_array_audit', Path(__file__).parents[1] / 'scripts/audit_sdk_retarget_comparison.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + '\n')


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'source_space', lambda a: (.01, 'Y') if a['asset_id'] == 'default' else (1., 'Z'))

    def make(import_setup=False):
        folder = tmp_path / ('sdk48' if import_setup else 'sdk24'); folder.mkdir()
        snapshot = folder / 'source_snapshot'; snapshot.mkdir(); (snapshot / 'probe.py').write_text('# frozen fixture\n')
        original = folder / 'original_source'; original.mkdir()
        (snapshot / 'src').mkdir(); (snapshot / 'src/runtime.py').write_text('# runtime\n')
        write(original / 'source_manifest.json', {'src/runtime.py': module.sha(snapshot / 'src/runtime.py')})
        cases, rows = {}, []
        for actor, n in [('operator', 81), ('second', 101)]:
            paths = ['Root'] + [f'Root/J{i}' for i in range(1, n)]
            world = np.zeros((4, n, 7)); world[..., 6] = 1
            world[..., :3] = [1, 2, 3]
            world[:, :, 2] += np.arange(n)[None, :] * .01
            world[:, 0, 0] += np.arange(4) * .001
            world[..., 3:] = Rotation.from_euler('z', np.arange(n) * .1, degrees=True).as_quat()[None]
            world[:, 2, 3:] *= 1.0003  # Actual frozen SDK contexts have similar raw norm error.
            meters, axis = (.01, 'Y') if actor == 'operator' else (1., 'Z')
            for phase in ['idle', 'left_low', 'look_left']:
                name = actor + '__' + phase
                samples = [{'joint_paths': paths, 'sim_time': 2 + i / 30, 'world_pose': frame.tolist()} for i, frame in enumerate(world)]
                cases[name] = {'rows': samples, 'active_descriptor': {'joints': paths}, 'descriptor_provenance': 'fixture' if phase == 'idle' else 'counterfactual descriptor'}
                local, origin = module.normalized_input(world, paths, meters, axis)
                for setup in (['prepared', 'sdk_imported'] if import_setup else ['prepared']):
                    for api in [False, True]:
                        for route in ['direct', 'via_human']:
                            ident = name + ('__' + setup if import_setup else '') + '__' + str(api) + '__' + route
                            edges = [('source', 'soma'), ('soma', 'source')] if route == 'direct' else [('source', 'human'), ('human', 'soma'), ('soma', 'human'), ('human', 'source')]
                            arrays = {'source_world': world, 'source_local': local, 'recovered_world': module.recover_world(local, paths, meters, axis, origin)}
                            for i, (a, b) in enumerate(edges):
                                if b == 'source': values = local
                                else:
                                    values = np.zeros((4, {'soma': 78, 'human': 81}[b], 7)); values[..., 6] = 1
                                arrays[f'{i}_{a}_to_{b}'] = values
                            np.savez(folder / (ident + '.npz'), **arrays)
                            metrics = module.measure(world, arrays['recovered_world'], paths)
                            row = {'case': name, 'preserve_control_rig_api': api, 'route': route, 'frames': 4, 'all_joints': n,
                                   'descriptor_provenance': cases[name]['descriptor_provenance'], 'native_animation_playback_tested': False,
                                   'sdk_quaternion_renormalization_max': 0., **metrics}
                            if import_setup: row['soma_setup'] = setup
                            rows.append(row)
        assets = [{'asset_id': a, 'source_uri': a + '.usd', 'content_hash': 'fixture'} for a in ['default', 'female_adult_business_02']]
        write(snapshot / 'inputs.json', {'cases': cases, 'assets': assets})
        write(folder / 'source_manifest.json', {str(p.relative_to(snapshot)): module.sha(p) for p in snapshot.rglob('*') if p.is_file()})
        done = {'harness_completed': True, 'comparisons': len(rows), 'native_animation_playback_tested': False}
        if import_setup:
            before = {k: [] for k in ['joints', 'restTransforms', 'bindTransforms', 'controlRig:retargetTags', 'controlRig:retargetTransforms']}
            before['joints'] = ['Root'] + ['Root/J'+str(i) for i in range(1,78)]
            before.update({'controlRig:upAxis': 'Y', 'controlRig:forwardAxis': 'Z', 'control_rig_api': True})
            after = {**before, 'controlRig:forwardAxis': '-Z'}
            write(folder / 'actual_import_setup_metadata.json', {'before': before, 'after': after,
                  'changed_fields': ['controlRig:forwardAxis'], 'should_auto_pose_before': False})
            done['sdk_import_setup_changed_fields'] = ['controlRig:forwardAxis']
        write(folder / 'completed.json', done)
        write(folder / 'sdk_metadata_chain_measurements.json', {'harness_completed': True, 'comparisons': rows,
              'native_animation_playback_tested': False, 'qualified_generated_native_rigs': []})
        plan = tmp_path / (folder.name + '_plan.json')
        write(plan, {'run_id': folder.name, 'comparisons': len(rows), 'case_count': 6,
                     'source': str(original), 'source_manifest_sha256': module.sha(original / 'source_manifest.json'),
                     'inputs_sha256': module.sha(snapshot / 'inputs.json'), 'probe_sha256': module.sha(snapshot / 'probe.py')})
        return folder, plan
    return make


@pytest.mark.parametrize('setup', [False, True])
def test_complete_array_matrix_is_not_playback_qualification(experiment, setup):
    folder, plan = experiment(setup); result = module.audit(folder, plan)
    assert result['verified'], result['errors']
    assert result['comparisons_recomputed'] == (48 if setup else 24)
    assert result['qualified_generated_native_rigs'] == []
    assert result['native_animation_playback_tested'] is False
    assert len(result['comparisons'][-1]['joint_errors']) == 101


@pytest.mark.parametrize('corrupt', ['duplicate', 'missing', 'metric', 'worst', 'provenance', 'playback', 'nan_metric', 'boolean_api', 'joint_count'])
def test_reject_bad_summary(experiment, corrupt):
    folder, plan = experiment(); file = folder / 'sdk_metadata_chain_measurements.json'; data = json.loads(file.read_text()); row = data['comparisons'][0]
    if corrupt == 'duplicate': data['comparisons'][-1] = row
    elif corrupt == 'missing': data['comparisons'].pop()
    elif corrupt == 'metric': row['max_joint_position_error_m'] += .1
    elif corrupt == 'worst': row['worst_angle_joint'] = 'Missing'
    elif corrupt == 'provenance': row['descriptor_provenance'] = 'actual instead of counterfactual'
    elif corrupt == 'playback': data['native_animation_playback_tested'] = True
    elif corrupt == 'nan_metric': row['max_joint_angle_error_deg'] = float('nan')
    elif corrupt == 'boolean_api': row['preserve_control_rig_api'] = 0
    elif corrupt == 'joint_count': row['all_joints'] -= 1
    write(file, data); assert not module.audit(folder, plan)['verified']


@pytest.mark.parametrize('corrupt', ['source', 'local', 'recovered', 'stage', 'nan', 'quaternion', 'extra', 'pickle'])
def test_reject_corrupt_raw_sdk_arrays(experiment, corrupt):
    folder, plan = experiment(); file = folder / 'operator__idle__False__direct.npz'
    with np.load(file, allow_pickle=False) as saved: arrays = {k: saved[k].copy() for k in saved.files}
    if corrupt == 'source': arrays['source_world'][0, 2, 0] += .1
    elif corrupt == 'local': arrays['source_local'][0, 2, 0] += 1
    elif corrupt == 'recovered': arrays['recovered_world'][0, 2, 0] += .1
    elif corrupt == 'stage': arrays['1_soma_to_source'][0, 2, 0] += 1
    elif corrupt == 'nan': arrays['0_source_to_soma'][0, 2, 0] = np.nan
    elif corrupt == 'quaternion': arrays['0_source_to_soma'][0, 2, 6] = 0
    elif corrupt == 'extra': arrays['untracked'] = np.zeros(1)
    elif corrupt == 'pickle': arrays['recovered_world'] = np.array([{}], dtype=object)
    np.savez(file, **arrays); assert not module.audit(folder, plan)['verified']


@pytest.mark.parametrize('field', ['changed_fields', 'should_auto_pose_before', 'control_rig_api'])
def test_reject_invalid_import_setup_report(experiment, field):
    folder, plan = experiment(True); file = folder / 'actual_import_setup_metadata.json'; data = json.loads(file.read_text())
    if field == 'changed_fields': data[field] = []
    elif field == 'should_auto_pose_before': data[field] = 0
    else: data['after'][field] = False
    write(file, data); assert not module.audit(folder, plan)['verified']


def test_reject_changed_frozen_input(experiment):
    folder, plan = experiment(); (folder / 'source_snapshot/probe.py').write_text('# changed\n')
    assert not module.audit(folder, plan)['verified']


def test_reject_changed_runtime_even_if_local_manifest_rewritten(experiment):
    folder, plan = experiment(); file = folder / 'source_snapshot/src/runtime.py'; file.write_text('# replacement\n')
    manifest = folder / 'source_manifest.json'; data = json.loads(manifest.read_text()); data['src/runtime.py'] = module.sha(file)
    write(manifest, data)
    result = module.audit(folder, plan)
    assert not result['verified'] and 'frozen runtime' in result['errors'][0]


def test_missing_plan_is_unverified(tmp_path):
    assert not module.audit(tmp_path / 'missing', tmp_path / 'no_plan.json')['verified']


def test_all_joint_angle_and_bone_error_recomputed():
    source = np.zeros((4, 3, 7)); source[..., 6] = 1; source[:, 1, 0] = 1; source[:, 2, 0] = 2
    recovered = source.copy(); recovered[:, 2, 0] += .025
    recovered[:, 2, 3:] = Rotation.from_euler('z', 3, degrees=True).as_quat()
    result = module.measure(source, recovered, ['Root', 'Root/A', 'Root/A/B'])
    assert result['max_joint_position_error_m'] == pytest.approx(.025)
    assert result['max_joint_angle_error_deg'] == pytest.approx(3)
    assert result['max_bone_length_change_m'] == pytest.approx(.025)
    assert result['roundtrip_within_entry_tolerance'] is False


def test_correctly_measured_bad_roundtrip_is_not_hidden(experiment):
    folder, plan = experiment(); file = folder / 'operator__idle__False__direct.npz'
    with np.load(file, allow_pickle=False) as saved: arrays = {k: saved[k].copy() for k in saved.files}
    data = json.loads((folder / 'source_snapshot/inputs.json').read_text())
    paths = data['cases']['operator__idle']['rows'][0]['joint_paths']
    arrays['recovered_world'][:, -1, 0] += .03
    _, origin = module.normalized_input(arrays['source_world'], paths, .01, 'Y')
    final, _ = module.normalized_input(arrays['recovered_world'], paths, .01, 'Y')
    arrays['1_soma_to_source'] = final
    np.savez(file, **arrays)
    report = folder / 'sdk_metadata_chain_measurements.json'; summary = json.loads(report.read_text())
    summary['comparisons'][0].update(module.measure(arrays['source_world'], arrays['recovered_world'], paths))
    write(report, summary); result = module.audit(folder, plan)
    assert result['verified'], result['errors']
    assert result['comparisons'][0]['max_joint_position_error_m'] == pytest.approx(.03)
    assert result['comparisons'][0]['roundtrip_within_entry_tolerance'] is False
    assert result['qualified_generated_native_rigs'] == []


def test_source_asset_space_hash_bound(tmp_path):
    from pxr import Usd, UsdGeom
    path = tmp_path / 'space.usda'; stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, .01); UsdGeom.SetStageUpAxis(stage, 'Y'); stage.GetRootLayer().Save()
    asset = {'source_uri': str(path), 'content_hash': module.sha(path)}
    assert module.source_space(asset) == (.01, 'Y')
    asset['content_hash'] = 'wrong'
    with pytest.raises(ValueError, match='revision'): module.source_space(asset)


def test_raw_sdk_norm_contract_does_not_relax_normalized_output():
    value = np.zeros((4, 2, 7)); value[..., 6] = 1.0003
    assert module.pose(value, value.shape, 'raw input', 1e-3) is not None
    with pytest.raises(ValueError, match='quaternion'): module.pose(value, value.shape, 'normalized SDK output')
    value[..., 6] = 1.002
    with pytest.raises(ValueError, match='quaternion'): module.pose(value, value.shape, 'raw input', 1e-3)


def test_model77_array_cannot_replace_actual_sdk78_array(experiment):
    folder, plan = experiment(True)
    file = folder/'operator__idle__prepared__False__direct.npz'
    with np.load(file,allow_pickle=False) as saved:
        arrays={k:saved[k].copy() for k in saved.files}
    arrays['0_source_to_soma']=arrays['0_source_to_soma'][:,1:]
    np.savez(file,**arrays)
    result=module.audit(folder,plan)
    assert not result['verified'] and '0_source_to_soma' in result['errors'][0]


@pytest.mark.parametrize('fault',['missing_root','wrong_count','foreign_parent','duplicate'])
def test_recorded_sdk_target_topology_is_checked(experiment,fault):
    folder,plan=experiment(True);file=folder/'actual_import_setup_metadata.json';data=json.loads(file.read_text())
    for key in ['before','after']:
        paths=data[key]['joints']
        if fault=='missing_root':paths[0]='Hips'
        elif fault=='wrong_count':paths.pop()
        elif fault=='foreign_parent':paths[1]='ForeignRoot/J1'
        else:paths[2]=paths[1]
    write(file,data)
    assert not module.audit(folder,plan)['verified']
