"""Audit fixed-cache registration repeatability, independently of playback quality.

Reads actual register() outputs and frozen run snapshots. Does not certify that
SDK playback, cancellation, or a generated rig passed animation acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if __name__ == '__main__':
    sys.path.insert(0, str(ROOT / 'src'))
from simpeople.core.asset_paths import resolve_asset_path

SOURCE_CONTRACTS = {
    'quality_contract': 'core/clip_quality.py',
    'entry_contract': 'motion/entry.py',
    'startup_contract': 'motion/startup.py',
    'native_adapter': 'backends/native/adapter.py',
    'engine': 'core/engine.py',
    'precise_facing_contract': 'core/facing_runtime.py',
    'custom_stop_contract': 'backends/native/custom_stop.py',
    'action_space': 'core/action_space.py',
    'reservations': 'backends/native/reservations.py',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inspect_run(run, workspace):
    snap = run / 'source_snapshot'
    manifest = read(run / 'source_manifest.json')
    require(isinstance(manifest, dict) and manifest, 'missing snapshot manifest')
    for relative, expected in manifest.items():
        path = Path(relative)
        require(not path.is_absolute() and '..' not in path.parts, 'unsafe snapshot path')
        require(sha(snap / path) == expected, 'snapshot digest mismatch: ' + relative)
    actual_files = {str(p.relative_to(snap)) for p in snap.rglob('*')
                    if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
    require(actual_files == set(manifest), 'snapshot manifest omits or invents files')
    declaration = read(snap / 'configs/custom_actions.json')
    require(isinstance(declaration, dict), 'invalid registry declaration')
    require(declaration.get('registration_source') == 'fixed_cache_uris', 'not a fixed URI registry')
    declared = declaration['actions']
    actual = read(run / 'custom_actions/registry.json')
    receipt = read(run / 'actual_fixed_registration.json')
    require(all(isinstance(v, dict) for v in [declared, actual, receipt]), 'invalid registry objects')
    require(bool(declared) and set(declared) == set(actual) == set(receipt), 'action set mismatch')
    sources = {k: v for k, v in manifest.items() if k.startswith('src/')}
    required_hashes = set(SOURCE_CONTRACTS) | {'skeleton', 'clip', 'registration', 'imported_clip'}
    for name, entry in declared.items():
        observed, record = actual[name], receipt[name]
        require(all(isinstance(v, dict) for v in [entry, observed, record]), 'invalid registered entry')
        require(entry.get('playback_mode') == 'out_and_back', 'unsupported registration audit mode')
        require(observed.get('status') == 'discovered' and observed.get('prim_paths'), 'registration not discovered')
        for key, value in entry.items():
            require(observed.get(key) == value, 'registered entry was rewritten: ' + name + '/' + key)
        proofs = observed['source_sha256']
        require(isinstance(proofs, dict), 'invalid source hashes')
        require(set(proofs) == required_hashes, 'unsupported or incomplete source hash contract')
        require(record['source_sha256'] == proofs, 'receipt and SDK registry differ')
        for key in ['clip', 'skeleton']:
            uri = entry[key]
            require(isinstance(uri, str) and uri.startswith('cache://'), 'not a fixed cache URI')
            require(record['literal_' + key] == uri, 'literal registration URI mismatch')
            path = Path(resolve_asset_path(uri, workspace))
            require(Path(record['resolved_' + key]) == path, 'resolved registration path mismatch')
            require(sha(path) == proofs[key], 'fixed asset bytes changed: ' + key)
        require(proofs['imported_clip'] == proofs['clip'], 'out-and-back imported source differs')
        registration = hashlib.sha256((snap / 'src/simpeople/backends/native/custom_actions.py').read_bytes()
                                      + json.dumps(entry, sort_keys=True).encode()).hexdigest()
        require(proofs['registration'] == registration, 'registration digest mismatch')
        for field, relative in SOURCE_CONTRACTS.items():
            require(sha(snap / 'src/simpeople' / relative) == proofs[field], 'source contract mismatch: ' + field)
    return {'receipt': receipt, 'actual': actual, 'sources': sources, 'declared': declaration}


def audit(first, second, workspace):
    first, second, workspace = map(lambda p: Path(p).resolve(), [first, second, workspace])
    result = {'method_version': 'simpeople.fixed-cache-registration-repeat.v1',
              'first_run': first.name, 'second_run': second.name,
              'verified': False, 'errors': [], 'native_playback_verified': False,
              'qualified_generated_native_rigs': [],
              'scope': 'Fixed-cache out-and-back registration and complete source proof repeatability only; no playback, cancellation, rig or product qualification.'}
    try:
        require(first != second, 'two independent run directories required')
        done = read(second / 'completed.json')
        require(done.get('harness_completed') is True and done.get('registration_only') is True
                and done.get('native_animation_playback_tested') is False, 'second registration-only run did not close')
        a, b = inspect_run(first, workspace), inspect_run(second, workspace)
        require(a['sources'] == b['sources'], 'frozen runtime sources differ')
        require(a['declared'] == b['declared'], 'declared registries differ')
        require(a['receipt'] == b['receipt'], 'actual registration proofs or paths differ')
        for name in a['actual']:
            require(a['actual'][name]['runtime_revision'] == b['actual'][name]['runtime_revision'], 'SDK revisions differ')
        result.update(verified=True, registered_actions=len(a['actual']),
                      source_files=len(a['sources']),
                      receipt_sha256=sha(first / 'actual_fixed_registration.json'),
                      inputs_sha256={str(p): sha(p) for run in [first, second]
                                     for p in [run / 'actual_fixed_registration.json', run / 'custom_actions/registry.json',
                                               run / 'source_manifest.json']})
    except (ValueError, OSError, KeyError, TypeError) as error:
        result['errors'].append(str(error))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first', type=Path)
    parser.add_argument('second', type=Path)
    parser.add_argument('--workspace-root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.first, args.second, args.workspace_root)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ['verified', 'errors', 'native_playback_verified']}))
    return 0 if result['verified'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
