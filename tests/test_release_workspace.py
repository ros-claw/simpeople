"""Frozen harness filesystem tests; SDK imports are explicitly forbidden."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_runtime_release_version import SCRIPTS, execute, jobs, prepare, validate_workspace


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / 'real'
    for name in ['src', 'configs', 'schemas', 'scripts', 'reports', 'assets', 'runs']:
        (root / name).mkdir(parents=True, exist_ok=True)
    for name in SCRIPTS:
        shutil.copy2(ROOT / 'scripts' / name, root / 'scripts' / name)
    for name in ['core/workloads.py', 'tools/runtime_contract.py', 'backends/native/probe_scenes.py', 'backends/native/idle_profile.py', 'core/release_scene.py']:
        relative = Path('src/simpeople') / name
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    (root / 'reports/capability_matrix.json').write_text('{}')
    matrix = tmp_path / 'inputs'
    matrix.mkdir()
    rows = []
    for n in range(18):
        name = 'offline_' + str(n)
        f = matrix / (name + '.json')
        f.write_text(json.dumps({'case_id': name}))
        rows.append({'case_id': name, 'file_sha256': hashlib.sha256(f.read_bytes()).hexdigest()})
    (matrix / 'matrix_manifest.json').write_text(json.dumps({'cases': rows}))
    frozen = prepare(root, tmp_path / 'shared', matrix)
    source = tmp_path / 'original-source'
    for name in ['src', 'configs', 'schemas', 'reports']:
        (source / name).mkdir(parents=True, exist_ok=True)
    (source / 'src/old_marker.py').write_text('original_runtime = True\n')
    (source / 'reports/capability_matrix.json').write_text('{}')
    (source / 'source_manifest.json').write_text(json.dumps({str(f.relative_to(source)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in source.rglob('*') if f.is_file()}))
    return root, frozen, source


def test_root_edits_do_not_change_shared_harness_and_frozen_tampering_is_detected(fixture):
    root, frozen, source = fixture
    validate_workspace(frozen)
    path = Path('src/simpeople/backends/native/idle_profile.py')
    original = (frozen / path).read_bytes()
    (root / path).write_text('development tree changed\n')
    validate_workspace(frozen)
    assert (frozen / path).read_bytes() == original
    assert (frozen / 'runs').resolve() == root / 'runs'
    assert (frozen / 'assets').resolve() == root / 'assets'
    (frozen / path).write_text('changed frozen helper\n')
    with pytest.raises(AssertionError, match='frozen source changed'):
        validate_workspace(frozen)


def test_case_selection_does_not_silently_expand_or_duplicate_a_partial_run(fixture):
    root, frozen, source = fixture
    all_jobs = jobs(frozen, source, 'offline', 'default', None, 3, 8898)
    one = jobs(frozen, source, 'offline', 'default', ['offline_7'], 3, 8898)
    assert len(all_jobs) == 18 and one == [all_jobs[7]]
    assert len({j['run_id'] for j in all_jobs}) == 18
    for ids in [['offline_7', 'offline_7'], ['unknown']]:
        with pytest.raises(AssertionError, match='unknown or duplicate'):
            jobs(frozen, source, 'offline', 'default', ids, 3, 8898)


def test_shared_native_prefix_uses_original_source_and_frozen_helpers(fixture, tmp_path):
    root, frozen, source = fixture
    code = '''
import importlib.abc,runpy,sys
class SDKBlocked(Exception):pass
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='isaacsim' or fullname.startswith(('omni.','carb.')):raise SDKBlocked(fullname)
sys.meta_path.insert(0,Fence())
script,source,case=sys.argv[1:]
sys.argv=[script,'--source-root',source,'--case',case,'--run-id','offline-prefix']
try:runpy.run_path(script,run_name='__main__')
except SDKBlocked:print('SDK_IMPORT_BLOCKED')
else:raise AssertionError('Expected a blocked SDK import')
'''
    result = subprocess.run([sys.executable, '-c', code, str(frozen / 'scripts/bench_native_runtime.py'),
                             str(source), str(frozen / 'inputs/offline_0.json')],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0 and 'SDK_IMPORT_BLOCKED' in result.stdout, result.stderr
    run = root / 'runs/offline-prefix'
    snap = run / 'source_snapshot'
    assert (snap / 'src/old_marker.py').read_bytes() == (source / 'src/old_marker.py').read_bytes()
    assert len(list((snap / 'src').rglob('*'))) == 1
    assert (snap / 'harness/idle_profile.py').read_bytes() == (frozen / 'src/simpeople/backends/native/idle_profile.py').read_bytes()
    assert (snap / 'bench_native_runtime.py').read_bytes() == (ROOT / 'scripts/bench_native_runtime.py').read_bytes()
    assert not (run / 'completed.json').exists()


def test_failed_fixture_prevents_any_native_launch(fixture, tmp_path, monkeypatch):
    root, frozen, source = fixture
    proof = tmp_path / 'fixture'
    proof.mkdir()
    (proof / 'completed.json').write_text(json.dumps({'passed': False, 'cases_checked': 18}))
    def forbidden(*args, **kwargs):
        raise AssertionError('unexpected native launch')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    with pytest.raises(AssertionError, match='static fixture preflight has not passed'):
        execute(frozen, source, 'offline', 'default', None, 3, 8898, proof, tmp_path / 'state.json')
    assert not (tmp_path / 'state.json').exists()
