"""Installed Isaac static NavMesh preflight, without spawning or driving actors.

Every query uses the same radius/height profile as the runtime. This checks only
fixture connectivity, not crowd capacity, standing transitions, deadlines or task
completion. Each use-site and its actual returned path remain inspectable.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace-root', required=True)
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--matrix', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--gpu', type=int, default=3)
    args = parser.parse_args()
    root = Path(args.workspace_root).resolve()
    source = Path(args.source_root).resolve()
    matrix = Path(args.matrix).resolve()
    manifest = json.loads((matrix / 'matrix_manifest.json').read_text())
    assert len(manifest['cases']) == 18
    cases = []
    for row in manifest['cases']:
        path = matrix / (row['case_id'] + '.json')
        assert digest(path) == row['file_sha256'], path
        cases.append(json.loads(path.read_text()))
    out = root / 'runs' / args.run_id
    out.mkdir(exist_ok=False)
    snap = out / 'source_snapshot'
    snap.mkdir()
    for name in ['src', 'configs']:
        shutil.copytree(source / name, snap / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (snap / 'reports').mkdir()
    shutil.copy2(source / 'reports/capability_matrix.json', snap / 'reports/capability_matrix.json')
    (snap / 'scripts').mkdir()
    for name in ['probe_release_fixture.py', 'runtime_fixture_points.py']:
        shutil.copy2(Path(__file__).parent / name, snap / 'scripts' / name)
    shutil.copytree(matrix, out / 'inputs')
    (out / 'source_manifest.json').write_text(json.dumps({str(p.relative_to(snap)): digest(p) for p in sorted(snap.rglob('*')) if p.is_file()}, indent=2) + '\n')
    sys.path.insert(0, str(snap / 'src'))
    sys.path.insert(0, str(snap / 'scripts'))
    # Kit parses argv at import. Only the frozen, already validated inputs above
    # are used after this point; no remote evaluation or actor mutation exists.
    sys.argv = [sys.argv[0]]
    from runtime_fixture_points import fixture_points, path_quality
    from isaacsim import SimulationApp
    app = SimulationApp({'headless': True, 'active_gpu': args.gpu, 'multi_gpu': False,
                         'limit_cpu_threads': 8, 'disable_viewport_updates': True})
    backend = None
    results = []
    try:
        import omni.kit.app
        import omni.usd
        manager = omni.kit.app.get_app().get_extension_manager()
        for ext in ['omni.anim.behavior.core', 'omni.anim.navigation.core']:
            assert manager.set_extension_enabled_immediate(ext, True)
        from simpeople.backends.native.environments import industrial_scene
        from simpeople.backends.native.probe_scenes import narrow_traffic_probe_scene, narrow_release_scene
        from simpeople.backends.native.reservations import ReservationNativeBackend
        builders = {'industrial': industrial_scene, 'industrial_narrow_probe_v1': narrow_traffic_probe_scene,
                    'industrial_narrow_release_v2': narrow_release_scene}
        scene_ids = list(dict.fromkeys(case['scene']['id'] for case in cases))
        assert len(scene_ids) == 2 and 'industrial' in scene_ids and set(scene_ids) <= set(builders)
        for scene_id in scene_ids:
            if backend:
                backend.close()
                backend = None
            omni.usd.get_context().new_stage()
            semantics = builders[scene_id]()
            actual_revision = hashlib.sha256(json.dumps(semantics, sort_keys=True).encode()).hexdigest()
            selected = [case for case in cases if case['scene']['id'] == scene_id]
            assert len(selected) == 9 and all(case['scene']['revision'] == actual_revision for case in selected)
            backend = ReservationNativeBackend(root, semantics, False, config_dir=snap / 'configs',
                                               capability_file=snap / 'reports/capability_matrix.json')
            for _ in range(5):
                app.update()
            assert backend.nav.start_navmesh_baking_and_wait()
            (out / (scene_id + '_semantics.json')).write_text(json.dumps(semantics, indent=2) + '\n')
            hub = backend.resolve_target('entrance')
            cached = {}
            for case in selected:
                uses = []
                for point in fixture_points(case, semantics):
                    key = tuple(point['position_m'])
                    if key not in cached:
                        path = backend.segment(hub, list(key))
                        cached[key] = {'path_m': path, **path_quality(hub, list(key), path)}
                    uses.append({**point, **cached[key]})
                row = {'case_id': case['case_id'], 'scene_revision': actual_revision,
                       'passed': all(use['passed'] for use in uses), 'uses': uses}
                results.append(row)
                (out / (case['case_id'] + '_paths.json')).write_text(json.dumps(row, indent=2) + '\n')
                print('NATIVE_FIXTURE_CASE', case['case_id'], row['passed'], len(uses), flush=True)
        summary = {'schema_version': 'simpeople.native-fixture-preflight.v1', 'run_id': args.run_id,
                   'passed': all(row['passed'] for row in results), 'cases_checked': len(results),
                   'failed_cases': [row['case_id'] for row in results if not row['passed']],
                   'profile_m': {'radius': .45, 'height': 1.6, 'collision_gap': 0.0},
                   'native_isaac_revision': backend.runtime_revision,
                   'matrix_manifest_sha256': digest(out / 'inputs/matrix_manifest.json'),
                   'task_feasibility_verified': False, 'nominal_capacity_verified': False,
                   'scope': 'Actual static navigation connectivity only. No actors, Play, tasks, recording, crowd coordination or release pass. All18 runtime cases remain required.'}
        (out / 'completed.json').write_text(json.dumps(summary, indent=2) + '\n')
        return 0 if summary['passed'] else 1
    finally:
        if backend:
            backend.close()
        app.close()


if __name__ == '__main__':
    raise SystemExit(main())
