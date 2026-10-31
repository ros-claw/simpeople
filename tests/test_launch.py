"""An SDK process that exits zero must not hide native failure or missing output."""
import json
from types import SimpleNamespace
import pytest
from simpeople.tools.launch import resolve_run_exit_code,run_logged

@pytest.mark.parametrize('launcher,metrics,completion,error,expected',[
    (0,0,0,False,0),(0,4,4,False,4),(0,1,0,False,1),
    (139,0,0,False,139),(0,None,0,False,1),(0,0,0,True,1)])
def test_native_exit_status_contract(tmp_path,launcher,metrics,completion,error,expected):
    if metrics is not None:(tmp_path/'metrics.json').write_text(json.dumps({'exit_code':metrics}))
    (tmp_path/'completion.json').write_text(json.dumps({'exit_code':completion}))
    if error:(tmp_path/'error.txt').write_text('native error retained')
    assert resolve_run_exit_code(tmp_path,launcher)==expected

def test_logged_launch_propagates_a_failure_swallowed_by_kit(monkeypatch,tmp_path):
    def start(*args,**kwargs):
        run=tmp_path/'runs'/'test-failed';run.mkdir(parents=True)
        (run/'metrics.json').write_text('{"exit_code": 4}')
        (run/'completion.json').write_text('{"exit_code": 4}')
        return SimpleNamespace(stdout=iter([]),wait=lambda:0,poll=lambda:0,pid=123)
    monkeypatch.setattr('simpeople.tools.launch.subprocess.Popen',start)
    assert run_logged(['test-sdk'],tmp_path,'test-failed')==4
    assert (tmp_path/'runs/test-failed/kit.log').exists()
