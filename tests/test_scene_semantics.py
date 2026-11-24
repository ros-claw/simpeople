import copy,importlib.util,sys
from pathlib import Path
import pytest
from simpeople.core import scene_semantics as module
from simpeople.core.errors import SimPeopleError
Registry=module.SceneInteractionRegistry

def seat():return {'semantic_id':'seat','kind':'seat','prim_path':'/Room/Seat','approach_points_m':[[0,0,0]],'exit_points_m':[[1.3,0,0]],'anchors':{'hips':{'position_m':[0,1,.56]}}}
def actor():return {'actor_id':'a','actor_instance_id':'new','ready':True,'position_m':[0,0,0],'capabilities':{k:{'status':'verified'} for k in ['walk','sit','queue','wait','look_at']}}
def snapshot():return {'sim_time':4,'navmesh_available':True,'path_checks':{'seat':True},'occupancy':{}}

def test_geometry_revision_excludes_live_occupancy():
 r=Registry([seat()]);before=r.resolve('seat')['geometry_revision'];one=snapshot();one['occupancy']={'seat':{'occupants':[{'actor_id':'b','actor_instance_id':'b1'}]}}
 assert not r.validate_interaction(actor(),'sit','seat',one)['valid']
 assert r.validate_interaction(actor(),'sit','seat',snapshot())['valid']
 assert r.resolve('seat')['geometry_revision']==before

def test_changed_anchor_rejects_an_old_planning_result():
 r=Registry([seat()]);old=r.resolve('seat')['geometry_revision'];changed=seat();changed['anchors']['hips']['position_m'][2]=.7
 with pytest.raises(SimPeopleError) as e:Registry([changed]).resolve('seat',old)
 assert e.value.code=='TARGET_STALE'

def test_duplicate_physical_resource_aliases_are_rejected():
 with pytest.raises(SimPeopleError):Registry([seat(),{**seat(),'semantic_id':'another_name'}])

def test_previous_incarnation_occupancy_is_not_owned_by_same_named_actor():
 s=snapshot();s['occupancy']={'seat':{'occupants':[{'actor_id':'a','actor_instance_id':'old'}]}}
 result=Registry([seat()]).validate_interaction(actor(),'sit','seat',s)
 assert not result['valid'] and result['errors'][0]['code']=='RESOURCE_BUSY'
 assert result['reservation_acquired'] is False

def test_unknown_object_and_unverified_gesture_do_not_gain_actions():
 r=Registry([seat()])
 with pytest.raises(SimPeopleError):r.resolve('arbitrary_box')
 result=r.validate_interaction(actor(),'reach_hand','seat',snapshot())
 assert not result['valid'] and result['errors'][0]['code']=='ACTION_UNSUPPORTED'

@pytest.mark.parametrize('data',[{'capacity':True},{'kind':'location'},{'approach_points_m':[[float('nan'),0,0]]}])
def test_invalid_semantics_rejected(data):
 with pytest.raises(SimPeopleError):Registry([{**seat(),**data}])

def test_stale_evidence_is_downgraded_and_missing_approach_blocks_preflight():
 data={**seat(),'evidence':{'status':'verified','geometry_revision':'old'}};r=Registry([data]);assert r.resolve('seat')['evidence']['status']=='discovered'
 data['approach_points_m']=[];assert not Registry([data]).validate_interaction(actor(),'sit','seat',snapshot())['valid']

def test_queue_full_can_offer_bounded_wait_without_claiming_a_slot():
 data={**seat(),'kind':'queue','capacity':1};s=snapshot();s['occupancy']={'seat':{'occupants':[{'actor_id':'b','actor_instance_id':'b1'}],'waiters':[],'outside_capacity':1}}
 result=Registry([data]).validate_interaction(actor(),'queue','seat',s)
 assert result['valid'] and 'queue_full_bounded_outside_wait_available' in result['warnings'] and not result['reservation_acquired']
 s['occupancy']['seat']['waiters']=[{'actor_id':'c'}];assert not Registry([data]).validate_interaction(actor(),'queue','seat',s)['valid']
