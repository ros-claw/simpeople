import ast
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('stop_candidate',ROOT/'scripts/prepare_canonical_stop_candidate.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
BASE=ROOT/'reports/evidence/iteration_20261115_integrated_native/execution_source'


def test_exact_stop_patch_includes_canonical_loops_and_retains_the_first_receipt(monkeypatch):
    original=(BASE/'src/simpeople/backends/native/adapter.py').read_text()
    code=builder.integrate_adapter(original);tree=ast.parse(code)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NativeBackend')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='stop')
    package=ModuleType('test_native_stop');package.__path__=[]
    gestures=ModuleType('test_native_stop.gestures');gestures.stop=lambda *_:None
    from simpeople.backends.native import custom_stop
    monkeypatch.setitem(sys.modules,'test_native_stop',package)
    monkeypatch.setitem(sys.modules,'test_native_stop.gestures',gestures)
    monkeypatch.setitem(sys.modules,'test_native_stop.custom_stop',custom_stop)
    scope={'__name__':'test_native_stop.adapter','__package__':'test_native_stop'}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'candidate_stop','exec'),scope)
    class Agent:
        def __init__(self):self.current=35;self.commands=[]
        def get_action_task_id(self):return self.current
        def get_task_name(self,tid):return 'canonical' if tid==35 else 'Idle'
        def cancel_task(self,tid):self.commands.append(('cancel',tid))
        def idle(self):self.commands.append(('idle',38));return 38
    a=Agent();events=[]
    b=SimpleNamespace(assert_thread=lambda:None,api=SimpleNamespace(get_agent=lambda _:a),
        custom_actions={'canonical':{'playback_mode':'loop','canonical_entry':{'world_pose':'reference'}}},
        instances={'actor':{}},timeline=SimpleNamespace(get_current_time=lambda:2.),
        on_event=lambda kind,**p:events.append((kind,p)))
    scope['stop'](b,'actor');record=copy.deepcopy(b.instances['actor']['custom_stop'])
    assert a.commands==[('cancel',35),('idle',38)]
    assert record['retired_native_task_id']==35 and record['idle_request_native_task_id']==38
    # The actual SDK slot may already show the pending Idle on a later call.
    a.current=38;scope['stop'](b,'actor')
    assert a.commands==[('cancel',35),('idle',38)]
    assert b.instances['actor']['custom_stop']==record and len(events)==1


def test_builder_preserves_base_and_does_not_transfer_any_native_qualification(tmp_path):
    before=json.loads((BASE/'source_manifest.json').read_text())
    destination=tmp_path/'candidate'
    result=builder.prepare(BASE,builder.sha(BASE/'source_manifest.json'),destination)
    assert not result['previous_native_proof_transferred'] and not result['production_source_installed']
    assert result['qualified_generated_native_rigs']==[]
    assert (destination/'src/simpeople/backends/native/custom_stop.py').read_bytes()==(ROOT/'src/simpeople/backends/native/custom_stop.py').read_bytes()
    catalog=json.loads((destination/'configs/native_gesture_catalog.json').read_text())
    for r in catalog['records']:
        assert r['status']=='discovered'
        for v in r['startup_profiles'].values():
            assert v['status']=='discovered' and v['implementation_sha256']==result['implementation_sha256']
            assert 'evidence_run' not in v and 'replay_audit_sha256' not in v
    assert all(builder.sha(BASE/n)==h for n,h in before.items())
    with pytest.raises(ValueError):builder.prepare(BASE,builder.sha(BASE/'source_manifest.json'),destination)


@pytest.mark.parametrize('function,name',[(builder.integrate_adapter,'backends/native/adapter.py'),
                                         (builder.integrate_engine,'core/engine.py')])
def test_integration_refuses_to_apply_twice_or_to_unreviewed_text(function,name):
    code=(BASE/'src/simpeople'/name).read_text()
    with pytest.raises(ValueError):function(function(code))
    with pytest.raises(ValueError):function('# unrelated implementation\n')


def test_bad_base_manifest_is_rejected_before_copy(tmp_path):
    with pytest.raises(ValueError,match='manifest changed'):
        builder.prepare(BASE,'wrong',tmp_path/'candidate')
    assert not (tmp_path/'candidate').exists()
