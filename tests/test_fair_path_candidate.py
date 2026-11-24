import importlib.util
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
spec = importlib.util.spec_from_file_location('fair_path_builder', ROOT/'scripts/prepare_fair_path_candidate.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


@pytest.fixture
def inputs(tmp_path):
    archived = ROOT/'reports/evidence/iteration_20261115_integrated_native/execution_source'
    base = tmp_path/'base'; shutil.copytree(archived, base)
    return base, builder.sha(base/'source_manifest.json'), tmp_path/'candidate'


def test_staging_preserves_other_native_features_and_revokes_old_proof(inputs):
    base, expected, destination = inputs
    original = json.loads((base/'source_manifest.json').read_text())
    result = builder.prepare(*inputs)
    actual = json.loads((destination/'source_manifest.json').read_text())
    assert result['previous_proof_transferred'] is False and result['native_verified'] is False
    assert result['production_source_installed'] is False
    assert all(builder.sha(base/n) == h for n, h in original.items())
    assert all(builder.sha(destination/n) == h for n, h in actual.items())
    changed = set(result['changes'])
    assert all(actual[n] == h for n, h in original.items() if n not in changed)
    code = (destination/'src/simpeople/backends/native/reservations.py').read_text()
    assert 'local_yield_stop' in code and '_arrival_shortfall' in code
    assert "if rid in self.fair_gate.pending:self.fair_gate.waiting" in code
    assert "fair_path_edges_enabled',False" in code
    p = destination/'src/simpeople/core/runtime_policy.py'
    s = importlib.util.spec_from_file_location('staged_policy', p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    assert m.DEFAULT_POLICY['cycle_drainage_enabled'] is False
    assert m.DEFAULT_POLICY['fair_path_edges_enabled'] is False
    assert m.DEFAULT_POLICY['max_wait_sim_s'] == 30 and m.DEFAULT_POLICY['max_conflicting_bypasses'] == 0
    catalog = json.loads((destination/'configs/native_gesture_catalog.json').read_text())
    for record in catalog['records']:
        for row in [record, *record.get('startup_profiles', {}).values()]:
            assert row['status'] == 'discovered'
            assert not any(key in row for key in builder.clear_proof.__globals__['PROOF_FIELDS'])


def test_source_drift_and_wrong_manifest_refuse_to_create_candidate(inputs):
    base, expected, destination = inputs
    with pytest.raises(ValueError): builder.prepare(base, 'wrong', destination)
    assert not destination.exists()
    (base/'src/simpeople/core/engine.py').write_text('# changed\n')
    with pytest.raises(ValueError): builder.prepare(*inputs)
    assert not destination.exists()


def test_existing_candidate_is_never_overwritten(inputs):
    builder.prepare(*inputs)
    with pytest.raises(ValueError): builder.prepare(*inputs)


def test_integration_refuses_fuzzy_or_duplicate_hooks(inputs):
    base, _, _ = inputs
    code = (base/'src/simpeople/backends/native/reservations.py').read_text()
    new = builder.integrate_reservations(code)
    with pytest.raises(ValueError): builder.integrate_reservations(new)
    with pytest.raises(ValueError): builder.integrate_reservations(code.replace('blocked=self.grid.blocked', 'blocked = self.grid.blocked'))


def test_policy_preserves_existing_keys_and_refuses_duplicate_extension(inputs):
    base, _, _ = inputs
    code = (base/'src/simpeople/core/runtime_policy.py').read_text()
    new = builder.integrate_policy(code)
    with pytest.raises(ValueError): builder.integrate_policy(new)
