"""SDK boundary invariants with a fake transport; no animation claims."""
import importlib.util
from pathlib import Path
from types import ModuleType,SimpleNamespace
import sys
import pytest


@pytest.fixture
def native(monkeypatch):
    for name in ['carb','omni','omni.anim','omni.anim.behavior','omni.anim.behavior.core']:
        module=ModuleType(name);monkeypatch.setitem(sys.modules,name,module)
        if '.' in name:
            parent,child=name.rsplit('.',1);setattr(sys.modules[parent],child,module)
    spec=importlib.util.spec_from_file_location('gesture_boundary_test',Path(__file__).resolve().parents[1]/'src/simpeople/backends/native/gestures.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_sampling_activation_keeps_velocity_in_the_cache_for_repeated_same_frame_reads(native):
    class Backend:
        def __init__(self):
            self.instances={'actor':{}};self.observation_frame_ids={}
            self.cached={'ready':True,'speed_mps':.7,'planar_speed_mps':.7,'velocity_mps':[.7,0,0]};self.samples=0
        def observe(self,handle):
            if self.instances[handle].get('gesture_sampling') and self.samples==0:
                self.samples+=1;self.cached={'ready':True,'speed_mps':0,'planar_speed_mps':0,'velocity_mps':[0,0,0]}
            return self.cached
    backend=Backend()
    assert native.observe(backend,'actor')['speed_mps']==.7
    assert native.observe(backend,'actor')['speed_mps']==.7
    assert backend.cached['velocity_mps']==[.7,0,0]


def test_stale_native_stop_id_cannot_cancel_a_new_owned_gesture(native):
    cancelled=[]
    backend=SimpleNamespace(instances={'actor':{'gesture':{'native_task_id':8,'releasing':False}}},api=SimpleNamespace(get_agent=lambda _:SimpleNamespace(cancel_task=cancelled.append)))
    native.stop(backend,'actor',tid=7)
    assert not cancelled and not backend.instances['actor']['gesture']['releasing']


@pytest.mark.parametrize('owns_base',[False,True])
def test_releasing_experimental_base_cannot_replace_a_newer_body_action(native,monkeypatch,owns_base):
    cancelled=[];idles=[]
    native.bh.BehaviorTaskStatus=SimpleNamespace(RUNNING='running');native.carb.Float3=lambda *v:v
    agent=SimpleNamespace(get_task_status=lambda _:'ended',cancel_task=cancelled.append,get_action_task_id=lambda:89 if owns_base else 90,idle=lambda **kw:idles.append(kw))
    state={'native_task_id':8,'action':'reach_hand','hand':'left','releasing':True,'base_task_id':89,'baseline':{'facing_direction':[0,-1,0]}}
    backend=SimpleNamespace(instances={'actor':{'gesture':state}},api=SimpleNamespace(get_agent=lambda _:agent),up='Z',to_stage=lambda v:v)
    monkeypatch.setattr(native,'return_ready',lambda *args:True)
    assert native.settled(backend,'actor',{'ready':True}) is False
    assert cancelled==[89] and bool(idles)==owns_base
    assert native.settled(backend,'actor',{'ready':True}) is True
    assert 'gesture' not in backend.instances['actor']
