import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
spec = importlib.util.spec_from_file_location('preload_source_audit', ROOT/'scripts/audit_preload_source_snapshot.py')
reader = importlib.util.module_from_spec(spec); spec.loader.exec_module(reader)


def freeze(folder, path):
    data = {str(p.relative_to(folder)): reader.sha(p) for p in folder.rglob('*')
            if p.is_file() and p != path}
    path.write_text(json.dumps(data)); return reader.sha(path)


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path/'source'; clips = tmp_path/'clips'; run = tmp_path/'run'
    for folder in [source, clips, run]: folder.mkdir()
    for name, value in {'src/simpeople/core/engine.py': '# actual engine\n',
                        'configs/custom_actions.json': '{"actions": {}}\n',
                        'configs/custom_action_acceptance.json': '{"old":true}\n',
                        'reports/capability_matrix.json': '{}\n',
                        'schemas/activity.schema.json': '{}\n',
                        'scripts/unused.py': '# not executed\n'}.items():
        p = source/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)
    for name in reader.PACKAGING_METADATA:
        p = source/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('packaging\n')
    source_sha = freeze(source, source/'source_manifest.json')
    registry = {'actions': {'candidate': {'clip': 'cache://candidate.usda'}}}
    (clips/'actions.json').write_text(json.dumps(registry, indent=2)+'\n')
    (clips/'candidate.usda').write_text('#usda 1.0\n')
    clip_manifest = tmp_path/'clip_manifest.json'; clip_sha = freeze(clips, clip_manifest)
    probe = tmp_path/'probe.py'; probe.write_text("import shutil\nshutil.ignore_patterns('__pycache__', '*.egg-info')\n")
    snap = run/'source_snapshot'; snap.mkdir()
    for name in ['src/simpeople', 'configs', 'schemas', 'reports']:
        shutil.copytree(source/name, snap/name)
    shutil.copy2(probe, snap/probe.name); shutil.copytree(clips, snap/'inputs')
    (snap/'configs/custom_actions.json').write_text(json.dumps(registry, indent=2)+'\n')
    (snap/'configs/custom_action_acceptance.json').write_text('{}\n')
    freeze(snap, run/'source_manifest.json')
    return source, run, source_sha, probe, reader.sha(probe), clips, clip_manifest, clip_sha


def test_exact_preload_snapshot_accepts_only_the_two_explicit_replacements(inputs):
    result = reader.audit(*inputs)
    assert result['execution_source_verified'] and not result['errors']
    assert len(result['omitted_packaging_metadata']) == 6
    assert result['native_motion_verified'] is False


@pytest.mark.parametrize('fault', ['source', 'source_manifest', 'probe', 'clip', 'clip_manifest',
                                  'snapshot_code', 'config', 'registry', 'extra_code',
                                  'extra_config', 'unlisted_code', 'snapshot_clip', 'missing_metadata'])
def test_source_or_input_drift_never_inherits_an_execution_certificate(inputs, fault):
    source, run, _, probe, _, clips, clip_manifest, _ = inputs
    snap = run/'source_snapshot'
    target = {'source': source/'src/simpeople/core/engine.py',
              'source_manifest': source/'source_manifest.json',
              'probe': probe, 'clip': clips/'candidate.usda', 'clip_manifest': clip_manifest,
              'snapshot_code': snap/'src/simpeople/core/engine.py',
              'config': snap/'configs/custom_action_acceptance.json',
              'registry': snap/'configs/custom_actions.json',
              'extra_code': snap/'src/simpeople/extra.py',
              'extra_config': snap/'configs/extra.json',
              'unlisted_code': snap/'src/simpeople/unlisted.py',
              'snapshot_clip': snap/'inputs/candidate.usda',
              'missing_metadata': snap/'schemas/activity.schema.json'}[fault]
    target.write_text('# mutated\n')
    # Rehash an actual snapshot too: a self-consistent foreign snapshot still
    # must not pass comparison against frozen source/inputs.
    if fault in {'snapshot_code', 'config', 'registry', 'extra_code', 'extra_config', 'snapshot_clip'}:
        freeze(snap, run/'source_manifest.json')
    if fault == 'missing_metadata':
        target.unlink(); freeze(snap, run/'source_manifest.json')
    result = reader.audit(*inputs)
    assert not result['execution_source_verified'] and result['errors']


@pytest.mark.parametrize('name', ['../escape.py', '/absolute.py', 'inputs/../escape.py', 'a//b.py'])
def test_canonical_paths_are_required(tmp_path, name):
    with pytest.raises(ValueError):
        reader.file_at(tmp_path, name)
