"""Exercise the real probe's snapshot prefix while blocking every Kit startup."""
import json
from pathlib import Path
import subprocess
import sys


def test_probe_uses_frozen_source_and_explicit_workspace_before_sdk_import(tmp_path):
    root=Path(__file__).parents[1];source=tmp_path/'frozen';workspace=tmp_path/'workspace';clips=tmp_path/'clips'
    for name in ['src','configs','schemas','reports']:(source/name).mkdir(parents=True)
    (source/'src/frozen_marker.py').write_text('frozen_source = True\n')
    (source/'reports/capability_matrix.json').write_text('{"frozen_marker":true}')
    (workspace/'runs').mkdir(parents=True);clips.mkdir()
    (clips/'actions.json').write_text('{"actions":{"fixture":{"clip":"old","skeleton":"fixture"}}}')
    code='''
import importlib.abc,runpy,sys
class SDKBlocked(Exception):pass
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='isaacsim' or fullname.startswith(('omni.','carb.')):raise SDKBlocked(fullname)
assert 'isaacsim' not in sys.modules
sys.meta_path.insert(0,Fence())
script,workspace,source,clips=sys.argv[1:]
sys.argv=[script,'--workspace-root',workspace,'--source-root',source,'--clip-dir',clips,'--run-id','prefix-only','--diagnostic-response-profile','fixed30','--diagnostic-seed','42']
try:runpy.run_path(script,run_name='__main__')
except SDKBlocked:print('SDK_IMPORT_BLOCKED_BEFORE_STARTUP')
else:raise AssertionError('Probe did not reach the guarded SDK import')
'''
    result=subprocess.run([sys.executable,'-c',code,str(root/'scripts/probe_generated_native.py'),str(workspace),str(source),str(clips)],text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert 'SDK_IMPORT_BLOCKED_BEFORE_STARTUP' in result.stdout
    run=workspace/'runs/prefix-only';snapshot=run/'source_snapshot'
    assert (snapshot/'src/frozen_marker.py').read_bytes()==(source/'src/frozen_marker.py').read_bytes()
    assert {p.name for p in (snapshot/'src').iterdir()}=={'frozen_marker.py'}
    assert json.loads((snapshot/'reports/capability_matrix.json').read_text())=={'frozen_marker':True}
    config=json.loads((run/'probe_config.json').read_text())
    assert config['source_root']==str(source) and config['workspace_root']==str(workspace)
    registry=json.loads((snapshot/'configs/custom_actions.json').read_text())
    assert registry['actions']['fixture']['clip']==str(snapshot/'inputs/fixture.usda')
    assert not (run/'completed.json').exists() and not (run/'generated_native_acceptance.json').exists()
