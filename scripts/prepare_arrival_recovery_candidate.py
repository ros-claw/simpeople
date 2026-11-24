"""Build an isolated, opt-in Native candidate from an exact frozen source.

No Kit imports, GPU/model launch, source-asset mutation or qualification here.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def integrate_reservations(code):
    """Add reviewed hooks; refuse drift instead of doing a fuzzy patch."""
    substitutions = [
        ('from .adapter import NativeBackend',
         'from .adapter import NativeBackend\nfrom .arrival_recovery import ArrivalRecoveryMixin'),
        ('class ReservationNativeBackend(NativeBackend):',
         'class ReservationNativeBackend(ArrivalRecoveryMixin,NativeBackend):'),
        ("        if self.owner_routes.get(handle)!=rid or not job:raise SimPeopleError('TASK_STALE','recovery does not own the current route')\n",
         "        if self.owner_routes.get(handle)!=rid or not job:raise SimPeopleError('TASK_STALE','recovery does not own the current route')\n"
         "        if job['phase']=='arrival_braking':return {'accepted':False,'reason':'native_arrival_stop_in_progress'}\n"),
        ("        if not obs.get('ready') or self.now<job['retry_at']:return\n",
         "        if not obs.get('ready') or self.now<job['retry_at']:return\n"
         "        if self._tick_arrival_recovery(handle,rid,job,obs):return\n"),
        ("            if math.dist(obs['position_m'][:2],job['segment_goal'][:2])>.3 or obs['speed_mps']>=.15:return\n",
         "            if self._arrival_shortfall(handle,rid,job,obs):return\n"
         "            if math.dist(obs['position_m'][:2],job['segment_goal'][:2])>.3 or obs['speed_mps']>=.15:return\n"),
        ("        if self.corridor_profile and self.start_continuous_corridor(handle,rid,job,obs):return\n",
         "        if self.corridor_profile and not job.get('arrival_segment_fallback',False) and self.start_continuous_corridor(handle,rid,job,obs):return\n"),
    ]
    for before, after in substitutions:
        if code.count(before) != 1:
            raise ValueError('Native integration point changed; review rather than guessing')
        code = code.replace(before, after)
    ast.parse(code)
    return code


def prepare(base, expected_manifest, destination):
    base = Path(base).resolve(); destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('candidate destination must be new; keep earlier evidence')
    if sha(base/'source_manifest.json') != expected_manifest:
        raise ValueError('frozen base manifest differs')
    manifest = json.loads((base/'source_manifest.json').read_text())
    for name, digest in manifest.items():
        if not (base/name).resolve().is_relative_to(base) or sha(base/name) != digest:
            raise ValueError('frozen base bytes differ: '+name)
    destination.mkdir(parents=True)
    for name in manifest:
        target = destination/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base/name, target)
    helper = 'src/simpeople/backends/native/arrival_recovery.py'
    if helper in manifest:
        raise ValueError('base already contains an arrival recovery implementation')
    shutil.copy2(ROOT/helper, destination/helper)
    path = destination/'src/simpeople/backends/native/reservations.py'
    path.write_text(integrate_reservations(path.read_text()))
    profile = destination/'src/simpeople/core/gesture_profiles.py'
    code = profile.read_text(); tree = ast.parse(code)
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'IMPLEMENTATION_FILES' for t in n.targets))
    files = ast.literal_eval(node.value)
    if len(files) != 14 or 'backends/native/reservations.py' not in files:
        raise ValueError('this candidate requires the reviewed fourteen-file gesture base')
    replacement = 'IMPLEMENTATION_FILES = '+repr((*files, 'backends/native/arrival_recovery.py'))
    lines = code.splitlines(keepends=True)
    profile.write_text(''.join(lines[:node.lineno-1])+replacement+'\n'+''.join(lines[node.end_lineno:]))
    spec = importlib.util.spec_from_file_location('candidate_gesture_profile', profile)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    revision = module.implementation_revision(destination/'src/simpeople')
    path = destination/'configs/native_gesture_catalog.json'; catalog = json.loads(path.read_text())
    for record in catalog['records']:
        record['status'] = 'discovered'
        for key in ['evidence_run', 'evidence_sha256', 'replay_audit_sha256']:
            record.pop(key, None)
        for variant in record.get('startup_profiles', {}).values():
            variant['status'] = 'discovered'; variant['implementation_sha256'] = revision
            for key in ['evidence_run', 'evidence_sha256', 'replay_audit_sha256']:
                variant.pop(key, None)
            variant['scope'] = 'Private arrival-recovery source; no previous gesture or legacy qualification transferred.'
    path.write_text(json.dumps(catalog, indent=2)+'\n')
    # Freeze only files selected from the prior manifest and the added helper.
    selected = sorted([*manifest, helper])
    frozen = {name: sha(destination/name) for name in selected}
    (destination/'source_manifest.json').write_text(json.dumps(frozen, indent=2)+'\n')
    changed = [name for name in manifest if frozen[name] != manifest[name]]
    assert set(changed) == {'src/simpeople/backends/native/reservations.py',
                            'src/simpeople/core/gesture_profiles.py', 'configs/native_gesture_catalog.json'}
    assert len(frozen) == len(manifest) + 1
    origin = {'base_source': str(base), 'base_manifest_sha256': expected_manifest,
              'source_file_count': len(frozen), 'source_manifest_sha256': sha(destination/'source_manifest.json'),
              'changed_files': sorted(changed), 'added_files': [helper],
              'builder_sha256': sha(Path(__file__)), 'implementation_sha256': revision,
              'implementation_files': list(module.IMPLEMENTATION_FILES),
              'default_enabled': False, 'production_source_installed': False,
              'qualified_generated_native_rigs': [],
              'scope': 'Explicit pre-agent arrival_recovery_probe_enabled only. New Native evidence required; no base proof transfer.'}
    (destination/'origin.json').write_text(json.dumps(origin, indent=2)+'\n')
    for name, digest in manifest.items():
        assert sha(base/name) == digest, 'builder changed original source'
    return origin


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-source', required=True)
    parser.add_argument('--expected-manifest-sha256', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.base_source, args.expected_manifest_sha256, args.destination), indent=2))
