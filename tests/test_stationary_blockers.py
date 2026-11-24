import copy

import pytest

from simpeople.core.stationary_blockers import stopped_blockers, settled_stop_receipt


def fixture():
    args = dict(requester='east', details={'blocker_handles': ['west', 'west', 'east']},
                instances={'west': {'traffic_instance_id': 'body1'},
                           'east': {'traffic_instance_id': 'body2'}},
                owner_routes={}, retained_stops={}, now=10.,
                observations={'west': (10., dict(ready=True, action='Idle',
                    observation_sim_time=10., speed_mps=0., position_m=[-1.2, -10.1, 0.],
                    native_task_id=7, position_source='BehaviorAgent.get_world_translation'))})
    obs = args['observations']['west'][1]
    stop = dict(body_generation='body1', stable_since=9.5, stable_samples=16,
                last_sample_time=10., last_position_m=list(obs['position_m']))
    args['instances']['west']['settled_stop_receipt'] = settled_stop_receipt(stop, obs, 'body1', 10.)
    return args


def test_current_idle_blocker_selects_search_only_without_mutating_inputs():
    args = fixture(); before = copy.deepcopy(args)
    assert stopped_blockers(**args) == [dict(handle='west', body_generation='body1',
                                            position_m=[-1.2, -10.1, 0.])]
    assert args == before


@pytest.mark.parametrize('fault', ['owned_route', 'retained_claim', 'missing_body',
    'stale_cache', 'stale_observation', 'moving', 'not_idle', 'unready',
    'static_xform', 'negative_speed', 'boolean_speed', 'nonfinite_position'])
def test_active_or_unreliable_blockers_do_not_enable_the_search(fault):
    args = fixture(); obs = args['observations']['west'][1]
    if fault == 'owned_route': args['owner_routes']['west'] = 'route1'
    if fault == 'retained_claim': args['retained_stops']['west'] = {'body_generation': 'body1'}
    if fault == 'missing_body': args['instances']['west']['traffic_instance_id'] = ''
    if fault == 'stale_cache': args['observations']['west'] = (9., obs)
    if fault == 'stale_observation': obs['observation_sim_time'] = 9.
    if fault == 'moving': obs['speed_mps'] = .15
    if fault == 'not_idle': obs['action'] = 'MoveAlong'
    if fault == 'unready': obs['ready'] = False
    if fault == 'static_xform': obs['position_source'] = 'USD_Xform'
    if fault == 'negative_speed': obs['speed_mps'] = -.01
    if fault == 'boolean_speed': obs['speed_mps'] = False
    if fault == 'nonfinite_position': obs['position_m'][0] = float('nan')
    assert stopped_blockers(**args) == []


@pytest.mark.parametrize('fault', ['nonfinite_clock', 'boolean_clock', 'malformed_handles'])
def test_invalid_search_snapshot_is_rejected(fault):
    args = fixture()
    if fault == 'nonfinite_clock': args['now'] = float('inf')
    if fault == 'boolean_clock': args['now'] = True
    if fault == 'malformed_handles': args['details']['blocker_handles'] = 'west'
    assert stopped_blockers(**args) == []


@pytest.mark.parametrize('fault', ['startup_idle', 'new_sdk_task', 'new_incarnation',
    'body_drifted', 'future_receipt', 'nonfinite_receipt', 'wrong_source'])
def test_only_the_same_verified_stopped_body_enables_a_detour(fault):
    args = fixture(); instance = args['instances']['west']
    receipt = instance['settled_stop_receipt']; obs = args['observations']['west'][1]
    if fault == 'startup_idle': instance.pop('settled_stop_receipt')
    if fault == 'new_sdk_task': obs['native_task_id'] = 8
    if fault == 'new_incarnation': instance['traffic_instance_id'] = 'body3'
    if fault == 'body_drifted': obs['position_m'][0] += .021
    if fault == 'future_receipt': receipt['settled_sim_time'] = 10.01
    if fault == 'nonfinite_receipt': receipt['position_m'][0] = float('nan')
    if fault == 'wrong_source': receipt['source'] = 'initial_idle'
    assert stopped_blockers(**args) == []


@pytest.mark.parametrize('fault', ['short_time', 'too_few_samples', 'old_sample',
    'wrong_body', 'static_root', 'moving', 'boolean_task', 'not_idle', 'position_mismatch'])
def test_receipt_cannot_replace_the_original_physical_settlement_gate(fault):
    args = fixture(); obs = args['observations']['west'][1]
    stop = dict(body_generation='body1', stable_since=9.5, stable_samples=16,
                last_sample_time=10., last_position_m=list(obs['position_m']))
    if fault == 'short_time': stop['stable_since'] = 9.51
    if fault == 'too_few_samples': stop['stable_samples'] = 15
    if fault == 'old_sample': stop['last_sample_time'] = 9.9
    if fault == 'wrong_body': stop['body_generation'] = 'body2'
    if fault == 'static_root': obs['position_source'] = 'USD_Xform'
    if fault == 'moving': obs['speed_mps'] = .15
    if fault == 'boolean_task': obs['native_task_id'] = True
    if fault == 'not_idle': obs['action'] = 'MoveAlong'
    if fault == 'position_mismatch': stop['last_position_m'][0] += .1
    assert settled_stop_receipt(stop, obs, 'body1', 10.) is None
