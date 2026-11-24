"""Compose an unqualified execution snapshot without overwriting either input.

Keep current fixes by default; import only the reviewed Native feature files.
This tool neither launches Isaac nor installs or qualifies the result.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import shutil


FEATURE_FILES = (
    'backends/native/adapter.py', 'backends/native/custom_actions.py',
    'backends/native/local_yield.py',
    'backends/native/local_yield_stop.py', 'backends/native/reservations.py',
    'core/engine.py', 'core/facing_runtime.py', 'core/journal.py',
    'core/protocol.py', 'core/runtime_policy.py', 'core/wait_snapshot.py',
    'motion/entry.py',
)
PRESERVED_FILES = (
    'backends/native/pose_bridge.py', 'core/management.py', 'core/workloads.py',
    'tools/claude_benchmark.py', 'tools/runtime_contract.py',
    'backends/native/custom_stop.py',
)
PROOF_FIELDS = (
    'evidence_run', 'evidence_sha256', 'replay_audit_sha256',
    'continuity_audit_sha256', 'source_audit_sha256',
    'legacy_regression_run', 'legacy_review_sha256', 'legacy_return_review_sha256',
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_manifest(folder, manifest_path, expected):
    folder = Path(folder).resolve(); manifest_path = Path(manifest_path)
    if sha(manifest_path) != expected:
        raise ValueError('input manifest differs')
    values = json.loads(manifest_path.read_text())
    if not isinstance(values, dict) or not values:
        raise ValueError('nonempty file manifest required')
    for name, digest in values.items():
        relative = PurePosixPath(name)
        if (not isinstance(name, str) or relative.is_absolute() or '..' in relative.parts
                or str(relative) != name or not (folder/name).resolve().is_relative_to(folder)
                or not (folder/name).is_file() or sha(folder/name) != digest):
            raise ValueError('input bytes/path differ: '+str(name))
    return values


def clear_proof(record):
    record['status'] = 'discovered'
    for key in PROOF_FIELDS:
        record.pop(key, None)


def preserve_pending_cancel(code):
    """Older feature snapshots must not undo current cancel idempotence."""
    tree=ast.parse(code)
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='cmd_cancel')
    if any(isinstance(n,ast.If) and ast.unparse(n.test)=="t.get('cancel_requested')" for n in method.body):
        return code
    old="        if t['status'] in TERMINAL:return self.public(t)\n        a=self.actor(t['actor_id']); a['control_epoch']+=1"
    new="        if t['status'] in TERMINAL:return self.public(t)\n        if t.get('cancel_requested'):\n            return {**self.public(t),'cancellation':'accepted'}\n        a=self.actor(t['actor_id']); a['control_epoch']+=1"
    if code.count(old)!=1:raise ValueError('review pending-cancel merge point')
    return code.replace(old,new)


def prepare(root, root_manifest, root_sha, features, features_sha, destination,
            legacy_source=None, legacy_sha=None):
    root = Path(root).resolve(); features = Path(features).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('use a new destination; preserve previous snapshots')
    if destination.is_relative_to(root/'src') or destination.is_relative_to(features):
        raise ValueError('destination overlaps input execution files')
    base = check_manifest(root, root_manifest, root_sha)
    extra = check_manifest(features, features/'source_manifest.json', features_sha)
    if (legacy_source is None) != (legacy_sha is None):
        raise ValueError('legacy source and manifest digest must be supplied together')
    legacy_entry = None
    if legacy_source is not None:
        legacy_source = Path(legacy_source).resolve()
        legacy = check_manifest(legacy_source, legacy_source/'source_manifest.json', legacy_sha)
        registry = 'configs/custom_actions.json'
        if registry not in legacy or registry not in base:
            raise ValueError('both registries are required')
        legacy_entry = json.loads((legacy_source/registry).read_text())['actions']['floor_stretch']
        if (legacy_entry.get('skeleton') != 'cache://behavior/MotionLibrary/Human/HumanMotionLibrary.usd'
                or legacy_entry.get('clip') != 'cache://legacy/floor_tail_eq01/floor_stretch.usda'
                or legacy_entry.get('playback_mode') != 'loop'
                or legacy_entry.get('clearance_radius_m') != 2.5 or 'pelvis_lift_m' in legacy_entry):
            raise ValueError('requires the reviewed finite floor-tail entry')
    required = {'src/simpeople/'+n for n in (*FEATURE_FILES, *PRESERVED_FILES)}
    if not required <= set(base) | set(extra):
        raise ValueError('required execution dependencies missing')
    if not all('src/simpeople/'+n in base for n in PRESERVED_FILES):
        raise ValueError('current fixes must come from the current root')
    if not all('src/simpeople/'+n in extra for n in FEATURE_FILES):
        raise ValueError('reviewed feature file absent')
    inputs = dict(base)
    inputs.update({'src/simpeople/'+name: extra['src/simpeople/'+name] for name in FEATURE_FILES})
    package = 'src/simpeople/'
    # Bind the new domain to the whole selected package, including indirect
    # controllers. An older fourteen/sixteen-file proof cannot transfer here.
    implementation = tuple(sorted(n[len(package):] for n in inputs
                                  if n.startswith(package) and n.endswith(('.py', '.cpp'))))
    profile_name = package+'core/gesture_profiles.py'
    profile = (root/profile_name).read_text(); tree = ast.parse(profile)
    assignment = next(n for n in tree.body if isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == 'IMPLEMENTATION_FILES'
                              for t in n.targets))
    lines = profile.splitlines(keepends=True)
    profile = ''.join(lines[:assignment.lineno-1])+'IMPLEMENTATION_FILES = '+repr(implementation)+'\n'+''.join(lines[assignment.end_lineno:])
    ast.parse(profile)
    engine_name = package+'core/engine.py'
    engine = preserve_pending_cancel((features/engine_name).read_text())
    destination.mkdir(parents=True)
    for name in inputs:
        origin = features if name in {'src/simpeople/'+n for n in FEATURE_FILES} else root
        target = destination/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin/name, target)
    (destination/profile_name).write_text(profile)
    (destination/engine_name).write_text(engine)
    if legacy_entry is not None:
        registry = destination/'configs/custom_actions.json'
        data = json.loads(registry.read_text())
        data['actions']['floor_stretch'] = legacy_entry
        registry.write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n')
    spec = importlib.util.spec_from_file_location('integrated_gesture_profile', destination/profile_name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    revision = module.implementation_revision(destination/'src/simpeople')
    catalog_path = destination/'configs/native_gesture_catalog.json'
    catalog = json.loads(catalog_path.read_text())
    for record in catalog['records']:
        clear_proof(record)
        record['scope'] = 'Integrated candidate: fresh Native qualification required.'
        for variant in record.get('startup_profiles', {}).values():
            clear_proof(variant)
            variant['implementation_sha256'] = revision
            variant['scope'] = 'Integrated candidate: no prior runtime proof transferred.'
    catalog_path.write_text(json.dumps(catalog, indent=2)+'\n')
    frozen = {name: sha(destination/name) for name in sorted(inputs)}
    (destination/'source_manifest.json').write_text(json.dumps(frozen, indent=2)+'\n')
    for name in PRESERVED_FILES:
        relative = package+name
        assert frozen[relative] == base[relative], relative
    check_manifest(root, root_manifest, root_sha)
    check_manifest(features, features/'source_manifest.json', features_sha)
    if legacy_source is not None:
        check_manifest(legacy_source, legacy_source/'source_manifest.json', legacy_sha)
    receipt = {
        'root': str(root), 'root_manifest_sha256': root_sha,
        'feature_source': str(features), 'feature_manifest_sha256': features_sha,
        'source_manifest_sha256': sha(destination/'source_manifest.json'),
        'source_file_count': len(frozen), 'feature_files': list(FEATURE_FILES),
        'preserved_files': list(PRESERVED_FILES),
        'implementation_files': list(implementation), 'implementation_sha256': revision,
        'previous_native_proof_transferred': False, 'production_source_installed': False,
        'qualified_generated_native_rigs': [], 'full_release_passed': False,
        'legacy_source': str(legacy_source) if legacy_source is not None else None,
        'legacy_source_manifest_sha256': legacy_sha,
        'legacy_entry_replaced': legacy_entry is not None,
        'scope': 'Unqualified composition only. Fresh Native gestures, legacy, motion, crowd and hosts required.',
    }
    (destination/'origin.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for flag in ['root', 'root-manifest', 'root-sha', 'features', 'features-sha', 'destination']:
        parser.add_argument('--'+flag, required=True)
    parser.add_argument('--legacy-source'); parser.add_argument('--legacy-sha')
    a = parser.parse_args()
    print(json.dumps(prepare(a.root, a.root_manifest, a.root_sha, a.features, a.features_sha, a.destination,
                             a.legacy_source, a.legacy_sha), indent=2))
