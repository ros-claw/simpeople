"""Independent array audit of the opt-in reusable Human81 SDK converter."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quaternion_pose(a,shape):
    a=np.asarray(a,dtype=float)
    if a.shape!=shape or not np.isfinite(a).all():raise ValueError('pose array shape or values invalid')
    norm=np.linalg.norm(a[...,3:],axis=-1)
    if abs(norm-1).max()>.01:raise ValueError('SDK quaternion normalization bound exceeded')
    a=a.copy();a[...,3:]/=norm[...,None];return a


def measure(source,recovered):
    if source.shape!=recovered.shape:raise ValueError('roundtrip shape mismatch')
    source=quaternion_pose(source,source.shape);recovered=quaternion_pose(recovered,source.shape)
    position=float(np.linalg.norm(source[...,:3]-recovered[...,:3],axis=-1).max())
    angle=float(np.degrees((Rotation.from_quat(source[...,3:].reshape(-1,4)).inv()*Rotation.from_quat(recovered[...,3:].reshape(-1,4))).magnitude()).max())
    return {'max_position_m':position,'max_angle_deg':angle,'within_2cm_2deg':position<=.02 and angle<=2}


def audit(folder,plan_path):
    folder=Path(folder);plan_path=Path(plan_path);errors=[];results=[];hashes={}
    try:
        plan=json.loads(plan_path.read_text());read=lambda n:json.loads((folder/n).read_text())
        if plan['run_id']!=folder.name:raise ValueError('wrong frozen converter run')
        for name,digest in plan['frozen_files'].items():
            if sha(name)!=digest:raise ValueError('frozen converter input changed: '+name)
        source=Path(plan['source'])
        if sha(source/'source_manifest.json')!=plan['source_manifest_sha256']:raise ValueError('source manifest changed')
        original=json.loads((source/'source_manifest.json').read_text());manifest=read('source_manifest.json')
        omitted={'src/rosclaw_simpeople.egg-info/'+n for n in ['PKG-INFO','SOURCES.txt','dependency_links.txt','entry_points.txt','requires.txt','top_level.txt']}
        if {n:h for n,h in manifest.items() if n.startswith('src/')}!={n:h for n,h in original.items() if n.startswith('src/') and n not in omitted}:
            raise ValueError('actual converter source differs from frozen candidate')
        if manifest['probe.py']!=sha(plan['argv'][1]):raise ValueError('actual converter probe changed')
        for name,digest in manifest.items():
            path=folder/'source_snapshot'/name
            if not path.resolve().is_relative_to((folder/'source_snapshot').resolve()) or sha(path)!=digest:raise ValueError('actual converter snapshot changed')
        for name,digest in read('input_references.json').items():
            if sha(name)!=digest or plan['frozen_files'].get(name)!=digest:raise ValueError('SDK reference array binding changed')
        done=read('completed.json');reported=read('converter_route_parity.json');inputs=read('source_snapshot/inputs.json')
        if not done['harness_completed'] or done['cases']!=6:raise ValueError('six-case converter harness incomplete')
        if sorted(c['case'] for c in reported['comparisons'])!=sorted(inputs['cases']):raise ValueError('converter denominator changed')
        sdk=Path(plan['argv'][plan['argv'].index('--sdk-run')+1])
        for result in reported['comparisons']:
            name=result['case'];case=inputs['cases'][name];world=np.asarray([r['world_pose'] for r in case['rows']],dtype=float)
            receipt=result['conversion_receipt'];artifact=Path(receipt['conversion_artifact'])
            if sha(artifact)!=receipt['conversion_artifact_sha256']:raise ValueError('converter artifact changed')
            profile=result['profile']
            if (profile['mapping_revision']!='native-sdk-actual-rig_via-human81_to-soma-local-v3'
                    or profile['intermediate_asset_sha256']!=sha(folder/'source_snapshot/human.usd')
                    or profile['retarget_route']!=['source','human81','soma78']):raise ValueError('converter profile route/asset binding changed')
            parity={}
            with np.load(artifact,allow_pickle=False) as actual,np.load(sdk/(name+'__prepared__True__via_human.npz'),allow_pickle=False) as expected:
                if not np.array_equal(actual['source_world'],world) or not np.array_equal(expected['source_world'],world):raise ValueError('converter used a different actual pose input')
                for a,b,count in [('source_to_human81','0_source_to_human',81),('human81_to_soma78','1_human_to_soma',78)]:
                    normalized=quaternion_pose(actual[a],(4,count,7));reference=quaternion_pose(expected[b],(4,count,7))
                    parity[a]=float(abs(normalized-reference).max())
                if max(parity.values())>1e-8:raise ValueError('reusable converter differs from verified SDK route')
                if actual['soma_local'].shape!=(4,77,7):raise ValueError('SDK Root was not explicitly projected to model77')
            path=Path(result['diagnostic']['artifact'])
            with np.load(path,allow_pickle=False) as arrays:
                if not np.array_equal(arrays['source_world'],world):raise ValueError('roundtrip used different input')
                metrics=measure(world,arrays['recovered_world'])
            if not metrics['within_2cm_2deg']:raise ValueError('module roundtrip exceeds original pose tolerance')
            results.append({'case':name,'samples':4,'stage_max_abs_error':parity,'roundtrip':metrics,
                            'descriptor_provenance':case['descriptor_provenance']})
            hashes[str(artifact)]=sha(artifact);hashes[str(path)]=sha(path)
    except (OSError,ValueError,KeyError,TypeError,IndexError) as error:errors.append(str(error))
    return {'run_id':folder.name,'converter_route_arrays_verified':not errors and len(results)==6,'errors':errors,
            'comparisons':results,'conversion_arrays_sha256':hashes,'plan_sha256':sha(plan_path),
            'qualified_generated_native_rigs':[],'scope':'Reusable converter SDK parity and full-joint roundtrip only. No model generation, actual animation playback, strict entry or cancellation qualification.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--plan',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    result=audit(args.run,args.plan);Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps({'verified':result['converter_route_arrays_verified'],'errors':result['errors']}))
    raise SystemExit(0 if result['converter_route_arrays_verified'] else 2)
