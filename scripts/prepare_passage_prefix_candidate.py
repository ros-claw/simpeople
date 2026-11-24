"""Stage explicit no-stop zones for controlled Native passage experiments."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'src/simpeople/core/passage_prefix.py'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def integrate(code):
    changes = [(
        '            if horizon:points=polyline_prefix(points,horizon)\n',
        """            zones=getattr(self,'passage_no_stop_probe_zones',[])
            if horizon and zones:
                from simpeople.core.passage_prefix import protected_prefix
                try:points,proof=protected_prefix(points,horizon,zones)
                except ValueError as error:
                    self.emit('traffic_passage_stop_rejected',route_id=rid,reason=str(error));return False
                horizon=proof['actual_horizon_m']
                next_goal=min(len(job['goals'])-1,job['goal_index']+sum(offset<=horizon+1e-6 for offset in goal_offsets))
                if proof['extended_for_passages']:
                    self.emit('traffic_passage_prefix_extended',route_id=rid,**proof)
            elif horizon:points=polyline_prefix(points,horizon)
"""), (
        '        cells=self.grid.sweep(here,destination)\n        # Verify the whole escape',
        """        from simpeople.core.passage_prefix import inside as passage_inside
        if any(passage_inside(destination,z) for z in getattr(self,'passage_no_stop_probe_zones',[])):
            self.emit('traffic_passage_stop_rejected',route_id=rid,target_m=destination,reason='grid_stop_inside_passage')
            self.block(rid,job);return
        cells=self.grid.sweep(here,destination)
        # Verify the whole escape"""), (
        '            if repair:\n                destination=',
        """            if repair and any(passage_inside(repair['destination_m'],z) for z in getattr(self,'passage_no_stop_probe_zones',[])):
                repair=None
            if repair:
                destination="""),
    ]
    for old, new in changes:
        if code.count(old) != 1:
            raise ValueError('review reservation source drift')
        code = code.replace(old, new)
    return code


def prepare(base, expected, destination):
    base = Path(base).resolve(); destination = Path(destination).resolve()
    if destination.exists() or sha(base/'source_manifest.json') != expected:
        raise ValueError('preserve prior candidate or review base manifest')
    manifest = json.loads((base/'source_manifest.json').read_text())
    for name, digest in manifest.items():
        if not (base/name).resolve().is_relative_to(base) or sha(base/name) != digest:
            raise ValueError('base bytes differ: '+name)
    adapter = integrate((base/'src/simpeople/backends/native/reservations.py').read_text())
    profile_name = 'src/simpeople/core/gesture_profiles.py'
    profile = (base/profile_name).read_text(); tree = ast.parse(profile)
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'IMPLEMENTATION_FILES' for t in n.targets))
    files = ast.literal_eval(node.value)
    if len(files) < 100 or 'core/passage_prefix.py' in files:
        raise ValueError('review whole-code fingerprint')
    lines = profile.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno] = ['IMPLEMENTATION_FILES = '+repr(tuple(sorted([*files, 'core/passage_prefix.py'])))+'\n']
    destination.mkdir(parents=True)
    for name in manifest:
        out = destination/name; out.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(base/name, out)
    (destination/'src/simpeople/backends/native/reservations.py').write_text(adapter)
    shutil.copy2(ROOT/MODULE, destination/MODULE)
    (destination/profile_name).write_text(''.join(lines))
    spec = importlib.util.spec_from_file_location('passage_profile', destination/profile_name)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    revision = module.implementation_revision(destination/'src/simpeople')
    catalog = destination/'configs/native_gesture_catalog.json'; data = json.loads(catalog.read_text())
    for row in data['records']:
        row['status'] = 'discovered'
        for key in ['evidence_run', 'evidence_sha256', 'replay_audit_sha256']: row.pop(key, None)
        for variant in row.get('startup_profiles', {}).values():
            for key in list(variant):
                if key.endswith('_sha256') or key in ['evidence_run', 'legacy_regression_run']: variant.pop(key)
            variant.update(status='discovered', implementation_sha256=revision,
                           scope='New no-stop passage experiment; fresh qualification required.')
    catalog.write_text(json.dumps(data, indent=2)+'\n')
    new = {n: sha(destination/n) for n in [*manifest, MODULE]}
    (destination/'source_manifest.json').write_text(json.dumps(new, indent=2)+'\n')
    result = dict(source_manifest_sha256=sha(destination/'source_manifest.json'),
                  implementation_sha256=revision, changed_files=[n for n in new if new[n] != manifest.get(n)],
                  production_source_installed=False, final_release_verified=False,
                  previous_native_proof_transferred=False)
    (destination/'origin.json').write_text(json.dumps(result, indent=2)+'\n')
    assert all(sha(base/n) == d for n, d in manifest.items())
    return result
