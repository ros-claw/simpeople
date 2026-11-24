import importlib.util
import json
from pathlib import Path
import shutil

import pytest

spec = importlib.util.spec_from_file_location('sdk_recovery_audit', Path(__file__).parents[1]/'scripts/audit_sdk_recovery_handoff.py')
reader = importlib.util.module_from_spec(spec); spec.loader.exec_module(reader)


def freeze(folder, path):
    values = {str(p.relative_to(folder)): reader.sha(p) for p in folder.rglob('*') if p.is_file()}
    path.write_text(json.dumps(values))
    return reader.sha(path)


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path/'source'; run = tmp_path/'run'; source.mkdir(); run.mkdir()
    for name, value in {'src/simpeople/runtime.py': '# runtime\n',
                        'configs/custom_actions.json': '{}\n',
                        'configs/custom_action_acceptance.json': '{}\n',
                        'schemas/action.json': '{}\n',
                        'reports/capability_matrix.json': '{}\n',
                        'scripts/not_executed.py': '# other probe\n'}.items():
        p = source/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)
    source_sha = freeze(source, source/'source_manifest.json')
    clip = tmp_path/'clip.usda'; clip.write_text('#usda 1.0\n')
    registry = tmp_path/'registry.json'; registry.write_text('{"registry":true}\n')
    atlas = tmp_path/'atlas.json'; atlas.write_text('{"atlas":true}\n')
    data = {'actions': {'reach': {'clip': str(clip)}}, 'source_registry': str(registry),
            'source_registry_sha256': reader.sha(registry), 'atlas_registry': str(atlas),
            'atlas_registry_sha256': reader.sha(atlas)}
    input_spec = tmp_path/'spec.json'; input_spec.write_text(json.dumps(data))
    probe = tmp_path/'probe_v2.py'; probe.write_text('# launched v2, stored as probe.py\n')
    snap = run/'source_snapshot'; snap.mkdir()
    for name in ['src', 'configs', 'schemas', 'reports']: shutil.copytree(source/name, snap/name)
    shutil.copy2(probe, snap/'probe.py'); shutil.copy2(input_spec, snap/'spec.json')
    (snap/'configs/custom_actions.json').write_text(json.dumps({'actions': data['actions']}, indent=2)+'\n')
    (snap/'configs/custom_action_acceptance.json').write_text('{}\n')
    freeze(snap, run/'source_manifest.json')
    (run/'sdk_settings.json').write_text(json.dumps({'source_inputs_sha256': {str(clip): reader.sha(clip)}}))
    plan = {'source': str(source), 'source_manifest_sha256': source_sha,
            'argv': ['python.sh', str(probe), '--spec', str(input_spec)],
            'frozen_files': {str(p): reader.sha(p) for p in [probe, input_spec]},
            'external_inputs': {str(clip): reader.sha(clip)}}
    return plan, run, source, clip


def test_exact_source_probe_alias_and_only_two_config_replacements(inputs):
    plan, run, _, _ = inputs
    _, result = reader.source_review(plan, run)
    assert result['execution_source_verified'] and result['snapshot_members'] == 7


@pytest.mark.parametrize('fault', ['source', 'manifest', 'probe', 'spec', 'asset',
                                  'registry', 'snapshot', 'unlisted', 'extra', 'wrong_config'])
def test_input_or_execution_drift_is_never_accepted(inputs, fault):
    plan, run, source, clip = inputs; snap = run/'source_snapshot'
    paths = {'source': source/'src/simpeople/runtime.py', 'manifest': source/'source_manifest.json',
             'probe': Path(plan['argv'][1]), 'spec': Path(plan['argv'][-1]), 'asset': clip,
             'registry': Path(json.loads((snap/'spec.json').read_text())['atlas_registry']),
             'snapshot': snap/'src/simpeople/runtime.py', 'unlisted': snap/'src/hidden.py',
             'extra': snap/'extra.py', 'wrong_config': snap/'configs/custom_actions.json'}
    paths[fault].write_text('# changed\n')
    if fault in {'extra', 'wrong_config'}:
        # Updating a self-authored execution manifest must not authorize changes.
        freeze(snap, run/'source_manifest.json')
    with pytest.raises((AssertionError, ValueError)):
        reader.source_review(plan, run)


def test_a_self_hashed_manifest_cannot_escape_the_declared_source_root(inputs):
    plan, run, source, clip = inputs
    manifest = json.loads((source/'source_manifest.json').read_text())
    manifest['../clip.usda'] = reader.sha(clip)
    (source/'source_manifest.json').write_text(json.dumps(manifest))
    plan['source_manifest_sha256'] = reader.sha(source/'source_manifest.json')
    with pytest.raises(AssertionError): reader.source_review(plan, run)


@pytest.mark.parametrize('fault', ['unknown', 'missing_declared', 'different_reference'])
def test_fixed_heading_entry_cannot_use_an_undeclared_or_different_frame(fault):
    spec = {'recovery_entry_alignment': 'fixed_declared_heading', 'declared_placement_facing': [0, 1, 0]}
    reference = {'declared_placement_facing': [0, 1, 0]}
    if fault == 'unknown': spec['recovery_entry_alignment'] = 'arbitrary'
    elif fault == 'missing_declared': spec.pop('declared_placement_facing')
    elif fault == 'different_reference': reference['declared_placement_facing'] = [1, 0, 0]
    with pytest.raises(ValueError): reader.compare_entry(spec, {}, reference)
