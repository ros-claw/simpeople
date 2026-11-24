"""Synthetic independent checks, not a native recovery acceptance fixture."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from audit_local_yield import actual_window, footprint, review, swept_cells


def fixture():
    f = dict(session_id='s', episode_id='e', actor_id='b', actor_instance_id='bi', task_id='bt', control_epoch=1)
    path = [[0, 0, 0], [0, 2.5, 0]]; goal = [2.5, 0, 0]; cells = sorted(swept_cells(path, 1.25, .45))
    start = {**f, 'route_id': 'r', 'agent': '/b', 'body_instance_id': 'body-b', 'native_task_id': 99,
             'sim_time': 10., 'points_m': path, 'reserved_cells': cells}
    ticket = dict(key='r', actor='/b', since=1., sequence=2, wait_since=1., cells=[[0, 0], [1, 0]],
                  goal_cells=[[2, 0]], drainers=[], occupant_token='body-b', origin_cells=[[0, 0]],
                  scope='corridor', state='waiting', conflicting_bypasses=0)
    old = {**copy.deepcopy(ticket), 'key': 'old', 'actor': '/a', 'since': 0, 'sequence': 1,
           'drainers': ['body-b'], 'occupant_token': 'body-a'}
    roots = {}; rows = []
    for i in range(300, 481):
        t = i/30
        y = min(2.5, (t-10)*1.25) if t <= 12.5 else 2.5*(1-min(1, (t-12.5)/3))
        x = 0 if t <= 12.5 else 2.5*min(1, (t-12.5)/3)
        r = {**f, 'sim_time': t, 'ready': True, 'position_m': [x, y, 0], 'speed_mps': 0 if t >= 12 else 1.25,
             'action': 'MoveAlong' if 10 < t < 12 else 'Idle', 'native_task_id': 99 if 10 < t < 12 else 0,
             'position_source': 'BehaviorAgent.get_world_translation', 'native_actor_prim_path': '/b',
             'traffic_body_instance_id': 'body-b', 'requested_step': {'target': goal}}
        rows.append(r)
    for time in [10., 12.5]:
        b = next(r for r in rows if r['sim_time'] == time)
        roots[round(time, 7)] = {'b': b, 'a': {**b, 'actor_id': 'a', 'position_m': [-3, 0, 0],
            'native_actor_prim_path': '/a', 'traffic_body_instance_id': 'body-a', 'native_task_id': 0, 'action': 'Idle'}}
    phases = {}
    for name, time in [('before_admission', 10.), ('native_submitted', 10.), ('original_goal_restored', 12.5)]:
        actors = {h: dict(actor_id=a, traffic_body_instance_id='body-'+a, cached_position_m=roots[time][a]['position_m'],
                    observation_at_tick_start={'position_m': roots[time][a]['position_m'], 'native_task_id': 0,
                                               'action': 'Idle', 'observation_sim_time': time}) for h, a in [('/a', 'a'), ('/b', 'b')]}
        route = {'goals': [goal], 'step': {'target': goal}}
        if name == 'native_submitted': route['local_yield'] = {'body_generation': 'body-b', 'path_m': path, 'deadline_sim_time': 18.}
        snap = dict(schema_version='simpeople.route-repair-snapshot.v1', complete_serialization=True,
            sim_time=time, actors=actors, nonfinite_value_paths=[], unsupported_value_paths=[],
            repair_context={'agent': '/b', 'route_id': 'r', 'phase': name},
            active_route_state={'r': route}, fair_gate={'pending': {'r': copy.deepcopy(ticket), 'old': copy.deepcopy(old)}},
            grid={'cell_m': 1.25, 'margin_m': .45, 'claims': {'/b': cells} if name == 'native_submitted' else {}})
        phases[name] = {**f, 'sim_time': time, 'snapshot': snap}
    motion = [{**f, 'agent': '/b', 'native_task_id': 99, 'sim_time': 10.2, 'actual_position_m': [0, .25, 0]}]
    end = {**f, 'agent': '/b', 'status': 'succeeded', 'sim_time': 12.5}
    events = [{'kind': 'step_started', 'task_id': 'bt', 'cursor': 1, 'index': 0, 'sim_time': 0., 'step': {'timeout_s': 30}},
              {'kind': 'recovery_attempt', 'task_id': 'bt', 'cursor': 2, 'sim_time': 10.,
               'recovery': {'deadline_sim_time': 30., 'result': {'strategy': 'bounded_local_yield_then_original_goal'}}},
              {'kind': 'step_ended', 'task_id': 'bt', 'index': 0, 'sim_time': 16.}]
    task = {**f, 'recovery_attempts': [{}]}; spec = {'on_blocked': 'replan_or_report'}
    return start, phases, motion, end, rows, roots, events, task, spec


def test_original_goal_and_same_owned_body_must_actually_finish_after_yield():
    result = review(*fixture())
    assert result['verified'] and not result['errors']
    assert result['actual_settlement_samples'] == 16
    assert result['original_goal_completed_sim_time'] == 16


@pytest.mark.parametrize('fault', ['report_only', 'wait_reset', 'priority_reset', 'old_goal_changed',
                                  'foreign_claim', 'drainer_recreated', 'partial_escape', 'bad_body_stream',
                                  'old_epoch', 'wrong_task', 'phase_gap', 'wrong_motion', 'false_stop',
                                  'no_original_goal', 'deadline_reset', 'third_attempt', 'moving_action_at_stop'])
def test_labels_cannot_substitute_for_actual_ownership_goal_and_budget(fault):
    args = list(copy.deepcopy(fixture()))
    if fault == 'report_only': args[-1]['on_blocked'] = 'report'
    elif fault == 'wait_reset': args[1]['native_submitted']['snapshot']['fair_gate']['pending']['r']['wait_since'] = 10
    elif fault == 'priority_reset': args[1]['original_goal_restored']['snapshot']['fair_gate']['pending']['r']['since'] = 10
    elif fault == 'old_goal_changed': args[1]['original_goal_restored']['snapshot']['active_route_state']['r']['goals'] = [[0, 2.5, 0]]
    elif fault == 'foreign_claim': args[1]['before_admission']['snapshot']['grid']['claims']['/other'] = [[0, 1]]
    elif fault == 'drainer_recreated': args[1]['before_admission']['snapshot']['fair_gate']['pending']['old']['drainers'] = ['former-body']
    elif fault == 'partial_escape': args[1]['before_admission']['snapshot']['fair_gate']['pending']['old']['cells'].append([0, 2])
    elif fault == 'bad_body_stream': args[4][30]['traffic_body_instance_id'] = 'recreated'
    elif fault == 'old_epoch': args[4][30]['control_epoch'] = 0
    elif fault == 'wrong_task': args[4][30]['task_id'] = 'replacement'
    elif fault == 'phase_gap': args[4].pop(30)
    elif fault == 'wrong_motion': args[2][0]['native_task_id'] = 100
    elif fault == 'false_stop': args[4][74]['position_m'] = [0, 2, 0]
    elif fault == 'no_original_goal': args[6].pop()
    elif fault == 'deadline_reset': args[6][1]['recovery']['deadline_sim_time'] = 40
    elif fault == 'moving_action_at_stop': args[4][65]['action'] = 'MoveAlong'
    else: args[7]['recovery_attempts'] = [{}, {}, {}]
    result = review(*args)
    assert not result['verified'] and result['errors']


def test_closed_diagonal_sweep_includes_corner_cells_and_actual_window_cannot_borrow_no_identity():
    assert footprint([0, 0, 0], 1.25, .45) == {(0, 0)}
    assert {(0, 0), (1, 1), (2, 2)} <= swept_cells([[0, 0, 0], [2.5, 2.5, 0]], 1.25, .45)
    _, passed = actual_window([{'sim_time': 0., 'ready': True}], 0., 0., {})
    assert not passed


def test_planned_target_exit_does_not_substitute_for_actual_settled_body_exit():
 args=list(copy.deepcopy(fixture()))
 for phase in args[1].values():phase['snapshot']['fair_gate']['pending']['old']['cells'].append([0,1])
 for row in args[4]:
  if 12<=row['sim_time']<=12.5:row['position_m']=[0,2.25,0]
 result=review(*args)
 assert not result['verified']
 assert 'actual settled body has not left every older protected fence' in result['errors']
