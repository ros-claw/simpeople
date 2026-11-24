"""Execute the candidate's real adapter methods and stop gate without Kit."""
import ast,copy,importlib.util,sys
from pathlib import Path
from types import ModuleType,SimpleNamespace
import pytest
R=Path(__file__).resolve().parents[1];S=R
spec=importlib.util.spec_from_file_location('finite_test_helpers',R/'tests/test_cooperative_finite_stop.py');t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
from simpeople.backends.native import custom_stop as gate
def methods(monkeypatch):
 stub=ModuleType('simpeople.backends.native.gestures');stub.stop=lambda *_:None;monkeypatch.setitem(sys.modules,stub.__name__,stub)
 cls=next(n for n in ast.parse((S/'src/simpeople/backends/native/adapter.py').read_text()).body if isinstance(n,ast.ClassDef)and n.name=='NativeBackend');nodes=[n for n in cls.body if isinstance(n,ast.FunctionDef)and n.name in {'start','stop'}];scope={'__package__':'simpeople.backends.native','SimPeopleError':t.SimPeopleError,'bh':SimpleNamespace(BEHAVIOR_TASK_ID_INVALID=-1)};exec(compile(ast.Module(body=nodes,type_ignores=[]),str(S/'src/simpeople/backends/native/adapter.py'),'exec'),scope);return scope
@pytest.fixture
def b(monkeypatch):
 b=t.Backend();b.agent=lambda h:b.agent_obj;b.canonical_entry_quality=lambda *_:dict(passed=True);monkeypatch.setattr(t.m,'capture',lambda backend,*_:copy.deepcopy(backend.pose));return b

def test_actual_adapter_validates_before_sdk_and_registers_positive_receipt(b,tmp_path,monkeypatch):
 t.entry(b,tmp_path);a=b.agent_obj;a.get_custom_action_names=lambda:['finite']
 def issue(name,duration):a.commands.append(('custom',name,duration));a.states[6]='running';a.names[6]=name;return 6
 a.custom_action=issue;assert methods(monkeypatch)['start'](b,'a',dict(action='custom_action',target='finite',duration_s=.2))==6
 assert b.instances['a']['owned_finite_cycle']['native_task_id']==6 and 6 in b.instances['a']['engine_native_ids'] and a.commands==[('custom','finite',.2)]

@pytest.mark.parametrize('fault',['asset','cliphash','duration','bound'])
def test_actual_start_rejects_bad_contract_before_command(b,tmp_path,monkeypatch,fault):
 e=t.entry(b,tmp_path);b.agent_obj.get_custom_action_names=lambda:['finite'];b.agent_obj.custom_action=lambda *_,**__:pytest.fail('Native command before validation')
 if fault=='asset':e['canonical_entry']['source_asset_sha256']='other'
 elif fault=='cliphash':e['source_sha256']['clip']='wrong'
 elif fault=='duration':e['requested_native_duration_s']=1.
 elif fault=='bound':e['frame_count']=1000
 with pytest.raises(t.SimPeopleError):methods(monkeypatch)['start'](b,'a',dict(action='custom_action',target='finite',duration_s=.2))

def test_actual_stop_waits_natural_end_and_real_gate_then_preserves_repeat(b,monkeypatch):
 b.custom_actions={'finite':{'canonical_entry':{'nonempty':True}}};stop=methods(monkeypatch)['stop'];stop(b,'a');record=copy.deepcopy(b.instances['a']['custom_stop']);assert not b.agent_obj.commands
 for i in range(30):b.now+=1/30;assert not gate.ready(b,'a',b.observe('a'),True)
 stop(b,'a');assert b.instances['a']['custom_stop']==record
 b.agent_obj.states[5]='succeeded';b.agent_obj.current=0
 for i in range(4):b.now+=1/30;assert not gate.ready(b,'a',b.observe('a'),True)
 assert b.agent_obj.commands==[('idle',)];b.agent_obj.current=9
 for i in range(16):b.now+=1/30;assert gate.ready(b,'a',b.observe('a'),True)==(i==15)

def test_actual_stop_queued_cancels_old_slot_and_observes_owned_idle(b,monkeypatch):
 b.custom_actions={};b.agent_obj.current=3;stop=methods(monkeypatch)['stop'];stop(b,'a');assert b.agent_obj.commands==[('cancel',5),('idle',)];stop(b,'a');assert len(b.agent_obj.commands)==2
 b.agent_obj.current=9
 for i in range(16):b.now+=1/30;assert gate.ready(b,'a',b.observe('a'),True)==(i==15)



def test_same_clock_submission_refreshes_old_task_observation(b,monkeypatch):
 old=b.observe('a');old['native_task_id']=3;old['action']='Idle';b.observations={'a':(b.now,old)};b.observation_frame_ids={'a':12};fresh=b.observe
 b.observe=lambda h: b.observations[h][1] if h in b.observations else fresh(h)
 t.m.register(b,'a',5,b.spec)
 assert 'a' not in b.observations and 'a' not in b.observation_frame_ids
 assert t.m.request(b,'a',5,'finite',b.agent_obj) and not b.agent_obj.commands
 assert b.instances['a']['custom_stop']['cooperative_finite_stop'] and not b.instances['a']['custom_stop']['queued_cancelled']


def test_prior_clock_position_history_is_preserved(b):
 old={'native_task_id':3};b.observations={'a':(b.now-1/30,old)};b.observation_frame_ids={'a':12};t.m.register(b,'a',5,b.spec)
 assert b.observations['a']==(b.now-1/30,old) and b.observation_frame_ids['a']==12


def test_already_current_task_observation_is_preserved(b):
 old=b.observe('a');b.observations={'a':(b.now,old)};b.observation_frame_ids={'a':12};t.m.register(b,'a',5,b.spec)
 assert b.observations['a'][1] is old and b.observation_frame_ids['a']==12
