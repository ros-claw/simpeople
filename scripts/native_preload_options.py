"""Freeze an explicitly selected preload bundle before creating Native actors.

This selects a startup profile; existing runtime admission still checks every
clip and certificate. No assets, proofs or capability statuses are generated.
"""
import hashlib
import json
from pathlib import Path

from simpeople.motion.startup import validate_domain


def stage_generated_preload(inputs, config_dir, *, custom_actions, idle_profile, seed):
    if inputs is None:
        return None
    if custom_actions is not True or idle_profile != 'basic':
        raise ValueError('--generated-preload requires --custom-actions and --idle-profile basic')
    source = Path(inputs).resolve()
    data = {name: (source / name).read_bytes() for name in ['actions.json', 'acceptance.json']}
    registry = json.loads(data['actions.json'])
    acceptance = json.loads(data['acceptance.json'])
    if (not isinstance(registry, dict)
            or registry.get('schema_version') != 'simpeople.custom_actions.v1'
            or registry.get('registration_source') != 'fixed_cache_uris'
            or not isinstance(registry.get('actions'), dict) or not registry['actions']
            or not isinstance(acceptance, dict)):
        raise ValueError('a fixed-URI action registry and separate acceptance object are required')
    domains = []
    for entry in registry['actions'].values():
        if (not isinstance(entry, dict)
                or any(not isinstance(entry.get(k), str) or not entry[k].startswith('cache://')
                       for k in ['clip', 'skeleton'])):
            raise ValueError('generated preload entries require fixed cache URIs')
        reference = entry.get('canonical_entry')
        if not isinstance(reference, dict):
            raise ValueError('generated preload entries require their canonical entry contract')
        domain = validate_domain(reference.get('native_startup_conditions'))
        if type(seed) is not int or seed != domain['api_seed']:
            raise ValueError('requested seed differs from the generated preload startup domain')
        domains.append(domain)
    # Validate the entire bundle before replacing either snapshot config file.
    destination = Path(config_dir)
    paths = {'actions.json': 'custom_actions.json', 'acceptance.json': 'custom_action_acceptance.json'}
    for name, target in paths.items():
        (destination / target).write_bytes(data[name])
    return {
        'profile': 'experimental_cooperative_finite_preload',
        'source_directory': str(source),
        'input_sha256': {name: hashlib.sha256(value).hexdigest() for name, value in data.items()},
        'snapshot_files': list(paths.values()),
        'required_domains': domains,
        'execution_runtime_flags': {'cooperative_finite_stop': True},
        'precise_facing_enabled': True,
        'scope': 'Preloaded local inputs only. Runtime verifies each asset, source revision, '
                 'startup domain and proof. This receipt confers no action or rig qualification.',
    }
