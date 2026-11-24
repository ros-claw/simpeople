import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def test_candidate_extends_the_execution_fingerprint_and_invalidates_native_proof(tmp_path):
    canonical = load('prepare_canonical_stop_candidate')
    deferred = load('prepare_deferred_stop_candidate')
    base = ROOT/'reports/evidence/iteration_20261115_integrated_native/execution_source'
    parent = tmp_path/'parent'
    canonical.prepare(base, canonical.sha(base/'source_manifest.json'), parent)
    old = json.loads((parent/'source_manifest.json').read_text())
    target = tmp_path/'candidate'
    result = deferred.prepare(parent, deferred.sha(parent/'source_manifest.json'), target)
    new = json.loads((target/'source_manifest.json').read_text())
    assert set(new)-set(old) == {deferred.HELPER}
    assert set(result['changed_files']) == {
        deferred.HELPER, 'src/simpeople/backends/native/custom_stop.py',
        'src/simpeople/backends/native/adapter.py', 'src/simpeople/core/gesture_profiles.py',
        'configs/native_gesture_catalog.json'} - ({'src/simpeople/backends/native/custom_stop.py'}
        if old['src/simpeople/backends/native/custom_stop.py'] == new['src/simpeople/backends/native/custom_stop.py'] else set())
    assert all(deferred.sha(parent/n) == digest for n, digest in old.items())
    assert not result['production_source_installed'] and not result['previous_native_proof_transferred']
    assert result['qualified_generated_native_rigs'] == []
    for record in json.loads((target/'configs/native_gesture_catalog.json').read_text())['records']:
        assert record['status'] == 'discovered'
        for variant in record.get('startup_profiles', {}).values():
            assert variant['implementation_sha256'] == result['implementation_sha256']
            assert variant['status'] == 'discovered' and 'evidence_run' not in variant
    with pytest.raises(ValueError):
        deferred.prepare(parent, deferred.sha(parent/'source_manifest.json'), target)


def test_adapter_patch_rejects_unreviewed_or_already_patched_stop():
    module = load('prepare_deferred_stop_candidate')
    code = '            if needs_settlement(entry):\n                record={}'
    assert 'request(self,handle,entry,current,name,a)' in module.integrate_adapter(code)
    with pytest.raises(ValueError):
        module.integrate_adapter(module.integrate_adapter(code))
    with pytest.raises(ValueError):
        module.integrate_adapter('different stop implementation')
