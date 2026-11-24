"""Packaging omission is not permission to omit execution inputs."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest


spec=importlib.util.spec_from_file_location('gesture_snapshot',Path(__file__).parents[1]/'scripts/audit_gesture_source_snapshot.py')
checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def fixture(tmp_path):
    source=tmp_path/'source';run=tmp_path/'run';snap=run/'source_snapshot';source.mkdir();snap.mkdir(parents=True)
    for name in ['src/simpeople/core/gestures.py','configs/profile.json','schemas/protocol.json',
                 'reports/capability_matrix.json',*checker.PACKAGING_METADATA]:
        f=source/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text('# fixture\n')
    manifest={str(f.relative_to(source)):sha(f) for f in source.rglob('*') if f.is_file()}
    (source/'source_manifest.json').write_text(json.dumps(manifest))
    for name in manifest:
        if name not in checker.PACKAGING_METADATA:
            dest=snap/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/name,dest)
    probe=tmp_path/'probe.py';probe.write_text("shutil.ignore_patterns('__pycache__','*.pyc','*.egg-info')\n")
    shutil.copy2(probe,snap/probe.name)
    actual={str(f.relative_to(snap)):sha(f) for f in snap.rglob('*') if f.is_file()}
    (run/'source_manifest.json').write_text(json.dumps(actual))
    return source,run,probe


def review(fixture):
    source,run,probe=fixture
    return checker.audit(source,run,sha(source/'source_manifest.json'),probe,sha(probe))


def test_exact_omitted_distribution_files_are_reported_without_animation_credit(fixture):
    result=review(fixture)
    assert result['execution_source_verified'] and len(result['omitted_packaging_metadata'])==6
    assert result['native_gesture_verified'] is False


@pytest.mark.parametrize('name',['src/simpeople/core/gestures.py','configs/profile.json','schemas/protocol.json','reports/capability_matrix.json'])
def test_missing_execution_inputs_are_never_exempt(fixture,name):
    source,run,probe=fixture;m=json.loads((run/'source_manifest.json').read_text());m.pop(name)
    (run/'source_manifest.json').write_text(json.dumps(m));(run/'source_snapshot'/name).unlink()
    assert not review(fixture)['execution_source_verified']


@pytest.mark.parametrize('fault',['candidate_mutation','snapshot_mutation','probe_mutation','unknown_egg_code','no_ignored_metadata','extra_python','path_escape'])
def test_hash_drift_unknown_omissions_and_scope_lies_fail(fixture,fault):
    source,run,probe=fixture
    if fault=='candidate_mutation':(source/'configs/profile.json').write_text('changed')
    elif fault=='snapshot_mutation':(run/'source_snapshot/configs/profile.json').write_text('changed')
    elif fault=='probe_mutation':probe.write_text('changed')
    elif fault=='unknown_egg_code':
        name='src/rosclaw_simpeople.egg-info/executable.py';p=source/name;p.write_text('raise RuntimeError()')
        m=json.loads((source/'source_manifest.json').read_text());m[name]=sha(p);(source/'source_manifest.json').write_text(json.dumps(m))
    elif fault=='no_ignored_metadata':
        probe.write_text('pass\n');shutil.copy2(probe,run/'source_snapshot/probe.py');m=json.loads((run/'source_manifest.json').read_text());m['probe.py']=sha(probe);(run/'source_manifest.json').write_text(json.dumps(m))
    elif fault=='extra_python':(run/'source_snapshot/injected.py').write_text('pass')
    else:
        m=json.loads((source/'source_manifest.json').read_text());m['../probe.py']=sha(probe);(source/'source_manifest.json').write_text(json.dumps(m))
    assert not review(fixture)['execution_source_verified']
