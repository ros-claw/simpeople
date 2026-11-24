"""Registration portability must not survive source or asset substitution."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('registration_audit', Path(__file__).resolve().parents[1] / 'scripts/audit_native_registration_repeat.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


@pytest.fixture
def registered(tmp_path):
    cache = tmp_path / 'assets/cache/candidate'
    cache.mkdir(parents=True)
    (cache / 'clip.usda').write_text('clip')
    (cache / 'rig.usda').write_text('rig')
    entry = {'clip': 'cache://candidate/clip.usda', 'skeleton': 'cache://candidate/rig.usda',
             'playback_mode': 'out_and_back'}
    runs = [tmp_path / 'first', tmp_path / 'second']
    for run in runs:
        snap = run / 'source_snapshot'
        for name in [*audit.SOURCE_CONTRACTS.values(), 'backends/native/custom_actions.py']:
            p = snap / 'src/simpeople' / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('# frozen ' + name)
        dump(snap / 'configs/custom_actions.json', {'registration_source': 'fixed_cache_uris', 'actions': {'reach': entry}})
        manifest = {str(p.relative_to(snap)): audit.sha(p) for p in snap.rglob('*') if p.is_file()}
        dump(run / 'source_manifest.json', manifest)
        proofs = {k: audit.sha(snap / 'src/simpeople' / v) for k, v in audit.SOURCE_CONTRACTS.items()}
        proofs.update(clip=audit.sha(cache / 'clip.usda'), skeleton=audit.sha(cache / 'rig.usda'),
                      imported_clip=audit.sha(cache / 'clip.usda'), registration=hashlib.sha256(
                          (snap / 'src/simpeople/backends/native/custom_actions.py').read_bytes()
                          + json.dumps(entry, sort_keys=True).encode()).hexdigest())
        dump(run / 'custom_actions/registry.json', {'reach': {**entry, 'status': 'discovered',
             'prim_paths': ['/World/Library/Reach'], 'source_sha256': proofs, 'runtime_revision': 'sdk'}})
        dump(run / 'actual_fixed_registration.json', {'reach': {'literal_clip': entry['clip'],
             'literal_skeleton': entry['skeleton'], 'resolved_clip': str(cache / 'clip.usda'),
             'resolved_skeleton': str(cache / 'rig.usda'), 'source_sha256': proofs}})
        dump(run / 'completed.json', {'harness_completed': True, 'registration_only': True,
                                     'native_animation_playback_tested': False})
    return tmp_path, runs


def mutate(path, fn):
    value = json.loads(path.read_text())
    fn(value)
    dump(path, value)


def test_actual_receipts_repeat_without_certifying_playback(registered):
    workspace, (a, b) = registered
    result = audit.audit(a, b, workspace)
    assert result['verified'] and result['registered_actions'] == 1
    assert not result['native_playback_verified']
    assert result['qualified_generated_native_rigs'] == []


@pytest.mark.parametrize('failure', ['asset', 'snapshot', 'receipt', 'omitted_hash', 'extra_hash',
                                    'rewritten_uri', 'runtime', 'closure', 'missing_action', 'same_run', 'unmanifested_source'])
def test_portability_corruption_is_refused(registered, failure):
    workspace, (a, b) = registered
    if failure == 'asset':
        (workspace / 'assets/cache/candidate/clip.usda').write_text('substituted')
    elif failure == 'snapshot':
        (b / 'source_snapshot/src/simpeople/core/engine.py').write_text('changed engine')
    elif failure == 'receipt':
        mutate(b / 'actual_fixed_registration.json', lambda x: x['reach']['source_sha256'].update(engine='0' * 64))
    elif failure in {'omitted_hash', 'extra_hash'}:
        for name in ['actual_fixed_registration.json', 'custom_actions/registry.json']:
            mutate(b / name, lambda x: x['reach']['source_sha256'].pop('custom_stop_contract') if failure == 'omitted_hash'
                   else x['reach']['source_sha256'].update(unknown='0' * 64))
    elif failure == 'rewritten_uri':
        mutate(b / 'custom_actions/registry.json', lambda x: x['reach'].update(clip='/run/source_snapshot/clip.usda'))
    elif failure == 'runtime':
        mutate(b / 'custom_actions/registry.json', lambda x: x['reach'].update(runtime_revision='different-sdk'))
    elif failure == 'closure':
        mutate(b / 'completed.json', lambda x: x.update(harness_completed=False))
    elif failure == 'missing_action':
        dump(b / 'actual_fixed_registration.json', {})
    elif failure == 'same_run':
        b = a
    elif failure == 'unmanifested_source':
        (b / 'source_snapshot/src/simpeople/core/extra.py').write_text('unrecorded runtime code')
    result = audit.audit(a, b, workspace)
    assert not result['verified'] and result['errors']
    assert result['native_playback_verified'] is False
