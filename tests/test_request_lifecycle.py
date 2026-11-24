"""Request-scope and late-result regressions; no simulated animation claims."""
import copy
import pytest
from test_engine import Backend,Journal
from simpeople.core.engine import Engine
from simpeople.core.errors import SimPeopleError


def test_repeated_cancel_with_a_new_request_id_does_not_restart_native_stop_or_its_budget():
    backend=Backend();backend.gesture_stop_settled=lambda *_:False
    e=Engine(backend,Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    tid=e.call('run_activity',{'request_id':'task','actor_id':'a','steps':[{'action':'wait','duration_s':30}]})['task_id']
    e.tick(0);e.tick(.2)
    e.call('cancel',{'request_id':'first_cancel','task_id':tid})
    before=copy.deepcopy(e.actors['a']);stop_time=e.tasks[tid]['cancel_sim_time']
    e.tick(10.2)
    second=e.call('cancel',{'request_id':'second_cancel','task_id':tid})
    assert second['cancellation']=='accepted'
    assert e.actors['a']==before and backend.stops==1
    assert e.tasks[tid]['cancel_sim_time']==stop_time==.2
    assert len([x for x in e.journal.events if x['kind']=='cancel_requested'])==1
    e.tick(15.3)
    assert e.tasks[tid]['status']=='failed' and e.tasks[tid]['error']['code']=='STOP_FAILED'


def test_pending_cancel_still_rejects_a_different_actor_binding():
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    tid=e.call('run_activity',{'request_id':'task','actor_id':'a','steps':[{'action':'wait','duration_s':30}]})['task_id']
    e.tick(0);e.call('cancel',{'request_id':'first_cancel','task_id':tid})
    before=copy.deepcopy(e.actors['a'])
    with pytest.raises(SimPeopleError):
        e.call('cancel',{'request_id':'wrong_actor','task_id':tid,'actor_id':'b'})
    assert e.actors['a']==before and e.backend.stops==1

@pytest.mark.parametrize('scope', ['session_id','episode_id'])
def test_stale_scope_does_not_acquire_controller(scope):
    e=Engine(Backend(),Journal());before=(e.controller_id,e.controller_epoch)
    with pytest.raises(SimPeopleError):
        e.call('spawn',{'request_id':'stale','controller_id':'codex',scope:'old','actor_id':'a'})
    assert (e.controller_id,e.controller_epoch)==before
    assert not e.actors and not e.tasks

def test_reset_retry_returns_original_receipt_with_acquisition_epoch():
    e=Engine(Backend(),Journal());old=e.episode_id
    p={'request_id':'reset','controller_id':'codex','controller_epoch':0,'episode_id':old}
    first=e.call('reset',p);second=e.call('reset',p)
    assert second['idempotent_replay'] and first['episode_id']==second['episode_id']
    assert e.controller_epoch==1

def test_old_spawn_replay_cannot_cross_a_later_reset():
    e=Engine(Backend(),Journal());p={'request_id':'spawn','actor_id':'a'};e.call('spawn',p)
    e.call('reset',{'request_id':'reset'})
    with pytest.raises(SimPeopleError) as err:e.call('spawn',p)
    assert err.value.code=='EPISODE_MISMATCH' and not e.actors

def test_rejected_call_emits_correlated_result():
    j=Journal();e=Engine(Backend(),j)
    with pytest.raises(SimPeopleError):
        e.call('run_activity',{'request_id':'bad','command_id':'cmd','attempt_id':'try1','actor_id':'missing','steps':[]})
    outcomes=[x for x in j.events if x['kind']=='tool_result' and x.get('request_id')=='bad']
    assert len(outcomes)==1 and outcomes[0]['error']['stage']=='validation'
    assert outcomes[0]['command_id']=='cmd' and outcomes[0]['attempt_id']=='try1'
    assert e.controller_id is None

def test_actor_instance_and_old_task_observation_are_fenced():
    e=Engine(Backend(),Journal());one=e.call('spawn',{'request_id':'one','actor_id':'a'})
    task=e.call('run_activity',{'request_id':'task','actor_id':'a','steps':[{'action':'wait','duration_s':10}]})
    e.call('despawn',{'request_id':'remove','actor_id':'a'});two=e.call('spawn',{'request_id':'two','actor_id':'a'})
    assert one['actor_instance_id']!=two['actor_instance_id']
    assert e.call('get_state',{'task_id':task['task_id']})['observation'] is None

def test_late_cleanup_cannot_release_new_lease():
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    old=e.call('run_activity',{'request_id':'old','actor_id':'a','steps':[{'action':'wait','duration_s':10,'resource_id':'bench'}]});e.tick(0)
    delayed=copy.deepcopy(e.tasks[old['task_id']])
    new=e.call('run_activity',{'request_id':'new','actor_id':'a','steps':[{'action':'wait','duration_s':10,'resource_id':'bench'}]});e.tick(.1)
    e.finish(delayed,'failed',{'code':'OLD_CALLBACK'})
    assert e.resources.owners=={'bench':'a'}
    assert e.tasks[new['task_id']]['status']=='running'

def test_on_blocked_policy_is_effective_or_explicitly_unsupported():
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    with pytest.raises(SimPeopleError) as err:
        e.call('run_activity',{'request_id':'policy','actor_id':'a','on_blocked':'replan_or_report','steps':[{'action':'wait','duration_s':1}]})
    assert err.value.code=='POLICY_UNSUPPORTED'

def test_takeover_preserves_accepted_activity():
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn','controller_id':'a','actor_id':'a'})
    t=e.call('run_activity',{'request_id':'task','controller_id':'a','command_id':'cmd','attempt_id':'try1','actor_id':'a','steps':[{'action':'wait','duration_s':3}]})
    e.call('control_session',{'request_id':'take','controller_id':'b','action':'takeover','expected_epoch':e.controller_epoch})
    e.tick(0);e.tick(3)
    assert e.tasks[t['task_id']]['status']=='succeeded'
    events=[x for x in e.journal.events if x['kind']=='task_ended' and x['task']['task_id']==t['task_id']]
    assert events[0]['task']['command_id']=='cmd'

def test_old_resource_and_queue_tokens_cannot_release_successor():
    from simpeople.core.resources import Resources
    from simpeople.core.population import Queues
    r=Resources();old=('a','first-instance',1,'t1');new=('a','second-instance',1,'t2')
    assert r.acquire('seat','a',token=old)
    r.release('a',token=old);assert r.acquire('seat','a',token=new)
    r.release('a',token=old);r.release('a')
    assert r.owners=={'seat':'a'}
    q=Queues();q.join('queue','a',1,token=old);q.remove('a',token=old)
    q.join('queue','a',1,token=new);q.remove('a',token=old);q.remove('a')
    assert q.members['queue']==['a']

def test_stale_actor_binding_does_not_change_recreated_actor():
    e=Engine(Backend(),Journal());one=e.call('spawn',{'request_id':'one','actor_id':'a'})
    e.call('despawn',{'request_id':'remove','actor_id':'a'});e.call('spawn',{'request_id':'two','actor_id':'a'})
    with pytest.raises(SimPeopleError) as err:
        e.call('run_activity',{'request_id':'late','actor_id':'a','actor_instance_id':one['actor_instance_id'],'steps':[{'action':'wait','duration_s':1}]})
    assert err.value.code=='ACTOR_INSTANCE_MISMATCH' and e.actors['a']['task_id'] is None

def test_open_arrival_busy_rejection_preserves_current_task():
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    one=e.call('run_activity',{'request_id':'one','actor_id':'a','steps':[{'action':'wait','duration_s':10}]})
    with pytest.raises(SimPeopleError) as err:
        e.call('run_activity',{'request_id':'two','actor_id':'a','if_busy':'reject','steps':[{'action':'wait','duration_s':1}]})
    assert err.value.code=='ACTOR_BUSY' and e.actors['a']['task_id']==one['task_id']

def test_nonfinite_rejection_is_serializable_and_preserves_owner():
    import json
    journal=Journal();e=Engine(Backend(),journal)
    with pytest.raises(SimPeopleError):
        e.call('spawn',{'request_id':'bad','actor_id':'a','spawn_anchor':[float('nan'),0,0]})
    assert e.controller_id is None and not e.actors
    json.dumps(journal.events,allow_nan=False)
    assert journal.events[-1]['kind']=='tool_result' and journal.events[-1]['error']['code']=='INVALID_REQUEST'

def test_native_ids_reused_across_tasks_are_not_falsely_correlated():
    journal=Journal();e=Engine(Backend(),journal);key=('/World/a','7')
    e.native_lineage[key]=[{'task_id':'old','command_id':'one'},{'task_id':'new','command_id':'two'}]
    e._call_context={'request_id':'currently_executing','command_id':'other_command'}
    e.event('native_task_ended',agent=key[0],task_id=7)
    event=journal.events[-1]
    assert event['correlation_status']=='ambiguous' and event['native_task_id']==7
    assert 'logical_task_id' not in event and 'command_id' not in event
    e.native_lineage[key]=[{'task_id':'new','command_id':'two'}]
    e.event('native_task_ended',agent=key[0],task_id=7)
    assert journal.events[-1]['logical_task_id']=='new' and journal.events[-1]['command_id']=='two'

def test_replaying_release_does_not_reacquire_ownership():
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn','controller_id':'test','actor_id':'a'})
    params={'request_id':'release','controller_id':'test','action':'release','expected_epoch':e.controller_epoch}
    first=e.call('control_session',params);epoch=e.controller_epoch
    second=e.call('control_session',params)
    assert second['idempotent_replay'] and e.controller_id is None and e.controller_epoch==epoch

def test_replacement_records_origin_separately_from_cancelling_command():
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    old=e.call('run_activity',{'request_id':'old','actor_id':'a','steps':[{'action':'wait','duration_s':10}]})
    e.call('run_activity',{'request_id':'new','command_id':'new_command','attempt_id':'new_attempt','actor_id':'a','steps':[{'action':'wait','duration_s':1}]})
    event=next(x for x in e.journal.events if x['kind']=='task_ended' and x['task_id']==old['task_id'])
    assert event['request_id']=='old' and event['command_id'] is None
    assert event['caused_by_request_id']=='new' and event['caused_by_command_id']=='new_command'
