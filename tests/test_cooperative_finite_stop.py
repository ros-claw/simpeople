"""Counterexamples for the private prototype; these do not qualify Native motion."""
import copy,hashlib,importlib.util,sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from pxr import Usd,UsdSkel,UsdGeom,Gf,Vt
ROOT=Path(__file__).resolve().parents[1]
from simpeople.backends.native import cooperative_finite_stop as m
from simpeople.backends.native.custom_stop import ready
from simpeople.core.errors import SimPeopleError
POSE=[[0.,0.,1.,0.,0.,0.,1.]]
class Agent:
 def __init__(self):self.current=5;self.names={5:'finite',3:'Idle',9:'Idle'};self.states={5:'running',3:'running',9:'running'};self.commands=[];self.receipt=9
 def get_action_task_id(self):return self.current
 def get_task_name(self,i):return self.names.get(i,'foreign')
 def cancel_task(self,i):self.commands.append(('cancel',i));self.states[i]='failed'
 def idle(self):
  self.commands.append(('idle',));return self.receipt
class Backend:
 def __init__(self):
  self.now=10.;self.thread_calls=0;self.agent_obj=Agent();self.cooperative_finite_stop_probe_enabled=True;self.timeline=SimpleNamespace(get_current_time=lambda:self.now);self.api=SimpleNamespace(get_agent=lambda h:self.agent_obj);self.on_event=None;self.pose=copy.deepcopy(POSE);self.instances={'a':{'traffic_instance_id':'body1','asset_id':'asset1','engine_native_ids':[3,5]}};self.assets=[{'asset_id':'asset1','content_hash':'assetsha'}];self.observation={};self.root=ROOT
  self.spec=dict(clip='finite',body_generation='body1',source_clip_sha256='clipsha',source_asset_sha256='assetsha',requested_native_duration_s=.2,conservative_authored_cycle_bound_s=12.,reference=dict(joint_paths=['Hips'],world_pose=copy.deepcopy(POSE),facing_direction=[0.,1.,0.]))
  m.register(self,'a',5,self.spec)
 def assert_thread(self):self.thread_calls+=1
 def observe(self,h):
  a=self.agent_obj;return dict(ready=True,observation_sim_time=self.now,native_task_id=a.current,action=a.get_task_name(a.current),speed_mps=0.,facing_direction=[0.,1.,0.],**self.observation)
 def task_state(self,h,i):return self.agent_obj.states[i]
@pytest.fixture
def b(monkeypatch):
 b=Backend();monkeypatch.setattr(m,'capture',lambda backend,*_:copy.deepcopy(backend.pose));return b

def request(b):return m.request(b,'a',b.agent_obj.current,b.agent_obj.get_task_name(b.agent_obj.current),b.agent_obj)
def advance(b):return m.advance(b,'a',b.instances['a']['custom_stop'],b.observe('a'),b.agent_obj)
def test_active_does_not_interrupt_or_claim_stop(b):
 assert request(b);record=copy.deepcopy(b.instances['a']['custom_stop']);assert b.agent_obj.commands==[]
 for _ in range(300):b.now+=1/30;assert not advance(b)
 assert not b.agent_obj.commands and record['requested_sim_time']==10

def test_natural_end_neutral_then_distinct_owned_idle_actual_16_samples(b):
 assert request(b);b.agent_obj.states[5]='succeeded';b.agent_obj.current=0
 for i in range(4):b.now=11+i/30;assert not advance(b)
 record=b.instances['a']['custom_stop'];assert b.agent_obj.commands==[('idle',)] and record['idle_request_native_task_id']==9
 assert not ready(b,'a',b.observe('a'),True)
 b.agent_obj.current=9
 for i in range(1,17):
  b.now=record['idle_requested_sim_time']+i/30
  assert advance(b);assert ready(b,'a',b.observe('a'),True)==(i==16)
 assert record['settled_emitted']

def test_queued_cancels_exact_owned_task_once(b):
 b.agent_obj.current=3;assert request(b);record=copy.deepcopy(b.instances['a']['custom_stop']);assert b.agent_obj.commands==[('cancel',5),('idle',)]
 b.now+=.2;assert request(b);assert b.instances['a']['custom_stop']==record and len(b.agent_obj.commands)==2

def test_active_repeat_after_actual_task_end_is_idempotent(b):
 assert request(b);old=copy.deepcopy(b.instances['a']['custom_stop']);b.agent_obj.states[5]='succeeded';b.agent_obj.current=0;b.now+=.2
 assert request(b);assert old==b.instances['a']['custom_stop'] and not b.agent_obj.commands

@pytest.mark.parametrize('change',['newbody','foreign','disabled','staleobs','notready','finished','unknownowned'])
def test_request_rejects_stale_or_foreign_ownership(b,change):
 if change=='newbody':b.instances['a']['traffic_instance_id']='body2'
 elif change=='foreign':b.agent_obj.current=8
 elif change=='disabled':b.cooperative_finite_stop_probe_enabled=False
 elif change=='staleobs':b.observe=lambda h:dict(ready=True,observation_sim_time=9.,native_task_id=5)
 elif change=='notready':b.observe=lambda h:dict(ready=False)
 elif change=='finished':b.agent_obj.states[5]='succeeded'
 elif change=='unknownowned':b.instances['a']['engine_native_ids']=[]
 assert not request(b);assert not b.agent_obj.commands and 'custom_stop' not in b.instances['a']

@pytest.mark.parametrize('change',['newbody','foreign','duplicate','stale','too_late','notready','failed','playing','moving','offneutral','nanpose'])
def test_advance_does_not_guess_a_stop(b,change):
 assert request(b);b.agent_obj.states[5]='succeeded';b.agent_obj.current=0;b.now=11
 if change=='newbody':b.instances['a']['traffic_instance_id']='new'
 elif change=='foreign':b.agent_obj.current=8
 elif change=='duplicate':b.now=10
 elif change=='stale':b.observe=lambda h:dict(ready=True,observation_sim_time=10.,native_task_id=0)
 elif change=='too_late':b.now=25.1
 elif change=='notready':b.observe=lambda h:dict(ready=False)
 elif change=='failed':b.agent_obj.states[5]='failed'
 elif change=='playing':b.agent_obj.states[5]='running'
 elif change=='moving':b.observe=lambda h:dict(ready=True,observation_sim_time=b.now,native_task_id=0,speed_mps=.2)
 elif change=='offneutral':b.pose[0][0]=.021
 elif change=='nanpose':b.pose[0][0]=float('nan')
 for i in range(4):assert not advance(b);b.now+=1/30
 assert not b.agent_obj.commands

@pytest.mark.parametrize('gap',[0.,2/30,-1/30])
def test_neutral_requires_four_distinct_adjacent_samples(b,gap):
 assert request(b);b.agent_obj.states[5]='succeeded';b.agent_obj.current=0;b.now=11
 for _ in range(3):assert not advance(b);b.now+=1/30
 b.now-=1/30;b.now+=gap;assert not advance(b);assert not b.agent_obj.commands

@pytest.mark.parametrize('receipt',[0,-1,True,None,5,1.5])
def test_bad_idle_receipt_never_retries_or_settles(b,receipt):
 b.agent_obj.receipt=receipt;b.agent_obj.current=3;assert request(b);record=b.instances['a']['custom_stop'];assert record['idle_request_failed']
 for _ in range(30):b.now+=1/30;assert not advance(b)
 assert len(b.agent_obj.commands)==2

@pytest.mark.parametrize('tid',[False,None,0,-2,2.3])
def test_register_invalid_receipt_rejected(b,tid):
 with pytest.raises(ValueError):m.register(b,'a',tid,b.spec)

def entry(b,tmp_path,frames=5):
 p=tmp_path/'motion.usda';s=Usd.Stage.CreateNew(str(p));UsdGeom.SetStageMetersPerUnit(s,.01);UsdGeom.SetStageUpAxis(s,'Y');s.SetTimeCodesPerSecond(30);a=UsdSkel.Animation.Define(s,'/Animation');s.SetDefaultPrim(a.GetPrim());a.CreateJointsAttr(['Hips'])
 for i in range(frames):a.CreateRotationsAttr().Set(Vt.QuatfArray([Gf.Quatf(1)]),i)
 s.GetRootLayer().Save();e=dict(playback_mode='transition_then_hold',sample_rate=30,frame_count=frames,endpoint_hold_frames=15,requested_native_duration_s=.2,canonical_entry=dict(b.spec['reference'],source_asset_sha256='assetsha'),entry_base_action='Idle',cooperative_finite_cycle=True,clip=str(p),source_sha256=dict(clip=hashlib.sha256(p.read_bytes()).hexdigest()));b.custom_actions={'finite':e};return e

def test_validate_actual_authored_contract(b,tmp_path):
 entry(b,tmp_path);result=m.validate(b,'a',dict(action='custom_action',target='finite',duration_s=.2));assert result['body_generation']=='body1' and result['conservative_authored_cycle_bound_s']<13
@pytest.mark.parametrize('field,value',[('playback_mode','loop'),('frame_count',True),('frame_count',1000),('endpoint_hold_frames',True),('endpoint_hold_frames',31),('sample_rate',24),('entry_base_action','Walk'),('requested_native_duration_s',.3),('canonical_entry',{}),('source_sha256',{'clip':'wrong'})])
def test_validate_rejects_changed_contract(b,tmp_path,field,value):
 e=entry(b,tmp_path);e[field]=value
 with pytest.raises(SimPeopleError):m.validate(b,'a',dict(action='custom_action',target='finite',duration_s=.2))
@pytest.mark.parametrize('duration',[True,0,-1,float('nan'),float('inf'),.3])
def test_validate_exact_positive_duration(b,tmp_path,duration):
 entry(b,tmp_path)
 with pytest.raises(SimPeopleError):m.validate(b,'a',dict(action='custom_action',target='finite',duration_s=duration))
