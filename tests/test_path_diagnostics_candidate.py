import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('path_candidate',ROOT/'scripts/prepare_path_diagnostics_candidate.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)


def test_historical_builder_keeps_its_exact_diagnostic_patch():
    original=ROOT/'reports/evidence/iteration_20261114_baseline_cancel_followup/implementation/src/simpeople/backends/native/reservations.py'
    # Pin the diagnostic-only source as it stood before later planner changes.
    # This historical builder must not silently import new scheduling behavior.
    assert hashlib.sha256(builder.integrate(original.read_text()).encode()).hexdigest()=='2e04f08f504fd1ffe6718f65347c1f50158b43fac0bbe760356bc50a84887975'
    with pytest.raises(ValueError):builder.integrate(builder.integrate(original.read_text()))
    with pytest.raises(ValueError):builder.integrate(original.read_text().replace('start=next(', 'start=changed('))


@pytest.fixture
def base(tmp_path):
    archived=ROOT/'reports/evidence/iteration_20261115_arrival_recovery/private_source'
    profile=archived/'src/simpeople/core/gesture_profiles.py';tree=ast.parse(profile.read_text())
    assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='IMPLEMENTATION_FILES' for t in n.targets))
    files=ast.literal_eval(assignment.value);assert len(files)==15
    folder=tmp_path/'base';names=[]
    for name in files:
        relative='src/simpeople/'+name;source=archived/relative
        if not source.exists():source=ROOT/relative
        target=folder/relative;target.parent.mkdir(parents=True,exist_ok=True)
        # Private-only dependencies are digest inputs in this CPU builder
        # fixture, never imported or presented as a real Native source.
        target.write_bytes(source.read_bytes() if source.exists() else ('# fixture-only dependency: '+name+'\n').encode())
        names.append(relative)
    relative='configs/native_gesture_catalog.json';target=folder/relative;target.parent.mkdir(parents=True)
    target.write_text(json.dumps({'records':[{'status':'verified','evidence_run':'stale',
        'startup_profiles':{'basic':{'status':'verified','evidence_run':'stale','evidence_sha256':'old','replay_audit_sha256':'old'}}}]}));names.append(relative)
    manifest={name:builder.sha(folder/name) for name in names};(folder/'source_manifest.json').write_text(json.dumps(manifest))
    return folder,manifest


def test_candidate_preserves_original_bytes_and_removes_inherited_qualification(base,tmp_path):
    folder,manifest=base;dest=tmp_path/'new';result=builder.prepare(folder,builder.sha(folder/'source_manifest.json'),dest)
    assert result['source_file_count']==len(manifest)+1 and len(result['implementation_files'])==16
    assert result['previous_native_proof_transferred'] is False and result['qualified_generated_native_rigs']==[]
    for name,digest in manifest.items():assert builder.sha(folder/name)==digest
    actual=json.loads((dest/'source_manifest.json').read_text())
    for name,digest in actual.items():assert builder.sha(dest/name)==digest
    record=json.loads((dest/'configs/native_gesture_catalog.json').read_text())['records'][0]
    assert record['status']=='discovered' and 'evidence_run' not in record
    variant=record['startup_profiles']['basic'];assert variant['status']=='discovered'
    assert not {'evidence_run','evidence_sha256','replay_audit_sha256'} & set(variant)
    assert variant['implementation_sha256']==result['implementation_sha256']
    with pytest.raises(ValueError):builder.prepare(folder,builder.sha(folder/'source_manifest.json'),dest)


def test_mutated_frozen_source_is_rejected_before_copy(base,tmp_path):
    folder,manifest=base;digest=builder.sha(folder/'source_manifest.json');name=next(iter(manifest))
    (folder/name).write_text('changed after freeze')
    with pytest.raises(ValueError):builder.prepare(folder,digest,tmp_path/'new')
    assert not (tmp_path/'new').exists()
