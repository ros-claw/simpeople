"""Freeze an explicit handoff/source without loading Kit or changing evidence."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


def test_room_discovery_freezes_exact_source_and_handoff_before_sdk(tmp_path):
    source=tmp_path/'source';workspace=tmp_path/'workspace'
    for name in ['src','configs','schemas','reports']:(source/name).mkdir(parents=True)
    (workspace/'runs').mkdir(parents=True)
    (source/'src/marker.py').write_text('selected_source=True\n')
    catalog={'records':[{'status':'discovered','max_hold_duration_s':.6}]}
    (source/'configs/native_gesture_catalog.json').write_text(json.dumps(catalog))
    (source/'reports/capability_matrix.json').write_text('{}')
    handoff=tmp_path/'explicit_handoff.json';handoff.write_text('{"scene_id":"selected-room"}')
    code='''
import importlib.abc,runpy,sys
class Blocked(Exception):pass
class Fence(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname in {'isaacsim','omni','carb'} or fullname.startswith(('omni.','carb.')):raise Blocked(fullname)
sys.meta_path.insert(0,Fence())
script,workspace,source,handoff=sys.argv[1:]
sys.argv=[script,'--run-id','room','--workspace-root',workspace,'--source-root',source,
 '--handoff',handoff,'--layout','room','--gestures','--discovery','--startup-profile','product-default']
try:runpy.run_path(script,run_name='__main__')
except Blocked:print('SDK_BLOCKED')
else:raise AssertionError('SDK import was not attempted')
'''
    script=Path(__file__).parents[1]/'scripts/probe_interactions_native.py'
    result=subprocess.run([sys.executable,'-c',code,str(script),str(workspace),str(source),str(handoff)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert 'SDK_BLOCKED' in result.stdout
    out=workspace/'runs/room';snap=out/'source_snapshot'
    manifest=json.loads((out/'source_manifest.json').read_text())
    assert (snap/'src/marker.py').read_bytes()==(source/'src/marker.py').read_bytes()
    assert (snap/'harness/interaction_room_handoff.json').read_bytes()==handoff.read_bytes()
    assert json.loads((snap/'configs/native_gesture_catalog.json').read_text())==catalog
    for name,digest in manifest.items():assert hashlib.sha256((snap/name).read_bytes()).hexdigest()==digest
    assert not (out/'completed.json').exists() and not (out/'bound_gesture_acceptance.json').exists()


@pytest.mark.parametrize('flags,reason',[(['--discovery'],'discovery requires room layout and gestures'),
                                       (['--handoff','x.json'],'handoff requires room layout')])
def test_ambiguous_probe_mode_rejected_before_any_run(tmp_path,flags,reason):
    script=Path(__file__).parents[1]/'scripts/probe_interactions_native.py'
    result=subprocess.run([sys.executable,str(script),'--run-id','bad','--workspace-root',str(tmp_path),*flags],capture_output=True,text=True,timeout=30)
    assert result.returncode==2 and reason in result.stderr
    assert not (tmp_path/'runs/bad').exists()
