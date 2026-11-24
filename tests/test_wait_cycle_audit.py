"""Synthetic diagnostic counterexamples, never native acceptance evidence."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from audit_wait_cycles import explain


@pytest.fixture
def journal():
    world = {'session_id': 'session', 'episode_id': 'episode'}
    tasks = [{**world, 'actor_id': a, 'actor_instance_id': a+'-instance',
              'control_epoch': 1, 'task_id': a+'-task'} for a in 'abc']
    events = []

    def emit(kind, actor=None, **payload):
        e = {**world, 'cursor': len(events)+1, 'sim_time': len(events)/30, 'kind': kind}
        if actor:
            e.update(tasks['abc'.index(actor)], agent='/'+actor, route_id=actor+'-route')
        e.update(payload)
        events.append(e)

    for a in 'abc':
        emit('traffic_route_started', a)
    emit('traffic_candidate_rejected', 'a', body_conflicts=[{'owner': '/c', 'distance_m': .3}],
         claim_conflicts=[], points_m=[[0, 0, 0], [4, 0, 0]])
    emit('traffic_fairness_deferred', 'b', older_route_ids=['a-route'], blocked_details={'physically_feasible': True},
         candidate_points_m=[[3, 0, 0], [3, 2, 0]])
    emit('traffic_fairness_deferred', 'c', older_route_ids=['b-route'], blocked_details={'physically_feasible': True},
         candidate_points_m=[[2, 0, 0], [2, 2, 0]])
    emit('traffic_wait_dependencies', edges=[['a', 'c'], ['c', 'b'], ['b', 'a']])
    emit('traffic_wait_cycle', members=['/a', '/b', '/c'])
    return events, tasks, world


def test_current_cycle_has_body_and_fairness_evidence_with_age(journal):
    result = explain(*journal)
    assert result['all_reported_traffic_cycles_corroborated']
    assert not result['release_gate_passed']
    edges = result['cycles'][0]['edges']
    assert {(e['source'], e['target']) for e in edges} == {('a', 'c'), ('c', 'b'), ('b', 'a')}
    assert {c['cause'] for e in edges for c in e['corroboration']} == {'physical_body', 'fairness_fence'}
    assert all(c['age_sim_s'] > 0 for e in edges for c in e['corroboration'])


@pytest.mark.parametrize('key,value', [('session_id', 'old-session'), ('episode_id', 'old-episode'),
                                    ('control_epoch', 0), ('actor_instance_id', 'recreated'),
                                    ('task_id', 'another-task')])
def test_stale_identity_cannot_explain_current_actor(journal, key, value):
    events, tasks, world = copy.deepcopy(journal)
    events[3][key] = value
    result = explain(events, tasks, world)
    assert result['identity_errors'] and not result['all_reported_traffic_cycles_corroborated']


@pytest.mark.parametrize('ending', ['traffic_route_cancelled', 'traffic_route_ended', 'traffic_route_started'])
def test_cancel_or_replaced_route_cannot_lend_old_candidate_evidence(journal, ending):
    events, tasks, world = copy.deepcopy(journal)
    e = {**world, 'cursor': 8, 'sim_time': .24, 'kind': ending, 'agent': '/a',
         'route_id': 'replacement' if ending == 'traffic_route_started' else 'a-route'}
    events.insert(-1, e)
    events[-1].update(cursor=9, sim_time=.3)
    assert not explain(events, tasks, world)['all_reported_traffic_cycles_corroborated']


def test_latest_graph_breaks_a_previously_reported_cycle(journal):
    events, tasks, world = copy.deepcopy(journal)
    events[-2]['edges'] = [['a', 'c'], ['b', 'a']]
    assert not explain(events, tasks, world)['all_reported_traffic_cycles_corroborated']


def test_empty_journal_cannot_pass_a_diagnostic_or_release_gate(journal):
    _, tasks, world = journal
    result = explain([], tasks, world)
    assert not result['all_reported_traffic_cycles_corroborated'] and not result['release_gate_passed']


def test_reordered_observations_are_rejected(journal):
    events, tasks, world = copy.deepcopy(journal)
    events[4]['cursor'] = events[3]['cursor']
    with pytest.raises(ValueError, match='reordered'):
        explain(events, tasks, world)


def test_unbound_cleanup_is_retained_without_borrowing_task_or_invalidating_other_cycle(journal):
    events, tasks, world = copy.deepcopy(journal)
    events.append({**world, 'cursor': 9, 'sim_time': 1, 'kind': 'traffic_candidate_rejected',
                   'agent': '/cleanup', 'route_id': 'cleanup'})
    result = explain(events, tasks, world)
    assert result['all_reported_traffic_cycles_corroborated'] and not result['identity_errors']
    assert len(result['unbound_candidate_events']) == 1


def test_supervisor_cycle_report_is_retained_separately_from_native_graph(journal):
    events, tasks, world = copy.deepcopy(journal)
    events.append({**world, 'cursor': 9, 'sim_time': 1, 'kind': 'task_wait_cycle', 'members': ['a', 'b', 'c']})
    result = explain(events, tasks, world)
    assert len(result['cycles']) == len(result['supervisor_task_cycle_events']) == 1
    assert result['all_reported_traffic_cycles_corroborated']
