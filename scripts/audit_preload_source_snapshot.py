"""Check the preload probe's two exact config replacements and frozen inputs.

No Native imports or edits. Source correspondence alone cannot qualify motion.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

from audit_gesture_source_snapshot import EXECUTION_ROOTS, PACKAGING_METADATA, excludes_packaging


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_at(root, name):
    relative = PurePosixPath(name)
    if (relative.is_absolute() or '..' in relative.parts or str(relative) != name
            or not (Path(root)/name).resolve().is_relative_to(Path(root).resolve())):
        raise ValueError('manifest path escapes or is not canonical: '+name)
    return Path(root)/name


def checked_manifest(root, path, expected):
    if sha(path) != expected:
        raise ValueError('manifest differs: '+str(path))
    values = json.loads(Path(path).read_text())
    if not isinstance(values, dict) or not values:
        raise ValueError('nonempty manifest required')
    for name, digest in values.items():
        if sha(file_at(root, name)) != digest:
            raise ValueError('frozen bytes differ: '+name)
    return values


def audit(source, run, source_sha, probe, probe_sha, clips, clip_manifest, clip_sha):
    source, run, probe, clips = map(Path, (source, run, probe, clips))
    errors = []; verified = []; omitted = []
    try:
        candidate = checked_manifest(source, source/'source_manifest.json', source_sha)
        inputs = checked_manifest(clips, clip_manifest, clip_sha)
        actual = json.loads((run/'source_manifest.json').read_text()); snap = run/'source_snapshot'
        if sha(probe) != probe_sha or actual.get(probe.name) != probe_sha:
            raise ValueError('executed probe differs')
        registry = json.loads(file_at(clips, 'actions.json').read_text())
        if 'actions.json' not in inputs or not registry.get('actions'):
            raise ValueError('frozen clip registry required')
        replacements = {
            'configs/custom_actions.json': hashlib.sha256((json.dumps(registry, indent=2)+'\n').encode()).hexdigest(),
            'configs/custom_action_acceptance.json': hashlib.sha256(b'{}\n').hexdigest(),
        }
        if not set(replacements) <= candidate.keys():
            raise ValueError('original config inputs absent')
        for name, digest in actual.items():
            if sha(file_at(snap, name)) != digest:
                raise ValueError('snapshot file differs: '+name)
        for name, digest in candidate.items():
            if name.split('/')[0] not in EXECUTION_ROOTS:
                continue
            if name not in actual and name in PACKAGING_METADATA and excludes_packaging(probe):
                omitted.append(name); continue
            if actual.get(name) != replacements.get(name, digest):
                raise ValueError('execution input differs: '+name)
            verified.append(name)
        expected = {name for name in candidate if name.split('/')[0] in EXECUTION_ROOTS}
        expected -= set(omitted)
        expected |= {probe.name, *('inputs/'+name for name in inputs)}
        if set(actual) != expected:
            raise ValueError('unexpected or missing snapshot paths')
        for name, digest in inputs.items():
            if actual.get('inputs/'+name) != digest:
                raise ValueError('preload input differs: '+name)
        for path in snap.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            if str(path.relative_to(snap)) not in actual:
                raise ValueError('unmanifested snapshot file')
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as error:
        errors.append(type(error).__name__+': '+str(error))
    return {'run_id': run.name, 'execution_source_verified': not errors, 'errors': errors,
            'execution_inputs_verified': verified, 'omitted_packaging_metadata': omitted,
            'source_manifest_sha256': source_sha, 'clip_manifest_sha256': clip_sha,
            'probe_sha256': probe_sha, 'native_motion_verified': False,
            'scope': 'Exact source, preload inputs and two documented config replacements only. No pose, contact, entry, cancellation or generated-rig qualification.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ['source', 'run', 'source-sha', 'probe', 'probe-sha', 'clips',
                 'clip-manifest', 'clip-sha', 'output']:
        parser.add_argument('--'+name, required=True)
    a = parser.parse_args()
    result = audit(a.source, a.run, a.source_sha, a.probe, a.probe_sha,
                   a.clips, a.clip_manifest, a.clip_sha)
    with Path(a.output).open('x') as stream:
        stream.write(json.dumps(result, indent=2)+'\n')
    print(json.dumps({'execution_source_verified': result['execution_source_verified'], 'errors': result['errors']}))
    raise SystemExit(0 if result['execution_source_verified'] else 2)
