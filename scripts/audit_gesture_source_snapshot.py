"""Match the gesture probe's actual snapshot scope, without weakening code checks."""
import argparse
import ast
import hashlib
import json
from pathlib import Path


PACKAGING_METADATA = {'src/rosclaw_simpeople.egg-info/'+name for name in (
    'PKG-INFO', 'SOURCES.txt', 'dependency_links.txt', 'entry_points.txt', 'requires.txt', 'top_level.txt')}
EXECUTION_ROOTS = {'src', 'configs', 'schemas', 'reports'}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def enclosed(root,name):
    path=Path(root)/name
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError('manifest path escapes source: '+name)
    return path


def excludes_packaging(probe):
    tree=ast.parse(Path(probe).read_text())
    return any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
               and n.func.attr=='ignore_patterns'
               and any(isinstance(a,ast.Constant) and a.value=='*.egg-info' for a in n.args)
               for n in ast.walk(tree))


def audit(source,run,source_manifest_sha256,probe,probe_sha256):
    source,run,probe=Path(source),Path(run),Path(probe)
    omitted=[];verified=[];nonexecuted=[];errors=[]
    try:
        if sha(source/'source_manifest.json')!=source_manifest_sha256:
            raise ValueError('frozen candidate manifest changed')
        candidate=json.loads((source/'source_manifest.json').read_text())
        actual=json.loads((run/'source_manifest.json').read_text());snap=run/'source_snapshot'
        if sha(probe)!=probe_sha256 or actual.get(probe.name)!=probe_sha256:
            raise ValueError('actual probe differs from frozen launch')
        for name,digest in candidate.items():
            if sha(enclosed(source,name))!=digest:
                raise ValueError('frozen candidate file changed: '+name)
        for name,digest in actual.items():
            if sha(enclosed(snap,name))!=digest:
                raise ValueError('actual snapshot file changed: '+name)
        metadata_ignored=excludes_packaging(probe)
        for name,digest in candidate.items():
            if name.split('/')[0] not in EXECUTION_ROOTS:
                nonexecuted.append(name);continue
            if name not in actual:
                if name in PACKAGING_METADATA and metadata_ignored:
                    omitted.append({'file':name,'candidate_sha256':digest,
                                    'reason':'exact packaging metadata excluded by the frozen probe copy policy'})
                    continue
                raise ValueError('runtime input absent from snapshot: '+name)
            if actual[name]!=digest:
                raise ValueError('runtime input differs: '+name)
            verified.append(name)
        # The probe ignores caches. An added Python file is not such a cache.
        for path in snap.rglob('*.py'):
            name=str(path.relative_to(snap))
            if name not in actual:raise ValueError('unmanifested snapshot code: '+name)
    except (OSError,ValueError,KeyError,TypeError,SyntaxError) as error:
        errors.append(type(error).__name__+': '+str(error))
    return {'run_id':run.name,'execution_source_verified':not errors,'errors':errors,
            'execution_inputs_verified':verified,'omitted_packaging_metadata':omitted,
            'candidate_nonexecuted_paths':nonexecuted,'source_manifest_sha256':source_manifest_sha256,
            'probe_sha256':probe_sha256,'native_gesture_verified':False,
            'scope':'Source/snapshot correspondence only. Known omitted distribution metadata does not exempt code, configs, schemas or capability data. No hold, release, catalog or rig qualification.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ['source','run','source-manifest-sha256','probe','probe-sha256','output']:
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    result=audit(args.source,args.run,args.source_manifest_sha256,args.probe,args.probe_sha256)
    with Path(args.output).open('x') as stream:stream.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'execution_source_verified':result['execution_source_verified'],
                      'omitted_metadata_files':len(result['omitted_packaging_metadata']),'errors':result['errors']}))
    raise SystemExit(0 if result['execution_source_verified'] else 2)
