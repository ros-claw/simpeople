"""Input freezing only: no Isaac startup or native acceptance is simulated."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize('profile', ['default', 'basic'])
def test_shared_idle_harness_is_frozen_even_for_older_runtime_source(tmp_path, profile):
    root = Path(__file__).parents[1]
    workspace = tmp_path / 'workspace'
    source = tmp_path / 'old-runtime'
    (workspace / 'scripts').mkdir(parents=True)
    (workspace / 'runs').mkdir()
    script = workspace / 'scripts/bench_native_runtime.py'
    shutil.copy2(root / 'scripts/bench_native_runtime.py', script)
    helpers = ['src/simpeople/core/workloads.py', 'src/simpeople/tools/runtime_contract.py',
               'src/simpeople/backends/native/probe_scenes.py', 'src/simpeople/backends/native/idle_profile.py',
               'src/simpeople/core/release_scene.py']
    for relative in helpers:
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)
    for directory in ['src', 'configs', 'schemas', 'reports']:
        (source / directory).mkdir(parents=True)
    (source / 'src/old_marker.py').write_text('old_runtime = True\n')
    (source / 'reports/capability_matrix.json').write_text('{}')
    case = tmp_path / 'case.json'
    case.write_text('{"case_id":"snapshot_prefix_only"}')
    code = '''
import importlib.abc,runpy,sys
class SDKBlocked(Exception):pass
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='isaacsim' or fullname.startswith(('omni.','carb.')):raise SDKBlocked(fullname)
sys.meta_path.insert(0,Fence())
script,source,case,profile=sys.argv[1:]
sys.argv=[script,'--source-root',source,'--case',case,'--run-id','prefix','--diagnostic-idle-tags',profile]
try:runpy.run_path(script,run_name='__main__')
except SDKBlocked:print('SDK_IMPORT_BLOCKED')
else:raise AssertionError('Expected the guarded SDK import')
'''
    result = subprocess.run([sys.executable, '-c', code, str(script), str(source), str(case), profile],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'SDK_IMPORT_BLOCKED' in result.stdout
    run = workspace / 'runs/prefix'
    snapshot = run / 'source_snapshot'
    assert {p.name for p in (snapshot / 'src').iterdir()} == {'old_marker.py'}
    manifest = json.loads((run / 'source_manifest.json').read_text())
    for relative in helpers:
        name = 'harness/' + Path(relative).name
        assert (snapshot / name).read_bytes() == (root / relative).read_bytes()
        assert manifest[name] == hashlib.sha256((root / relative).read_bytes()).hexdigest()
    assert json.loads((run / 'bootstrap.json').read_text())['diagnostic_idle_tags'] == profile
    assert not (run / 'completed.json').exists()
