import pytest
from simpeople.core.engine import Engine
from simpeople.core.protocol import activity,activity_contract,ACTIONS
from simpeople.core.errors import SimPeopleError
from test_engine import Backend,Journal


@pytest.mark.parametrize('gait',['walk','run'])
def test_capability_template_builds_a_valid_movement_plan(gait):
    contract=activity_contract()
    step={**contract['capability_to_step_fields'][gait],'target':[1,2,0]}
    validated=activity({'actor_id':'a','steps':[step]})
    assert validated==[{'action':'move_to','gait':gait,'target':[1.,2.,0.]}]
    assert gait not in contract['step_action_values']
    assert set(contract['step_action_values'])==ACTIONS


def test_readable_contract_does_not_promote_an_unverified_capability():
    backend=Backend();backend.list_actions=lambda _: {'walk':{'status':'verified'},'run':{'status':'blocked'}}
    e=Engine(backend,Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    before=(e.actors['a']['control_epoch'],len(e.tasks),backend.stops)
    reply=e.call('list_actions',{'actor_id':'a'})
    assert reply['actions']['run']['status']=='blocked'
    assert reply['activity_contract']['capability_to_step_fields']['run']['action']=='move_to'
    reply['activity_contract']['step_action_values'].append('walk')
    assert 'walk' not in e.call('list_actions',{'actor_id':'a'})['activity_contract']['step_action_values']
    assert before==(e.actors['a']['control_epoch'],len(e.tasks),backend.stops)


def test_invalid_capability_as_verb_preserves_work_and_explains_the_mapping():
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    old=e.call('run_activity',{'request_id':'old','actor_id':'a','steps':[{'action':'wait','duration_s':10}]})['task_id']
    before=(e.actors['a']['control_epoch'],len(e.tasks),e.backend.stops)
    with pytest.raises(SimPeopleError) as error:
        e.call('run_activity',{'request_id':'bad','actor_id':'a','steps':[{'action':'walk','target':[1,2,0]}]})
    assert error.value.code=='ACTION_UNSUPPORTED'
    assert error.value.details['step_fields_hint']=={'action':'move_to','gait':'walk'}
    assert 'move_to' in error.value.details['allowed_step_actions']
    assert before==(e.actors['a']['control_epoch'],len(e.tasks),e.backend.stops)
    assert e.actors['a']['task_id']==old and not e.tasks[old]['cancel_requested']
