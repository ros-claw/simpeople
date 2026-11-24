"""Exercise frozen gesture inputs without starting or importing the SDK."""
import json
from pathlib import Path
import subprocess
import sys


def test_experimental_gesture_probe_freezes_explicit_source_before_sdk(tmp_path):
    root = Path(__file__).parents[1]
    source = tmp_path / 'frozen'; workspace = tmp_path / 'workspace'
    for name in ['src', 'configs', 'schemas', 'reports']:
        (source / name).mkdir(parents=True)
    (workspace / 'runs').mkdir(parents=True)
    (source / 'src/marker.py').write_text('frozen = True\n')
    (source / 'configs/native_gesture_catalog.json').write_text(
        '{"records":[{"status":"verified","max_hold_duration_s":0.6}]}')
    (source / 'reports/capability_matrix.json').write_text('{"frozen":true}')
    code = '''
import importlib.abc,runpy,sys
class SDKBlocked(Exception):pass
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname in {'isaacsim','omni','carb'} or fullname.startswith(('omni.','carb.')):raise SDKBlocked(fullname)
sys.meta_path.insert(0,Fence())
script,workspace,source=sys.argv[1:]
sys.argv=[script,'--workspace-root',workspace,'--source-root',source,'--run-id','prefix',
 '--experimental-hold','--hold-seconds','2','--diagnostic-idle-tags','basic',
 '--diagnostic-response-profile','fixed30','--diagnostic-seed','42']
try:runpy.run_path(script,run_name='__main__')
except SDKBlocked:print('SDK_IMPORT_BLOCKED')
else:raise AssertionError('No SDK import attempted')
'''
    result = subprocess.run([sys.executable, '-c', code,
                             str(root / 'scripts/probe_gesture_runtime.py'),
                             str(workspace), str(source)],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'SDK_IMPORT_BLOCKED' in result.stdout
    run = workspace / 'runs/prefix'; snapshot = run / 'source_snapshot'
    assert (snapshot / 'src/marker.py').read_text() == 'frozen = True\n'
    assert len(list((snapshot / 'src').iterdir())) == 1
    row = json.loads((snapshot / 'configs/native_gesture_catalog.json').read_text())['records'][0]
    assert row['status'] == 'discovered' and row['max_hold_duration_s'] == 2
    assert json.loads((source / 'configs/native_gesture_catalog.json').read_text())['records'][0]['status'] == 'verified'
    assert not (run / 'completed.json').exists()


def test_nondefault_sdk_settings_cannot_use_strict_qualification(tmp_path):
    root = Path(__file__).parents[1]
    result = subprocess.run([sys.executable, str(root / 'scripts/probe_gesture_runtime.py'),
                             '--workspace-root', str(tmp_path), '--run-id', 'not-created',
                             '--strict', '--diagnostic-idle-tags', 'basic'],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 2
    assert 'require experimental hold mode' in result.stderr
    assert not (tmp_path / 'runs/not-created').exists()
