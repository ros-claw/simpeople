"""Cross-client ownership, retry, bounded reads and partial batch outcomes."""
import pytest
from test_engine import Backend, Journal
from simpeople.core.engine import Engine
from simpeople.core.errors import SimPeopleError

def test_takeover_blocks_old_client_and_keeps_runtime_activity():
    e=Engine(Backend(),Journal())
    e.call('spawn',{'request_id':'spawn','controller_id':'codex','actor_id':'a'})
    tid=e.call('run_activity',{'request_id':'task','controller_id':'codex','actor_id':'a','steps':[{'action':'wait','duration_s':10}]})['task_id']
    with pytest.raises(SimPeopleError) as err:e.call('cancel',{'request_id':'cancel','controller_id':'claude','task_id':tid})
    assert err.value.code=='CONTROLLER_BUSY'
    epoch=e.cmd_session_info({})['controller_epoch']
    e.call('control_session',{'request_id':'takeover','controller_id':'claude','action':'takeover','expected_epoch':epoch})
    assert e.tasks[tid]['status']=='accepted'
    with pytest.raises(SimPeopleError):e.call('spawn',{'request_id':'spawn','controller_id':'codex','actor_id':'a'})
    e.call('cancel',{'request_id':'cancel2','controller_id':'claude','task_id':tid})
    assert e.tasks[tid]['cancel_requested']

def test_stale_generation_cannot_claim_free_session():
    e=Engine(Backend(),Journal())
    with pytest.raises(SimPeopleError):e.call('spawn',{'request_id':'spawn','controller_id':'codex','controller_epoch':99,'actor_id':'a'})
    assert e.controller_id is None and not e.actors

def test_batch_individual_results_and_retry_without_duplicate_writes():
    e=Engine(Backend(),Journal())
    request={'request_id':'batch','operation':'spawn','items':[{'actor_id':'a','role':'worker','group':'west'},{'actor_id':'a'},{'actor_id':'b','role':'patrol'}]}
    r=e.call('batch',request)
    assert r['accepted']==2 and r['rejected']==1
    assert e.call('batch',request)['idempotent_replay']
    r=e.call('batch',{'request_id':'plans','operation':'run_activity','selector':{'group':'west'},'steps':[{'action':'wait','duration_s':1}]})
    assert r['accepted']==1
    assert e.cmd_crowd_state({'selector':{'role':'patrol'}})['total']==1
    assert e.cmd_crowd_state({'limit':1})['next_offset']==1
    assert 'observation' not in e.cmd_crowd_state({})['actors'][0]

def test_event_cursor_replay_gap_and_bounded_pages():
    e=Engine(Backend(),Journal())
    for i in range(2100):e.event('example',value=i)
    r=e.cmd_read_events({'after':0,'limit':100})
    assert r['history_gap'] and len(r['events'])==100
    again=e.cmd_read_events({'after':r['next_cursor'],'limit':100})
    assert again['events'][0]['cursor']>r['events'][-1]['cursor']
    assert not again['history_gap']
    with pytest.raises(SimPeopleError):e.cmd_read_events({'limit':101})

def test_batch_rejects_bad_envelope_before_partial_writes():
    e=Engine(Backend(),Journal())
    with pytest.raises(SimPeopleError):e.call('batch',{'request_id':'batch','operation':'spawn','items':[{'actor_id':'a'},{'actor_id':'b','unexpected':1}]})
    assert not e.actors

def test_reset_retry_is_idempotent_across_its_own_episode_change():
    e=Engine(Backend(),Journal());old=e.episode_id
    p={'request_id':'reset','episode_id':old}
    first=e.call('reset',p);second=e.call('reset',p)
    assert second['idempotent_replay'] and first['episode_id']==second['episode_id']

def test_boolean_is_not_a_control_generation():
    e=Engine(Backend(),Journal())
    with pytest.raises(SimPeopleError):e.call('control_session',{'request_id':'take','controller_id':'qa','action':'takeover','expected_epoch':False})
    assert e.controller_id is None


def test_bound_batch_items_preserve_busy_actor_and_allow_another_actor():
    e=Engine(Backend(),Journal())
    for aid in ['a','b']:e.call('spawn',{'request_id':'spawn_'+aid,'actor_id':aid})
    old=e.call('run_activity',{'request_id':'old','actor_id':'a','steps':[{'action':'wait','duration_s':10}]})['task_id']
    r=e.call('batch',{'request_id':'bound','operation':'run_activity','items':[{'actor_id':aid,'actor_instance_id':e.actors[aid]['actor_instance_id'],'if_busy':'reject','on_blocked':'report','steps':[{'action':'wait','duration_s':1}]} for aid in ['a','b']]})
    assert r['accepted']==1 and r['rejected']==1
    assert r['results'][0]['error']['code']=='ACTOR_BUSY'
    assert e.actors['a']['task_id']==old and e.tasks[old]['status']=='accepted'
    assert e.actors['b']['task_id']==r['results'][1]['result']['task_id']


def test_stale_batch_instance_cannot_assign_work_to_recreated_actor():
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn1','actor_id':'a'});old=e.actors['a']['actor_instance_id']
    e.call('despawn',{'request_id':'delete','actor_id':'a'});e.call('spawn',{'request_id':'spawn2','actor_id':'a'})
    stopped=e.backend.stops
    r=e.call('batch',{'request_id':'stale','operation':'run_activity','items':[{'actor_id':'a','actor_instance_id':old,'steps':[{'action':'wait','duration_s':1}]}]})
    assert r['results'][0]['error']['code']=='ACTOR_INSTANCE_MISMATCH'
    assert e.actors['a']['task_id'] is None and e.backend.stops==stopped


@pytest.mark.parametrize('bound',[True,False])
def test_batch_cancel_task_cannot_be_labeled_as_another_actor(bound):
    e=Engine(Backend(),Journal())
    for aid in ['a','b']:e.call('spawn',{'request_id':'spawn_'+aid,'actor_id':aid})
    tid=e.call('run_activity',{'request_id':'old','actor_id':'a','steps':[{'action':'wait','duration_s':10}]})['task_id']
    item={'actor_id':'b','task_id':tid}
    if bound:item['actor_instance_id']=e.actors['b']['actor_instance_id']
    r=e.call('batch',{'request_id':'badcancel','operation':'cancel','items':[item]})
    assert r['results'][0]['error']['code']=='INVALID_REQUEST'
    assert not e.tasks[tid]['cancel_requested'] and e.backend.stops==0


def test_bad_batch_envelope_reports_the_exact_fields_before_any_write():
    e=Engine(Backend(),Journal())
    with pytest.raises(SimPeopleError) as error:e.call('batch',{'request_id':'bad','operation':'spawn','items':[{'actor_id':'a'},{'actor_id':'b','mystery':1}]})
    assert error.value.details['item_index']==1
    assert error.value.details['unsupported_fields']==['mystery']
    assert 'spawn_anchor' in error.value.details['allowed_item_fields']
    assert not e.actors


def test_old_task_cannot_use_either_instance_id_to_cancel_a_new_instance():
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn1','actor_id':'a'});old_instance=e.actors['a']['actor_instance_id']
    old=e.call('run_activity',{'request_id':'old','actor_id':'a','steps':[{'action':'wait','duration_s':10}]})['task_id']
    e.call('despawn',{'request_id':'delete','actor_id':'a'});e.call('spawn',{'request_id':'spawn2','actor_id':'a'})
    new_instance=e.actors['a']['actor_instance_id'];new=e.call('run_activity',{'request_id':'new','actor_id':'a','steps':[{'action':'wait','duration_s':10}]})['task_id'];stops=e.backend.stops
    for i,instance in enumerate([old_instance,new_instance]):
        result=e.call('batch',{'request_id':'late_'+str(i),'operation':'cancel','items':[{'task_id':old,'actor_instance_id':instance}]})
        assert result['results'][0]['error']['code']=='ACTOR_INSTANCE_MISMATCH'
    assert e.actors['a']['task_id']==new and not e.tasks[new]['cancel_requested'] and e.backend.stops==stops


def test_single_cancel_rejects_conflicting_actor_and_task_before_native_stop():
    e=Engine(Backend(),Journal())
    for aid in ['a','b']:e.call('spawn',{'request_id':'spawn_'+aid,'actor_id':aid})
    tid=e.call('run_activity',{'request_id':'old','actor_id':'a','steps':[{'action':'wait','duration_s':10}]})['task_id'];before=[e.actors[a]['control_epoch'] for a in ['a','b']]
    with pytest.raises(SimPeopleError) as error:e.call('cancel',{'request_id':'wrong','actor_id':'b','task_id':tid})
    assert error.value.code=='INVALID_REQUEST' and not e.tasks[tid]['cancel_requested']
    assert before==[e.actors[a]['control_epoch'] for a in ['a','b']] and e.backend.stops==0
