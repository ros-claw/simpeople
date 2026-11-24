"""Actual SDK parity check for the opt-in NativePoseConverter Human81 route."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser()
    for name in ['run-id','workspace-root','source-root','inputs','sdk-run','model-rig','soma','human']:
        p.add_argument('--'+name,required=True)
    p.add_argument('--gpu',type=int,default=3);args=p.parse_args()
    root=Path(args.workspace_root);out=root/'runs'/args.run_id;out.mkdir(exist_ok=False)
    snapshot=out/'source_snapshot';snapshot.mkdir();source=Path(args.source_root)
    shutil.copytree(source/'src',snapshot/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.egg-info'))
    for name,path in [('inputs.json',args.inputs),('rig.json',args.model_rig),('soma.usda',args.soma),('human.usd',args.human),('probe.py',__file__)]:shutil.copyfile(path,snapshot/name)
    inputs=json.loads((snapshot/'inputs.json').read_text());sdk=Path(args.sdk_run)
    references={}
    for name in inputs['cases']:
        path=sdk/(name+'__prepared__True__via_human.npz');references[str(path)]=sha(path)
    (out/'input_references.json').write_text(json.dumps(references,indent=2)+'\n')
    (out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snapshot)):sha(f) for f in snapshot.rglob('*') if f.is_file()},indent=2)+'\n')
    sys.path.insert(0,str(snapshot/'src'));sys.argv=[sys.argv[0]]
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});code=0
    try:
        import numpy as np
        import carb.settings,omni.kit.app,omni.usd,threading
        from pxr import UsdGeom
        from types import SimpleNamespace
        from simpeople.backends.native.pose_bridge import NativePoseConverter
        manager=omni.kit.app.get_app().get_extension_manager();assert manager.set_extension_enabled_immediate('omni.anim.behavior.core',True)
        carb.settings.get_settings().set('/persistent/exts/omni.anim.retarget.core/enableFeetIK',False)
        omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();UsdGeom.SetStageUpAxis(stage,'Z');UsdGeom.SetStageMetersPerUnit(stage,1)
        thread=threading.get_ident()
        def assert_thread():assert threading.get_ident()==thread
        runtime={e['id'].split('-')[0]:e['id'] for e in manager.get_extensions() if e.get('enabled') and any(n in e['id'] for n in ['omni.anim.behavior.core','omni.anim.retarget.core'])}
        rig=json.loads((snapshot/'rig.json').read_text());results=[]
        for name,case in inputs['cases'].items():
            actor=name.split('__')[0];asset_id='default' if actor=='operator' else 'female_adult_business_02'
            asset=next(a for a in inputs['assets'] if a['asset_id']==asset_id);assert sha(asset['source_uri'])==asset['content_hash']
            facade=SimpleNamespace(stage=stage,namespace='/Converter/'+name,assert_thread=assert_thread,runtime_revision=runtime)
            converter=NativePoseConverter(facade,asset['source_uri'],snapshot/'soma.usda',rig,out/name,
                active_descriptor=case['active_descriptor'],intermediate_skeleton_path=snapshot/'human.usd')
            rows=copy.deepcopy(case['rows'])
            for row in rows:row['source_asset_sha256']=asset['content_hash']
            converted,receipt=converter.convert_world_history(rows,converter.profile)
            artifact=Path(receipt['conversion_artifact'])
            with np.load(artifact,allow_pickle=False) as saved,np.load(sdk/(name+'__prepared__True__via_human.npz'),allow_pickle=False) as reference:
                parity={}
                for actual_key,expected_key in [('source_to_human81','0_source_to_human'),('human81_to_soma78','1_human_to_soma')]:
                    values=saved[actual_key].copy();values[:,:,3:]/=np.linalg.norm(values[:,:,3:],axis=-1,keepdims=True)
                    parity[actual_key]=float(abs(values-reference[expected_key]).max())
                assert np.array_equal(saved['source_world'],np.asarray([r['world_pose'] for r in case['rows']]))
            diagnostic=converter.diagnose_roundtrip(receipt)
            results.append({'case':name,'four_actual_samples':len(rows),'stage_parity_max_abs':parity,
                'passed':max(parity.values())<=1e-8,'source_descriptor_provenance':case['descriptor_provenance'],
                'conversion_receipt':receipt,'profile':converter.profile,'diagnostic':diagnostic,
                'model_shape':list(converted.shape),'source_rows_augmented_only_with_verified_asset_hash':True})
            converter.close()
        result={'harness_completed':True,'all_stage_arrays_match_verified_sdk_reference':all(x['passed'] for x in results),
            'comparisons':results,'qualified_generated_native_rigs':[],'model_requests_added':0,
            'scope':'Reusable converter parity against verified SDK arrays on the same six four-frame inputs. No new actor playback or generated/cancel qualification.'}
        (out/'converter_route_parity.json').write_text(json.dumps(result,indent=2)+'\n')
        (out/'completed.json').write_text(json.dumps({'harness_completed':True,'cases':len(results),'passed':result['all_stage_arrays_match_verified_sdk_reference']},indent=2)+'\n')
        print('CONVERTER_ROUTE_PARITY',result['all_stage_arrays_match_verified_sdk_reference'],flush=True)
        code=0 if result['all_stage_arrays_match_verified_sdk_reference'] else 2
    except Exception:
        import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
    finally:app.close(exit_code=code)
    return code


if __name__=='__main__':raise SystemExit(main())
