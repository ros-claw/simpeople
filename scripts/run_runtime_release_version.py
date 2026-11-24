"""Freeze an independent shared harness, then run explicit release cases.

The shared workspace keeps the original harness bytes and existing asset cache
through declared local symlinks. Both runtime versions must use this SAME shared
workspace, so edits in the development tree cannot change a later matrix job.
Results always go to the real workspace's runs directory. No asset is copied or
rewritten, and a partial invocation never certifies all18 cases.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


SCRIPTS = ['bench_native_runtime.py', 'audit_runtime_probe.py', 'analyze_waits.py',
           'summarize_run.py', 'audit_retry_identity.py', 'run_runtime_release_version.py',
           'native_fault_triggers.py']


def sha(path):
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(path.read_text())


def dump(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def verify_source(source):
    manifest = read(source / 'source_manifest.json')
    assert manifest, 'empty frozen source manifest'
    for relative, expected in manifest.items():
        path = Path(relative)
        assert not path.is_absolute() and '..' not in path.parts
        assert sha(source / path) == expected, 'frozen source changed: ' + relative
    return manifest


def prepare(root, destination, matrix):
    root, destination, matrix = map(lambda p: Path(p).resolve(), [root, destination, matrix])
    inputs = read(matrix / 'matrix_manifest.json')
    assert len(inputs['cases']) == 18
    for row in inputs['cases']:
        assert sha(matrix / (row['case_id'] + '.json')) == row['file_sha256']
    destination.mkdir(parents=True, exist_ok=False)
    for name in ['src', 'configs', 'schemas']:
        shutil.copytree(root / name, destination / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (destination / 'scripts').mkdir()
    for name in SCRIPTS:
        shutil.copy2(root / 'scripts' / name, destination / 'scripts' / name)
    (destination / 'reports').mkdir()
    shutil.copy2(root / 'reports/capability_matrix.json', destination / 'reports/capability_matrix.json')
    shutil.copytree(matrix, destination / 'inputs')
    for name in ['assets', 'runs']:
        assert (root / name).is_dir(), name
        (destination / name).symlink_to(root / name, target_is_directory=True)
    names = ['src', 'configs', 'schemas', 'scripts', 'reports', 'inputs']
    manifest = {str(path.relative_to(destination)): sha(path) for name in names
                for path in sorted((destination / name).rglob('*')) if path.is_file()}
    dump(destination / 'source_manifest.json', manifest)
    dump(destination / 'workspace_binding.json', {
        'schema_version': 'simpeople.shared-release-workspace.v1', 'real_workspace': str(root),
        'source_manifest_sha256': sha(destination / 'source_manifest.json'),
        'original_matrix_manifest_sha256': sha(matrix / 'matrix_manifest.json'),
        'links': {name: str(root / name) for name in ['assets', 'runs']},
        'scope': 'Shared frozen driver and analyzers ONLY; not a runtime version or native acceptance.'})
    return destination


def validate_workspace(workspace):
    workspace = Path(workspace).resolve()
    binding = read(workspace / 'workspace_binding.json')
    assert sha(workspace / 'source_manifest.json') == binding['source_manifest_sha256']
    verify_source(workspace)
    for name, target in binding['links'].items():
        assert (workspace / name).is_symlink() and (workspace / name).resolve() == Path(target).resolve(), 'shared link changed: ' + name
    assert sha(workspace / 'inputs/matrix_manifest.json') == binding['original_matrix_manifest_sha256']
    return binding


def jobs(workspace, source, prefix, profile, case_ids, gpu, port):
    assert prefix and all(c.isalnum() or c in '-_' for c in prefix), 'invalid unique run prefix'
    workspace, source = Path(workspace).resolve(), Path(source).resolve()
    manifest = read(workspace / 'inputs/matrix_manifest.json')
    available = {row['case_id']: row for row in manifest['cases']}
    assert len(available) == 18
    assert not case_ids or len(set(case_ids)) == len(case_ids) and set(case_ids) <= set(available), 'unknown or duplicate selected case'
    result = []
    for name, row in available.items():
        if case_ids and name not in case_ids:
            continue
        rid = prefix + '-' + name.removeprefix('release_').replace('_', '-')
        result.append({'run_id': rid, 'case_id': name, 'input_sha256': row['file_sha256'],
            'argv': ['/data/omniverse/isaac-sim-6.2.0/python.sh', str(workspace / 'scripts/bench_native_runtime.py'),
                     '--run-id', rid, '--case', str(workspace / 'inputs' / (name + '.json')),
                     '--source-root', str(source), '--gpu', str(gpu), '--port', str(port),
                     '--diagnostic-idle-tags', profile]})
    return result


def no_owned_native_job():
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = (proc / 'cmdline').read_bytes().split(b'\0')
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if b'--run-id' in argv:
            rid = argv[argv.index(b'--run-id') + 1]
            assert not rid.startswith(b'iter1114'), 'another owned native job remains live: ' + rid.decode()


def execute(workspace, source, prefix, profile, case_ids, gpu, port, fixture_run, state_file):
    workspace, source, fixture_run, state_file = map(lambda p: Path(p).resolve(), [workspace, source, fixture_run, state_file])
    assert not state_file.exists(), 'refusing to overwrite a prior execution state'
    binding = validate_workspace(workspace)
    source_manifest = verify_source(source)
    fixture = read(fixture_run / 'completed.json')
    assert fixture['passed'] and fixture['cases_checked'] == 18, 'static fixture preflight has not passed'
    assert fixture['matrix_manifest_sha256'] == binding['original_matrix_manifest_sha256'], 'fixture used other inputs'
    selected = jobs(workspace, source, prefix, profile, case_ids, gpu, port)
    state = {'state': 'prepared', 'selected_jobs': selected, 'source_root': str(source),
             'source_manifest_sha256': sha(source / 'source_manifest.json'), 'idle_profile': profile,
             'shared_workspace': str(workspace), 'workspace_binding_sha256': sha(workspace / 'workspace_binding.json'),
             'fixture_completed_sha256': sha(fixture_run / 'completed.json'), 'jobs': [],
             'all18_runtime_cases_executed': False, 'release_gate_passed': False}
    dump(state_file, state)
    try:
        for job in selected:
            assert shutil.disk_usage(workspace).free >= 80 * 1024 ** 3, 'insufficient evidence storage; prior runs retained'
            validate_workspace(workspace)
            assert verify_source(source) == source_manifest
            no_owned_native_job()
            folder = workspace / 'runs' / job['run_id']
            assert not folder.exists(), 'run ID already exists'
            assert sha(workspace / 'inputs' / (job['case_id'] + '.json')) == job['input_sha256']
            state.update(state='native_case_running', current_run_id=job['run_id'])
            dump(state_file, state)
            with (state_file.parent / (job['run_id'] + '.log')).open('w') as log:
                process = subprocess.Popen(job['argv'], cwd=workspace, stdout=log, stderr=subprocess.STDOUT)
                state['launcher_pid'] = process.pid
                dump(state_file, state)
                returncode = process.wait()
            row = {'run_id': job['run_id'], 'case_id': job['case_id'], 'native_returncode': returncode}
            state['jobs'].append(row)
            state['launcher_pid'] = None
            dump(state_file, state)
            assert (folder / 'completed.json').is_file(), 'native harness did not close'
            done = read(folder / 'completed.json')
            assert done['harness_completed'] and abs(done['duration_s'] - 600) < 1e-5
            row['original_completed'] = done
            for script, output in [('audit_runtime_probe.py', 'runtime_audit.json'),
                                   ('audit_retry_identity.py', 'retry_identity_audit.json'),
                                   ('summarize_run.py', None)]:
                argv = [sys.executable, str(workspace / 'scripts' / script), str(folder)]
                if output:
                    argv += ['--output', str(folder / output)]
                with (state_file.parent / (job['run_id'] + '_' + script + '.log')).open('w') as log:
                    row[script + '_returncode'] = subprocess.call(argv, cwd=workspace, stdout=log, stderr=subprocess.STDOUT)
            dump(state_file, state)
        state.update(state='closed', current_run_id=None, all18_runtime_cases_executed=len(state['jobs']) == 18)
        dump(state_file, state)
    except Exception as exc:
        state.update(state='failed', error=repr(exc))
        dump(state_file, state)
        raise
    return state


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_subparsers(dest='mode', required=True)
    prepare_parser = mode.add_parser('prepare')
    prepare_parser.add_argument('--workspace-root', required=True)
    prepare_parser.add_argument('--output', required=True)
    prepare_parser.add_argument('--matrix', required=True)
    run = mode.add_parser('run')
    for name in ['shared-workspace', 'source-root', 'run-prefix', 'fixture-run', 'state-output']:
        run.add_argument('--' + name, required=True)
    run.add_argument('--idle-profile', choices=['default', 'basic'], required=True)
    run.add_argument('--case-ids', nargs='+')
    run.add_argument('--gpu', type=int, default=3)
    run.add_argument('--port', type=int, default=8898)
    args = parser.parse_args()
    if args.mode == 'prepare':
        print(prepare(args.workspace_root, args.output, args.matrix))
    else:
        result = execute(args.shared_workspace, args.source_root, args.run_prefix, args.idle_profile,
                         args.case_ids, args.gpu, args.port, args.fixture_run, args.state_output)
        print(json.dumps({k: v for k, v in result.items() if k not in {'jobs', 'selected_jobs'}}, indent=2))


if __name__ == '__main__':
    main()
