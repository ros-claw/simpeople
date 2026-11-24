import copy
import importlib.util
import json
import math
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('legacy_return', Path(__file__).parents[1]/'scripts/audit_legacy_return.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


@pytest.fixture
def example():
    step = {'action': 'move_to', 'target': [1.5, 0, 0], 'gait': 'walk', 'timeout_s': 15}
    actor = {'actor_id': 'a', 'move_target_m': [1.5, 0, 0]}
    task = {'actor_id': 'a', 'status': 'succeeded', 'task_id': 't', 'session_id': 's', 'episode_id': 'e',
            'actor_instance_id': 'i', 'control_epoch': 1, 'steps': [{'action': 'custom_action'}, step]}
    def event(kind, when, **kw):
        return {'kind': kind, 'sim_time': when, 'actor_id': 'a', 'task_id': 't', 'session_id': 's', 'episode_id': 'e', **kw}
    events = [event('step_started', 0, index=1, step=step), event('step_ended', 2, index=1),
              event('traffic_route_started', 0, agent='/A', route_id='r'),
              event('traffic_native_started', 0, route_id='r', native_task_id=2, action='move_to'),
              event('native_task_bound', -25, native_task_id=1)]
    rows = []
    for i in range(61):
        x = min(i/30, 1.5)
        rows.append({**task, 'sim_time': i/30, 'observation_sim_time': i/30, 'position_m': [x, 0, 0],
                     'position_source': 'BehaviorAgent.get_world_translation', 'ready': True,
                     'native_actor_prim_path': '/A', 'traffic_body_instance_id': 'b', 'facing_direction': [1, 0, 0],
                     'native_task_id': 2, 'action': 'MoveTo', 'joints_m': {
                         'LeftFoot': [x+math.sin(i*.4)*.2, .1, .05],
                         'RightFoot': [x-math.sin(i*.4)*.2, -.1, .05]}})
    return task, actor, rows, events


def test_actual_sdk_return_and_stationary_window(example):
    result = module.measure_return(*example)
    assert result['actual_samples'] == 61
    assert result['max_displacement_from_move_start_m'] == pytest.approx(1.5)
    assert result['longest_continuous_moving_sdk_sim_s'] == pytest.approx(1.5)
    assert result['final_stationary_window_s'] == pytest.approx(.5)
    assert result['native_movement_task_ids'] == [2]


def test_continuous_corridor_receipt_requires_measured_movealong(example):
    task,actor,rows,events=example
    command=next(e for e in events if e['kind']=='traffic_native_started')
    command.update(action='continuous_corridor',points_m=[[0,0,0],[1.5,0,0]])
    for row in rows:row['action']='MoveAlong'
    assert module.measure_return(*example)['native_movement_task_ids']==[2]
    command['points_m']=[[0,0,float('nan')],[1.5,0,0]]
    with pytest.raises(ValueError,match='finite route points'):module.measure_return(*example)


@pytest.mark.parametrize('bad', ['still_clip', 'wrong_sdk', 'borrowed_body', 'stale', 'epoch', 'duplicate', 'gap',
                                'missing_boundary', 'no_command', 'reused_id', 'static_pose', 'missing_foot',
                                'deadline', 'changed_goal', 'unstable_arrival', 'borrowed_event', 'no_identity'])
def test_false_return_is_rejected(example, bad):
    task, actor, rows, events = example
    if bad == 'still_clip':
        for r in rows: r['action'] = 'custom_clip'
    elif bad == 'wrong_sdk':
        for r in rows: r['native_task_id'] = 99
    elif bad == 'borrowed_body': rows[20]['traffic_body_instance_id'] = 'new'
    elif bad == 'stale': rows[20]['observation_sim_time'] -= 1/30
    elif bad == 'epoch': rows[20]['control_epoch'] = 2
    elif bad == 'duplicate': rows.insert(20, copy.deepcopy(rows[20]))
    elif bad == 'gap': rows.pop(20)
    elif bad == 'missing_boundary': rows.pop()
    elif bad == 'no_command': events[:] = [e for e in events if e['kind'] != 'traffic_native_started']
    elif bad == 'reused_id': events[-1]['native_task_id'] = 2
    elif bad == 'static_pose':
        for r in rows:
            x = r['position_m'][0]; r['joints_m'] = {'LeftFoot': [x, .1, .05], 'RightFoot': [x, -.1, .05]}
    elif bad == 'missing_foot': rows[20]['joints_m'].pop('LeftFoot')
    elif bad == 'deadline': events[1]['sim_time'] = 16
    elif bad == 'changed_goal': actor['move_target_m'] = [10, 0, 0]
    elif bad == 'unstable_arrival':
        for r in rows[46:]: r['position_m'][0] += (r['sim_time']-1.5)*.4
    elif bad == 'borrowed_event': events[0]['episode_id'] = 'other'
    else: task['session_id'] = None
    with pytest.raises(ValueError): module.measure_return(*example)


def test_rigidly_turning_static_pose_does_not_mimic_leg_motion(example):
    task, actor, rows, events = example
    for i, r in enumerate(rows):
        angle = i*.02; c, s = math.cos(angle), math.sin(angle); x = r['position_m'][0]
        r['facing_direction'] = [c, s, 0]
        r['joints_m'] = {'LeftFoot': [x-.1*s, .1*c, .05], 'RightFoot': [x+.1*s, -.1*c, .05]}
    with pytest.raises(ValueError, match='static pose'): module.measure_return(*example)


@pytest.fixture
def startup_example():
    tags = ['Idle', 'look_left']
    settings = {'startup_profile': {'mode': 'default', 'original_tags': tags, 'active_tags': tags.copy()},
                'requested_api_seed': 42, 'active_response': {
                    '/exts/omni.anim.behavior.core/'+k: v for k, v in
                    [('agentResponseTime', 1/30), ('agentResponseTimeMaxRandomOffset', 0), ('navBlockedTimeout', 3)]}}
    return settings, tags


def test_actual_default_startup_contract(startup_example):
    module.startup(*startup_example)


@pytest.mark.parametrize('bad', ['menu', 'profile', 'seed', 'jitter', 'nan_response'])
def test_changed_startup_never_transfers_default_proof(startup_example, bad):
    settings, tags = startup_example
    if bad == 'menu': settings['startup_profile']['active_tags'] = ['Idle']
    elif bad == 'profile': settings['startup_profile']['mode'] = 'basic'
    elif bad == 'seed': settings['requested_api_seed'] = 17
    elif bad == 'jitter': settings['active_response']['/exts/omni.anim.behavior.core/agentResponseTimeMaxRandomOffset'] = .1
    else: settings['active_response']['/exts/omni.anim.behavior.core/agentResponseTime'] = float('nan')
    with pytest.raises(ValueError): module.startup(settings, tags)


def test_missing_original_review_cannot_qualify(tmp_path):
    result = module.audit(tmp_path, ['Idle'])
    assert not result['verified'] and result['errors']


def test_another_runs_successful_grade_cannot_transfer(tmp_path):
    (tmp_path/'legacy_regression_independent_review.json').write_text(json.dumps({'run_id': 'another', 'verified': True}))
    result = module.audit(tmp_path, ['Idle'])
    assert not result['verified']
    assert result['errors'] == ['original independent legacy review must pass first']
