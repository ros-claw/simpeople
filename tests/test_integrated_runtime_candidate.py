import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('integrated_builder', ROOT/'scripts/prepare_integrated_runtime_candidate.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


def manifest(folder):
    values = {str(p.relative_to(folder)): builder.sha(p) for p in folder.rglob('*')
              if p.is_file() and p.name != 'source_manifest.json'}
    path = folder/'source_manifest.json'; path.write_text(json.dumps(values))
    return path, builder.sha(path)


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path/'root'; features = tmp_path/'features'
    names = set(builder.FEATURE_FILES) | set(builder.PRESERVED_FILES)
    names |= {'core/gesture_profiles.py', 'core/gestures.py', 'backends/native/gestures.py'}
    for folder, label in [(root, 'current-fix'), (features, 'reviewed-feature')]:
        for name in names:
            p = folder/'src/simpeople'/name; p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('# '+label+' '+name+'\n')
        profile = folder/'src/simpeople/core/gesture_profiles.py'
        profile.write_bytes((ROOT/'src/simpeople/core/gesture_profiles.py').read_bytes())
        (folder/'src/simpeople/core/engine.py').write_bytes((ROOT/'src/simpeople/core/engine.py').read_bytes())
        catalog = folder/'configs/native_gesture_catalog.json'; catalog.parent.mkdir()
        variant = {'status': 'verified', 'max_hold_duration_s': 2,
                   'implementation_sha256': 'old-digest', **{k: 'old-proof' for k in builder.PROOF_FIELDS}}
        record = {'status': 'verified', 'kind': 'head_look', 'domain': {'max_yaw_deg': 45},
                  'startup_profiles': {'basic': variant}, **{k: 'old-proof' for k in builder.PROOF_FIELDS}}
        catalog.write_text(json.dumps({'records': [record]}))
    root_path, root_sha = manifest(root); _, features_sha = manifest(features)
    return root, root_path, root_sha, features, features_sha, tmp_path/'candidate'


def test_composition_keeps_current_fixes_imports_reviewed_files_and_strips_proof(inputs):
    root, root_manifest, root_sha, features, features_sha, destination = inputs
    before = {str(p): p.read_bytes() for folder in [root, features] for p in folder.rglob('*') if p.is_file()}
    receipt = builder.prepare(*inputs)
    for name in builder.FEATURE_FILES:
        assert (destination/'src/simpeople'/name).read_bytes() == (features/'src/simpeople'/name).read_bytes()
    for name in builder.PRESERVED_FILES:
        assert (destination/'src/simpeople'/name).read_bytes() == (root/'src/simpeople'/name).read_bytes()
    catalog = json.loads((destination/'configs/native_gesture_catalog.json').read_text())
    record = catalog['records'][0]; variant = record['startup_profiles']['basic']
    assert record['status'] == variant['status'] == 'discovered'
    assert record['domain'] == {'max_yaw_deg': 45} and variant['max_hold_duration_s'] == 2
    assert not any(key in data for data in [record, variant] for key in builder.PROOF_FIELDS)
    assert variant['implementation_sha256'] == receipt['implementation_sha256']
    actual = builder.check_manifest(destination, destination/'source_manifest.json', receipt['source_manifest_sha256'])
    expected = {n.removeprefix('src/simpeople/') for n in actual if n.startswith('src/simpeople/') and n.endswith('.py')}
    assert set(receipt['implementation_files']) == expected
    assert 'result.pop(key, None)' in (destination/'src/simpeople/core/gesture_profiles.py').read_text()
    assert receipt['previous_native_proof_transferred'] is False
    assert receipt['production_source_installed'] is False
    assert receipt['qualified_generated_native_rigs'] == []
    assert all(Path(p).read_bytes() == content for p, content in before.items())


@pytest.mark.parametrize('side', ['root', 'features'])
def test_mutated_inputs_rejected_before_destination_is_created(inputs, side):
    folder = inputs[0 if side == 'root' else 3]
    (folder/'src/simpeople/core/engine.py').write_text('# changed since frozen\n')
    with pytest.raises(ValueError, match='input bytes/path differ'):
        builder.prepare(*inputs)
    assert not inputs[-1].exists()


@pytest.mark.parametrize('side', ['root', 'features'])
def test_manifest_hash_mismatch_is_not_accepted(inputs, side):
    args = list(inputs); args[2 if side == 'root' else 4] = 'wrong'
    with pytest.raises(ValueError, match='manifest differs'):
        builder.prepare(*args)
    assert not inputs[-1].exists()


def test_never_overwrites_an_existing_candidate(inputs):
    builder.prepare(*inputs)
    before = builder.sha(inputs[-1]/'source_manifest.json')
    with pytest.raises(ValueError, match='new destination'):
        builder.prepare(*inputs)
    assert builder.sha(inputs[-1]/'source_manifest.json') == before


@pytest.mark.parametrize('name', ['../escape.py', '/absolute.py', 'src/../escape.py', 'a//b.py'])
def test_manifest_cannot_read_outside_the_declared_input(inputs, name):
    root, path, _, features, features_sha, destination = inputs
    data = json.loads(path.read_text()); data[name] = 'bad'; path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='input bytes/path differ'):
        builder.prepare(root, path, builder.sha(path), features, features_sha, destination)
    assert not destination.exists()


def test_every_selected_package_file_contributes_to_the_new_domain_digest(inputs):
    receipt = builder.prepare(*inputs); destination = inputs[-1]
    spec = importlib.util.spec_from_file_location('frozen_integrated_profile', destination/'src/simpeople/core/gesture_profiles.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    for name in receipt['implementation_files']:
        p = destination/'src/simpeople'/name; original = p.read_bytes()
        try:
            p.write_bytes(original+b'\n# changed\n')
            assert module.implementation_revision(destination/'src/simpeople') != receipt['implementation_sha256']
        finally:
            p.write_bytes(original)
    assert module.implementation_revision(destination/'src/simpeople') == receipt['implementation_sha256']


@pytest.mark.parametrize('source,digest', [(None, 'digest'), ('source', None)])
def test_partial_legacy_binding_is_rejected(inputs, source, digest):
    with pytest.raises(ValueError, match='supplied together'):
        builder.prepare(*inputs, legacy_source=source, legacy_sha=digest)
    assert not inputs[-1].exists()


def test_optional_floor_entry_preserves_every_other_registered_action(inputs, tmp_path):
    root, root_manifest, _, features, features_sha, destination = inputs
    root_registry = root/'configs/custom_actions.json'
    original = {'actions': {'floor_stretch': {'clip': 'old'}, 'other': {'clip': 'keep'}}}
    root_registry.write_text(json.dumps(original)); root_manifest, root_sha = manifest(root)
    legacy = tmp_path/'legacy'; (legacy/'configs').mkdir(parents=True)
    entry = {'skeleton': 'cache://behavior/MotionLibrary/Human/HumanMotionLibrary.usd',
             'clip': 'cache://legacy/floor_tail_eq01/floor_stretch.usda',
             'playback_mode': 'loop', 'clearance_radius_m': 2.5}
    (legacy/'configs/custom_actions.json').write_text(json.dumps({'actions': {'floor_stretch': entry}}))
    _, legacy_sha = manifest(legacy)
    receipt = builder.prepare(root, root_manifest, root_sha, features, features_sha, destination, legacy, legacy_sha)
    selected = json.loads((destination/'configs/custom_actions.json').read_text())
    assert selected['actions'] == {'floor_stretch': entry, 'other': original['actions']['other']}
    assert json.loads(root_registry.read_text()) == original
    assert receipt['legacy_entry_replaced'] is True
    assert receipt['previous_native_proof_transferred'] is False


def test_old_feature_engine_cannot_undo_current_pending_cancel_protection(inputs):
    root, root_manifest, root_sha, features, _, destination = inputs
    path=features/'src/simpeople/core/engine.py'
    code=path.read_text()
    guard="        if t.get('cancel_requested'):\n            # A second command ID is still the same pending cancellation.\n            # Preserve its original stop deadline and the owned SDK request.\n            return {**self.public(t),'cancellation':'accepted'}\n"
    assert code.count(guard)==1
    path.write_text(code.replace(guard,''));_, digest=manifest(features)
    builder.prepare(root,root_manifest,root_sha,features,digest,destination)
    assert "if t.get('cancel_requested'):" in (destination/'src/simpeople/core/engine.py').read_text()
    assert "if t.get('cancel_requested'):" not in path.read_text()
