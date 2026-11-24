"""CPU domain rejection only; no Native SDK acceptance inferred."""
import copy
import pytest
from simpeople.motion.startup import SCHEMA, startup_error, validate_domain


def fixture():
    domain = {'schema_version': SCHEMA, 'idle_tags': ['Idle'], 'response_time_s': 1 / 30,
              'response_random_offset_s': 0, 'nav_blocked_timeout_s': 3, 'api_seed': 42}
    actual = {k: copy.deepcopy(domain[k]) for k in ['idle_tags', 'response_time_s',
              'response_random_offset_s', 'nav_blocked_timeout_s']}
    actual['seed_configuration'] = {'api_seed': 42, 'configured_before_agents': True,
                                    'configured_on_owner_thread': True}
    return actual, domain


def test_settings_and_owned_startup_call_are_required_and_detached():
    actual, domain = fixture(); before = copy.deepcopy((actual, domain))
    result = startup_error(actual, domain); assert result['passed']
    result['required_domain']['idle_tags'].append('IdleGroove')
    result['observed_settings']['seed_configuration']['api_seed'] = 17
    assert (actual, domain) == before


@pytest.mark.parametrize('changes', [
    {'idle_tags': ['Idle', 'IdleGroove']}, {'idle_tags': None},
    {'response_time_s': .3}, {'response_time_s': float('nan')},
    {'response_time_s': True}, {'response_random_offset_s': 1e-12},
    {'response_random_offset_s': float('inf')}, {'nav_blocked_timeout_s': 1},
    {'seed_configuration': None}, {'seed_configuration': {'api_seed': 42}},
    {'seed_configuration': {'api_seed': True, 'configured_before_agents': True, 'configured_on_owner_thread': True}},
    {'seed_configuration': {'api_seed': 17, 'configured_before_agents': True, 'configured_on_owner_thread': True}},
    {'seed_configuration': {'api_seed': 42, 'configured_before_agents': False, 'configured_on_owner_thread': True}},
    {'seed_configuration': {'api_seed': 42, 'configured_before_agents': True, 'configured_on_owner_thread': False}},
])
def test_unsupported_or_unobserved_startup_cannot_borrow_a_valid_body_entry(changes):
    actual, domain = fixture(); actual.update(changes)
    assert not startup_error(actual, domain)['passed']


@pytest.mark.parametrize('changes', [
    {'schema_version': 'other'}, {'idle_tags': ['IdleGroove']},
    {'response_time_s': .3}, {'response_random_offset_s': .1},
    {'nav_blocked_timeout_s': 1}, {'api_seed': True}, {'api_seed': -1},
    {'api_seed': 2 ** 32}, {'eval': 'code'},
])
def test_registry_cannot_silently_widen_startup_bounds(changes):
    _, domain = fixture(); domain.update(changes)
    with pytest.raises(ValueError): validate_domain(domain)


def test_carbs_single_precision_response_time_is_compared_with_bounded_precision():
    actual, domain = fixture(); actual['response_time_s'] = 0.03333333507180214
    assert startup_error(actual, domain)['passed']
    actual['response_time_s'] += 1e-7
    assert not startup_error(actual, domain)['passed']
