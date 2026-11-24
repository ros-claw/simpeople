"""Compare a declared native preload domain with observed process settings.

No Kit imports, seed setters, pose writes or capability promotion here.
"""
import copy
import math

SCHEMA = 'simpeople.native-motion-startup.v1'
FIELDS = {'schema_version', 'idle_tags', 'response_time_s',
          'response_random_offset_s', 'nav_blocked_timeout_s', 'api_seed'}


def validate_domain(domain):
    if not isinstance(domain, dict) or set(domain) != FIELDS or domain['schema_version'] != SCHEMA:
        raise ValueError('complete native motion startup domain required')
    if domain['idle_tags'] != ['Idle']:
        raise ValueError('only the audited basic Idle startup domain is supported')
    for key, expected in [('response_time_s', 1 / 30), ('response_random_offset_s', 0),
                          ('nav_blocked_timeout_s', 3)]:
        value = domain[key]
        if (isinstance(value, bool) or not isinstance(value, (float, int))
                or not math.isfinite(value) or abs(value - expected) > 1e-12):
            raise ValueError('unsupported native startup bound: ' + key)
    seed = domain['api_seed']
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2 ** 32:
        raise ValueError('native startup seed must be an unsigned 32-bit integer')
    return copy.deepcopy(domain)


def startup_error(actual, domain):
    domain = validate_domain(domain)
    errors = []
    if not isinstance(actual, dict):
        return {'passed': False, 'errors': ['native startup readback absent']}
    tags = actual.get('idle_tags')
    if not isinstance(tags, (list, tuple)) or list(tags) != domain['idle_tags']:
        errors.append('native Idle menu outside declared startup domain')
    for key in ['response_time_s', 'response_random_offset_s', 'nav_blocked_timeout_s']:
        value = actual.get(key)
        tolerance = 1e-8 if key == 'response_time_s' else 0
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or abs(value - domain[key]) > tolerance):
            errors.append('native setting outside declared startup domain: ' + key)
    seed = actual.get('seed_configuration')
    if (not isinstance(seed, dict) or set(seed) != {'api_seed', 'configured_before_agents', 'configured_on_owner_thread'}
            or isinstance(seed.get('api_seed'), bool) or not isinstance(seed.get('api_seed'), int)
            or seed['api_seed'] != domain['api_seed']
            or seed.get('configured_before_agents') is not True
            or seed.get('configured_on_owner_thread') is not True):
        errors.append('owned startup seed configuration absent or outside declared domain')
    return {'passed': not errors, 'errors': errors, 'required_domain': domain,
            'observed_settings': copy.deepcopy(actual),
            'scope': 'Actual settings plus provenance of the main-thread SDK seed call before actors. '
                     'No SDK seed getter, deterministic-execution or generated-rig qualification claim.'}
