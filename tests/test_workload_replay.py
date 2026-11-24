import copy
import pytest
from test_engine import Backend,Journal
from simpeople.core.engine import Engine
from simpeople.core.workloads import WorkloadReplay,case_hash,validate_case,actor_cycle_seed

class Client:
    def __init__(self):
        self.e=Engine(Backend(),Journal());self.e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    def call(self,method,params):return self.e.call(method,params)
    def at(self,t):self.e.tick(t)

def case(mode='open_arrival',policy='queue'):
    return {'schema_version':'simpeople.benchmark.v1','case_id':'test','category':'ordinary','scene':{'id':'lab','revision':'frozen'},'actors':[{'actor_id':'a','spawn_anchor':[0,0,0]}],
        'capture_profile':'none','duration_s':20,'finite':True,'submission_mode':mode,'busy_policy':policy,'max_pending_per_actor':2,
        'requests':[{'request_case_id':f'r{i}','actor_id':'a','at_s':i,'deadline_s':20,'steps':[{'action':'wait','duration_s':3}]} for i in range(3)]}

def test_same_time_order_and_hash_are_stable():
    c=case();[r.update(at_s=0) for r in c['requests']];a=Client();b=Client();x=WorkloadReplay(c,a);y=WorkloadReplay(copy.deepcopy(c),b)
    for t in range(12):a.at(t);b.at(t);x.tick(t);y.tick(t)
    assert x.hash==y.hash and x.summary()['counts']==y.summary()['counts']
    assert [r['request_case_id'] for r in x.trace if r['kind']=='request_submitted']==['r0','r1','r2']
    assert c==validate_case(c)

def test_queue_records_actual_submit_time_not_scheduled_time():
    c=case();client=Client();r=WorkloadReplay(c,client)
    for t in [0,1,2,3,4,5,6,7,8,9,10,11]:client.at(t);r.tick(t)
    row=r.summary()['requests'][1]
    assert row['scheduled_at_s']==1 and row['eligible_at_s']==1 and row['submitted_at_s']>1
    assert all(t['error'] is None or t['error']['code']!='CANCELLED' for t in client.e.tasks.values())

def test_overload_and_unsubmitted_dependencies_stay_in_denominator():
    c=case(policy='reject');client=Client();r=WorkloadReplay(c,client)
    for t in range(21):client.at(t);r.tick(t)
    s=r.summary();assert s['scheduled']==s['denominator']==3 and s['counts']['rejected_busy']==2 and s['unsuccessful']==2
    c=case('closed_loop');c['requests'][0]['steps']=[{'action':'move_to','target':[2,0,0]}];c['requests'][1]['depends_on']=['r0'];client=Client();client.e.backend.state='failed';r=WorkloadReplay(c,client)
    for t in range(21):client.at(t);r.tick(t)
    assert r.summary()['requests'][1]['state']=='not_submitted_dependency_failed' and r.summary()['denominator']==3

def test_finite_deadline_and_continuous_censoring_are_separate():
    c=case();c['requests']=c['requests'][:1];c['requests'][0]['steps'][0]['duration_s']=30
    for finite,expected in [(True,'deadline_unfinished'),(False,'admitted')]:
        c['finite']=finite;client=Client();r=WorkloadReplay(c,client);r.tick(0);client.at(0)
        client.at(20);r.tick(20);s=r.summary(20)
        assert s['requests'][0]['state']==expected
        assert s['censored']==(0 if finite else 1)
        assert s['unsuccessful']==(1 if finite else 0)

def test_continuous_window_does_not_erase_an_earlier_deadline():
    c=case();c['finite']=False;c['requests']=c['requests'][:1];c['requests'][0].update(deadline_s=10,steps=[{'action':'wait','duration_s':30}])
    client=Client();r=WorkloadReplay(c,client);r.tick(0);client.at(20);r.tick(20)
    assert r.summary()['requests'][0]['state']=='deadline_unfinished' and r.summary()['censored']==0

def test_polling_after_continuous_cutoff_does_not_classify_a_later_finish():
    c=case();c['finite']=False;c['requests']=c['requests'][:1];c['requests'][0]['steps'][0]['duration_s']=21
    client=Client();r=WorkloadReplay(c,client);r.tick(0);client.at(0);client.at(22);r.tick(22);s=r.summary()
    assert s['censored']==1 and s['unsuccessful']==0 and s['unsuccessful_fraction'] is None
    assert s['requests'][0]['unfinished_wait_lower_bound_s']==20

def test_dependency_cycles_and_implicit_supersede_are_rejected():
    c=case();c['requests'][0]['depends_on']=['r2']
    with pytest.raises(ValueError):validate_case(c)
    c=case(policy='supersede')
    with pytest.raises(ValueError):validate_case(c)
    assert actor_cycle_seed(17,'a',0)==actor_cycle_seed(17,'a',0)!=actor_cycle_seed(17,'b',0)

def test_closed_loop_think_interval_is_measured_from_actual_finish():
    c=case('closed_loop');c['requests']=c['requests'][:2];c['requests'][1].update(depends_on=['r0'],think_s=2)
    client=Client();r=WorkloadReplay(c,client)
    for t in range(15):client.at(t);r.tick(t)
    first,second=r.summary()['requests']
    assert second['eligible_at_s']>=first['finished_at_s']+2

def test_frozen_cases_validate_against_published_schema():
    import json
    from pathlib import Path
    import jsonschema
    root=Path(__file__).resolve().parents[1];schema=json.loads((root/'schemas/benchmark.schema.json').read_text())
    cases=list((root/'benchmarks/workloads').glob('*.json'));assert len(cases)>=5
    for path in cases:
        c=json.loads(path.read_text());jsonschema.validate(c,schema);assert validate_case(c)==c

def test_replay_waits_for_physical_queue_cleanup_before_submitting_successor():
    c=case();client=Client();client.e.actors['a']['queue_cleanup']={'resource_id':'q'}
    replay=WorkloadReplay(c,client);replay.tick(0)
    assert replay.results['r0']['state']=='waiting' and replay.results['r0']['submitted_at_s'] is None
    client.e.actors['a'].pop('queue_cleanup');replay.tick(1)
    assert replay.results['r0']['state']=='admitted' and replay.results['r0']['submitted_at_s']==1
