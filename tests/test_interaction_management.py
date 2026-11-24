import copy
import pytest
from simpeople.core.engine import Engine
from simpeople.core.errors import SimPeopleError
from test_engine import Backend,Journal


class InteractionBackend(Backend):
    def __init__(self):
        super().__init__();self.targets=[{'semantic_id':'station','kind':'workstation','prim_path':'/Room/Station',
            'approach_points_m':[[0,0,0]],'position_m':[0,1,.5]}]
    def interaction_targets(self,semantic_id=None):return copy.deepcopy([r for r in self.targets if semantic_id is None or r['semantic_id']==semantic_id])
    def list_actions(self,h):return {k:{'status':'verified'} for k in ['walk','wait','look_at']}
    def inspect_scene(self):return {'navmesh_available':True}
    def interaction_path_reachable(self,h,p):return True


def setup():
    e=Engine(InteractionBackend(),Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    r=e.call('list_interactions',{})['interactions'][0]['geometry_revision']
    return e,r


def test_registry_and_preflight_reads_do_not_acquire_control_or_reserve():
    e,revision=setup();e.call('control_session',{'request_id':'release','controller_id':'legacy-local','action':'release','expected_epoch':e.controller_epoch})
    before=e.controller_epoch
    result=e.call('validate_interaction',{'actor_id':'a','action':'wait','target':'station','revision':revision})
    assert result['valid'] and result['reservation_acquired'] is False and e.controller_id is None and e.controller_epoch==before
    assert not e.resources.owners and not e.backend.started


def test_stale_target_rejection_preserves_controller_and_existing_plan():
    e,revision=setup();tid=e.call('run_activity',{'request_id':'old','actor_id':'a','steps':[{'action':'wait','duration_s':4}]})['task_id']
    owner=(e.controller_id,e.controller_epoch);e.backend.targets[0]['position_m'][0]=.2
    with pytest.raises(SimPeopleError) as error:
        e.call('run_activity',{'request_id':'stale','actor_id':'a','steps':[{'action':'wait','duration_s':1,'resource_id':'station','interaction_revision':revision}]})
    assert error.value.code=='TARGET_STALE' and e.actors['a']['task_id']==tid and (e.controller_id,e.controller_epoch)==owner


def test_geometry_change_during_bound_execution_fails_and_releases_only_its_lease():
    e,revision=setup();e.call('spawn',{'request_id':'witness_spawn','actor_id':'witness'})
    tid=e.call('run_activity',{'request_id':'bound','actor_id':'a','steps':[{'action':'wait','duration_s':4,'resource_id':'station','interaction_revision':revision}]})['task_id']
    witness=e.call('run_activity',{'request_id':'witness','actor_id':'witness','steps':[{'action':'wait','duration_s':1}]})['task_id']
    e.tick(0);assert e.resources.owners=={'station':'a'}
    e.backend.targets[0]['position_m'][0]=.2;e.tick(.1)
    assert e.tasks[tid]['status']=='failed' and e.tasks[tid]['error']['code']=='TARGET_STALE' and not e.resources.owners
    e.tick(1.1);assert e.tasks[witness]['status']=='succeeded'


def test_discovery_mode_acceptance_cannot_promote_unverified_custom_clip():
    e,_=setup();e.backend.targets=[{'semantic_id':'bay','kind':'activity_bay','prim_path':'/Bay','clip':'scratch','approach_points_m':[[0,0,0]]}]
    e.backend.list_actions=lambda h:{'custom_action':{'clips':{'scratch':{'status':'discovered'}}}}
    # This backend intentionally accepts unknown clips, like allow_unverified.
    result=e.call('validate_interaction',{'actor_id':'a','target':'bay','action':'custom_action'})
    assert not result['valid'] and any(r['code']=='ACTION_UNVERIFIED' for r in result['errors'])
    assert not e.backend.started


def test_free_logical_lease_does_not_hide_a_body_still_at_the_approach():
    e,revision=setup();e.call('spawn',{'request_id':'b','actor_id':'b'})
    assert not e.resources.owners
    result=e.call('validate_interaction',{'actor_id':'a','target':'station','action':'wait','revision':revision})
    assert not result['valid'] and any(r['code']=='TARGET_BLOCKED' for r in result['errors'])
    assert result['body_clearance']['approaches'][0]['blocker_ids']==['b']
    assert e.call('list_interactions',{})['interactions'][0]['geometry_revision']==revision


def test_default_workstation_does_not_gain_head_or_hand_affordances():
    e,_=setup();target=e.call('list_interactions',{})['interactions'][0]
    assert set(target['allowed_actions'])=={'wait','look_at'}


def test_bound_hand_requires_the_explicit_matching_anchor_before_taking_control():
    e,_=setup();e.backend.targets[0].update(allowed_actions=['reach_hand'],anchors={'palm_right':{'position_m':[0,-.3,1.2]}})
    revision=e.call('list_interactions',{})['interactions'][0]['geometry_revision']
    old=e.call('run_activity',{'request_id':'old','actor_id':'a','steps':[{'action':'wait','duration_s':2}]})['task_id']
    with pytest.raises(SimPeopleError) as error:
        e.call('run_activity',{'request_id':'wrong_anchor','actor_id':'a','steps':[{'action':'reach_hand','hand':'right','target':[0,-.2,1.2],'duration_s':1,'resource_id':'station','interaction_revision':revision}]})
    assert error.value.code=='TARGET_INVALID' and e.actors['a']['task_id']==old


def test_gesture_preflight_cannot_invent_a_missing_palm_anchor():
    e,_=setup();e.backend.targets[0]['allowed_actions']=['reach_hand'];e.backend.list_actions=lambda h:{'reach_hand':{'status':'verified'}}
    result=e.call('validate_interaction',{'actor_id':'a','action':'reach_hand','target':'station','hand':'left'})
    assert not result['valid'] and any(err['code']=='TARGET_INVALID' for err in result['errors'])


@pytest.mark.parametrize('anchors',['invalid',{'palm_right':{'position_m':[0,1]}},{'palm_right':{'position_m':[0,True,1]}},{'palm_right':{'position_m':[0,float('nan'),1]}}])
def test_invalid_anchor_data_is_a_structured_read_error_without_acquiring_control(anchors):
    e,_=setup();e.backend.targets[0]['anchors']=anchors;before=(e.controller_id,e.controller_epoch,len(e.tasks))
    with pytest.raises(SimPeopleError) as error:e.call('list_interactions',{})
    assert error.value.code=='TARGET_INVALID' and before==(e.controller_id,e.controller_epoch,len(e.tasks))
