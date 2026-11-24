"""Reject fabricated/stale readbacks; these synthetic rows are not Native proof."""
import copy
import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('arrival_audit', Path(__file__).parents[1]/'scripts/audit_arrival_recovery_prefix.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


@pytest.fixture
def frame():
    bindings = {}; actors = {}
    for i in range(1, 31):
        aid = f'person_{i:03d}'; p = [float(i), 0., 0.]
        b = {'actor_instance_id': 'i_'+aid, 'traffic_body_instance_id': 'b_'+aid, 'native_actor_prim_path': '/'+aid,
             'control_epoch': 1, 'task_id': 't_'+aid, 'sdk_enabled': True, 'read_errors': [],
             'observation_ready': True, 'observation_sim_time': 1., 'actual_sdk_position_m': p,
             'actual_sdk_task_id': 0, 'actual_sdk_task_name': 'Idle'}
        bindings[aid] = b
        if i not in {1, 20}: continue
        task = {'actor_id': aid, 'actor_instance_id': b['actor_instance_id'], 'control_epoch': 1,
                'task_id': b['task_id'], 'session_id': 's', 'episode_id': 'e', 'status': 'running'}
        obs = {'ready': True, 'position_source': 'BehaviorAgent.get_world_translation', 'observation_sim_time': 1.,
               'position_m': list(p), 'speed_mps': 0., 'action': 'Idle', 'native_task_id': 0,
               'joints_m': {'Hips': [p[0], 0., .95], 'LeftFoot': [p[0]-.1, 0., .1], 'RightFoot': [p[0]+.1, 0., .1]},
               'facing_direction': [1, 0, 0]}
        actors[aid] = {'binding': b, 'observation': obs, 'task': task, 'route_id': 'r_'+aid,
            'route': {'handle': b['native_actor_prim_path'], 'segment_goal': [p[0]+12, 0., 0.], 'native_task_id': 8},
            'native_status': {'8': 'succeeded', '9': 'running'}, 'native_elapsed_s': {'8': .0666667, '9': 1.}}
    identity = {'source_tick': 0, 'relative_sim_time': 0.}
    row = {'sim_time': 1., 'frame_identity': identity, 'session_id': 's', 'episode_id': 'e',
           'timeline_playing': True, 'arrival_recovery_enabled': True, 'body_bindings': bindings, 'actors': actors}
    return row, {'frame_identity': identity, 'sim_time': 1.}


def test_complete_actual_binding_contract_has_no_implied_qualification(frame):
    row, stamp = frame
    assert len(module.check_frame(row, stamp, True, set(row['body_bindings']))) == 30


@pytest.mark.parametrize('fault', ['stale', 'missing_body', 'duplicate_body', 'disabled_body', 'read_error', 'no_root',
                                 'wrong_mode', 'paused', 'wrong_rgb', 'wrong_task', 'wrong_route'])
def test_native_frame_contract_rejects_false_or_borrowed_state(frame, fault):
    row, stamp = frame; aid = 'person_020'; b = row['body_bindings'][aid]; actor = row['actors'][aid]
    if fault == 'stale': b['observation_sim_time'] = 0.
    elif fault == 'missing_body': row['body_bindings'].pop('person_030')
    elif fault == 'duplicate_body': b['traffic_body_instance_id'] = row['body_bindings']['person_001']['traffic_body_instance_id']
    elif fault == 'disabled_body': b['sdk_enabled'] = False
    elif fault == 'read_error': b['read_errors'].append({'error': 'missing SDK'})
    elif fault == 'no_root': b['actual_sdk_position_m'] = None
    elif fault == 'wrong_mode': row['arrival_recovery_enabled'] = False
    elif fault == 'paused': row['timeline_playing'] = False
    elif fault == 'wrong_rgb': stamp['sim_time'] = 2.
    elif fault == 'wrong_task': actor['task']['control_epoch'] = 2
    else: actor['route']['handle'] = '/another'
    with pytest.raises((ValueError, KeyError)):
        module.check_frame(row, stamp, True, {f'person_{i:03d}' for i in range(1, 31)})


def window_example(frame, stop=False):
    row, _ = frame; rows = []
    for i in range(16):
        current = copy.deepcopy(row); now = 1+i/30; current['sim_time'] = now
        a = current['actors']['person_020']; a['observation']['observation_sim_time'] = now
        a['binding']['observation_sim_time'] = now
        if stop: a['observation']['native_task_id'] = a['binding']['actual_sdk_task_id'] = 9
        rows.append(current)
    a = rows[-1]['actors']['person_020']; identity = [a['binding']['native_actor_prim_path'], a['binding']['traffic_body_instance_id'], a['route_id'], 8, [32., 0., 0.]]
    event = {'sim_time': 1.5, 'actor': a}
    return rows[:-1], event, {'since': 1., 'last': 1.5, 'count': 16, 'identity': identity}


@pytest.mark.parametrize('stop', [False, True])
def test_direct_event_snapshot_supplies_last_real_sample_before_or_after_stop(frame, stop):
    rows, event, window = window_example(frame, stop)
    assert len(module.verify_window(rows, event, window, 'person_020', 8, 9 if stop else None)) == 16


@pytest.mark.parametrize('fault', ['gap', 'count', 'stale', 'other_sdk', 'other_epoch', 'moving', 'not_standing',
                                 'not_succeeded', 'actual_root_differs', 'another_route', 'elapsed_zero', 'deadline', 'goals'])
def test_invalid_stop_or_confirmation_window_cannot_authorize_claim_release(frame, fault):
    rows, event, window = window_example(frame, True); a = rows[7]['actors']['person_020']
    if fault == 'gap': rows[7]['sim_time'] += .01
    elif fault == 'count': window['count'] = 99
    elif fault == 'stale': a['observation']['observation_sim_time'] = 0
    elif fault == 'other_sdk': a['binding']['actual_sdk_task_id'] = 0
    elif fault == 'other_epoch': a['binding']['control_epoch'] = 2
    elif fault == 'moving': a['observation']['speed_mps'] = .15
    elif fault == 'not_standing': a['observation']['joints_m']['Hips'][2] = .5
    elif fault == 'not_succeeded': a['native_status']['8'] = 'running'
    elif fault == 'actual_root_differs': a['binding']['actual_sdk_position_m'][0] += 1
    elif fault == 'another_route': event['actor']['route_id'] = 'another'
    elif fault == 'deadline': a['task']['step_deadline_sim_time'] = 999
    elif fault == 'goals': a['task']['steps'] = [{'action': 'move_to', 'target': [999, 0, 0]}]
    else: a['native_elapsed_s']['9'] = 0
    with pytest.raises(ValueError): module.verify_window(rows, event, window, 'person_020', 8, 9)


@pytest.mark.parametrize('motion', ['static_body_sliding', 'idle_drift', 'real_articulation'])
def test_sdk_movement_and_articulated_body_are_required_for_local_resume(frame, motion):
    row, _ = frame; rows = []
    for i in range(40):
        r = copy.deepcopy(row); r['sim_time'] = 1+i/30; a = r['actors']['person_020']; o = a['observation']; b = a['binding']
        x = 20+i*.04; o['position_m'] = [x, 0, 0]; b['actual_sdk_position_m'] = [x, 0, 0]
        o['observation_sim_time'] = r['sim_time']; o['speed_mps'] = 1.2
        o['native_task_id'] = b['actual_sdk_task_id'] = 10
        o['action'] = b['actual_sdk_task_name'] = 'Idle' if motion == 'idle_drift' else 'MoveTo'
        a['native_elapsed_s']['10'] = .1+i/30
        for k in ['LeftFoot', 'RightFoot']: o['joints_m'][k] = [x+(.1 if k == 'LeftFoot' else -.1), 0, .1]
        if motion == 'real_articulation': o['joints_m']['LeftFoot'][0] += .1*(i%7)/7
        rows.append(r)
    result = module.movement(rows, 'person_020', {10}, required_name='MoveTo')
    assert module.resume_criteria(result) == (motion == 'real_articulation')


def test_missing_native_artifacts_never_qualify(tmp_path):
    result = module.audit(tmp_path, tmp_path, tmp_path/'case', tmp_path/'probe', tmp_path/'trace', tmp_path)
    assert not result['measurement_verified'] and not result['native_local_resume_verified']


def test_shared_driver_can_omit_only_three_unexecuted_source_scripts():
    source = {'src/executed.py': 'actual', 'scripts/kit_main.py': 'other-entry'}
    module.verify_candidate_snapshot(source, {'src/executed.py': 'actual'})
    with pytest.raises(ValueError): module.verify_candidate_snapshot(source, {})
    with pytest.raises(ValueError): module.verify_candidate_snapshot(source, {'src/executed.py': 'changed'})
    with pytest.raises(ValueError): module.verify_candidate_snapshot(source, {'src/executed.py': 'actual', 'scripts/kit_main.py': 'changed'})
