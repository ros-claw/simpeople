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
