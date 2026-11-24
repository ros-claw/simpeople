"""Tamper checks for recorded scheduling evidence, not simulated native passes."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('retry_auditor',Path(__file__).parents[1]/'scripts/audit_retry_identity.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


def events(incarnation='one'):
    rows=[]
    for index,(actor,delay) in enumerate([('a',.21),('b',.28)]):
        handle=actor+'-'+incarnation;route='route-'+actor
        rows.extend([
            {'kind':'tool_result','method':'spawn','result':{'actor_id':actor,'actor_instance_id':handle+'-instance','prim_path':handle}},
            {'kind':'traffic_route_started','route_id':route,'agent':handle,'retry_actor_id':actor,'retry_delay_s':delay},
            {'kind':'traffic_wait_started','route_id':route,'agent':handle,'retry_actor_id':actor,'retry_delay_s':delay,'sim_time':10+index,'retry_at_sim_time':10+index+delay}])
    for i,row in enumerate(rows):row.update(cursor=i+1,episode_id='fixture-episode')
    return rows


def fixture(directory,incarnation='one',functional=True):
    directory.mkdir();(directory/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events(incarnation)))
    for name,value in [('completed.json',{'harness_completed':True,'functional_expected_matched':functional}),('benchmark_done.json',{'event_cursor':6}),('source_manifest.json',{'fixture.py':'fixed-input-hash'}),('workload.json',{'case_id':'fixture'})]:
        (directory/name).write_text(json.dumps(value))
    return directory


def test_valid_schedule_is_bound_to_spawn_not_physical_path_hash():
    result=audit.audit_events(events())
    assert result['execution_checks_passed'] and result['actors']['a']['delay_s']==.21
    assert result['actors']['a']['physical_handles']==['a-one']


@pytest.mark.parametrize('mutation,reason',[
    ('path_key','retry_key_is_not_logical_actor'),('clock','actual_retry_schedule_mismatch'),
    ('wait_identity','wait_identity_changed'),('delay','wait_delay_changed'),
    ('unbound','route_has_no_spawn_binding'),('bucket','delay_outside_declared_stagger_buckets')])
def test_tampered_native_log_never_passes(mutation,reason):
    rows=events()
    if mutation=='path_key':rows[1]['retry_actor_id']='a-one'
    elif mutation=='clock':rows[2]['retry_at_sim_time']+=.033333
    elif mutation=='wait_identity':rows[2]['agent']='new-incarnation'
    elif mutation=='delay':rows[2]['retry_delay_s']=.22
    elif mutation=='unbound':rows[0]['method']='get_state'
    elif mutation=='bucket':rows[1]['retry_delay_s']=.215
    result=audit.audit_events(rows)
    assert not result['execution_checks_passed'] and reason in {r['reason'] for r in result['errors']}


def test_no_block_execution_and_legacy_logs_cannot_qualify():
    rows=events();assert not audit.audit_events([r for r in rows if r['kind']!='traffic_wait_started'])['execution_checks_passed']
    for row in rows:row.pop('retry_actor_id',None)
    assert audit.audit_events(rows)['supported'] is False


def test_closed_guard_and_cutoff_exclude_shutdown_events(tmp_path):
    assert audit.audit(tmp_path)['measurement_closed'] is False
    directory=fixture(tmp_path/'run')
    extra=copy.deepcopy(events()[1]);extra['cursor']=7;extra['retry_actor_id']='bad-cleanup-key'
    with (directory/'events.jsonl').open('a') as f:f.write(json.dumps(extra)+'\n')
    assert audit.audit(directory)['execution_checks_passed']


def test_repeat_checks_require_new_incarnations_equal_inputs_and_stable_delays(tmp_path):
    first=fixture(tmp_path/'first','one');second=fixture(tmp_path/'second','two',functional=False)
    result=audit.compare([first,second]);assert result['passed'] and result['runs'][1]['functional_expected_matched'] is False
    # Passing the scheduling check must not turn a failed workload into success.
    assert not audit.compare([first,first])['passed']
    (second/'workload.json').write_text('{"case_id":"different"}')
    assert {'reason':'paired_input_changed','path':'workload.json'} in audit.compare([first,second])['errors']


def test_three_repetitions_cannot_reuse_the_second_incarnation(tmp_path):
    paths=[fixture(tmp_path/name,incarnation) for name,incarnation in [('first','one'),('second','two'),('third','two')]]
    result=audit.compare(paths);assert not result['passed']
    assert any(r['reason']=='fresh_physical_incarnation_not_proven' for r in result['errors'])
