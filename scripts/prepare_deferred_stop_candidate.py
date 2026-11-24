"""Freeze an opt-in delayed Idle experiment; retain all earlier failures."""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
HELPER = 'src/simpeople/backends/native/deferred_custom_stop.py'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def integrate_adapter(code):
    old = "            if needs_settlement(entry):\n                record="
    new = ("            if needs_settlement(entry):\n"
           "                from .deferred_custom_stop import request\n"
           "                if request(self,handle,entry,current,name,a):return\n"
           "                record=")
    if code.count(old) != 1:
        raise ValueError('review canonical stop adapter drift')
    return code.replace(old, new)


def prepare(base, expected, destination):
    base = Path(base).resolve(); destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('preserve earlier source and evidence')
    if sha(base/'source_manifest.json') != expected:
        raise ValueError('base manifest changed')
    manifest = json.loads((base/'source_manifest.json').read_text())
    for name, digest in manifest.items():
        if not (base/name).resolve().is_relative_to(base) or sha(base/name) != digest:
            raise ValueError('base file differs: ' + name)
    adapter = integrate_adapter((base/'src/simpeople/backends/native/adapter.py').read_text())
    profile_name = 'src/simpeople/core/gesture_profiles.py'
    profile_code = (base/profile_name).read_text()
    nodes = [n for n in ast.parse(profile_code).body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'IMPLEMENTATION_FILES' for t in n.targets)]
    if len(nodes) != 1:
        raise ValueError('review execution fingerprint drift')
    node = nodes[0]; files = ast.literal_eval(node.value)
    if (len(files) < 100 or 'backends/native/custom_stop.py' not in files
            or 'backends/native/deferred_custom_stop.py' in files):
        raise ValueError('review execution fingerprint drift')
    lines = profile_code.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno] = ['IMPLEMENTATION_FILES = ' + repr(tuple(sorted(
        [*files, 'backends/native/deferred_custom_stop.py']))) + '\n']
    profile_code = ''.join(lines)
    destination.mkdir(parents=True)
    for name in manifest:
        out = destination/name; out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base/name, out)
    (destination/'src/simpeople/backends/native/adapter.py').write_text(adapter)
    for name in [HELPER, 'src/simpeople/backends/native/custom_stop.py']:
        shutil.copy2(ROOT/name, destination/name)
    (destination/profile_name).write_text(profile_code)
    spec = importlib.util.spec_from_file_location('deferred_stop_profile', destination/profile_name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    revision = module.implementation_revision(destination/'src/simpeople')
    catalog = destination/'configs/native_gesture_catalog.json'
    data = json.loads(catalog.read_text())
    for record in data['records']:
        record['status'] = 'discovered'
        for key in ['evidence_run', 'evidence_sha256', 'replay_audit_sha256']:
            record.pop(key, None)
        for variant in record.get('startup_profiles', {}).values():
            for key in list(variant):
                if key.endswith('_sha256') or key in ['evidence_run', 'legacy_regression_run']:
                    variant.pop(key)
            variant.update(status='discovered', implementation_sha256=revision,
                           scope='Deferred cancellation experiment; fresh Native proof required.')
    catalog.write_text(json.dumps(data, indent=2)+'\n')
    frozen = {name: sha(destination/name) for name in [*manifest, HELPER]}
    (destination/'source_manifest.json').write_text(json.dumps(frozen, indent=2)+'\n')
    changed = [name for name in frozen if frozen[name] != manifest.get(name)]
    result = dict(source_manifest_sha256=sha(destination/'source_manifest.json'),
                  implementation_sha256=revision, changed_files=changed,
                  previous_native_proof_transferred=False, production_source_installed=False,
                  qualified_generated_native_rigs=[],
                  scope='Default-off delayed owned Idle, original cancellation budget and canonical entry.')
    (destination/'origin.json').write_text(json.dumps(result, indent=2)+'\n')
    assert all(sha(base/name) == digest for name, digest in manifest.items())
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ['base', 'expected', 'destination']:
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.base, args.expected, args.destination), indent=2))
