"""Twenty fixed official FP32/N=1 requests, retaining raw and corrected outputs."""
import argparse,hashlib,json,math,shutil,sys,time,traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--upstream',required=True);p.add_argument('--rig-dir',required=True);p.add_argument('--output',required=True);p.add_argument('--device',default='cuda:3');args=p.parse_args()
out=Path(args.output).resolve();out.mkdir(exist_ok=False,parents=True);snap=out/'source_snapshot';snap.mkdir()
for name in ['src','workers']:shutil.copytree(ROOT/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n')
sys.path.insert(0,str(snap/'src'));sys.path.insert(0,str(snap/'workers/motionbricks'))
from backend import SomaBackend,sha256
from simpeople.motion.rig import forward_kinematics,multiply
import numpy as np
rig_dir=Path(args.rig_dir).resolve();shutil.copy2(rig_dir/'rig.json',out/'rig.json')
began=time.monotonic();backend=None
try:
    backend=SomaBackend(args.upstream,out/'rig.json',args.device,str(Path(args.upstream).resolve()/'.trt-cache'))
    (out/'model_provenance.json').write_text(json.dumps(backend.provenance,indent=2)+'\n');print('MODEL_READY',flush=True)
    cases=[];checks=[]
    for i in range(20):
        context=backend.sample_idle(.9);target=backend.sample_idle(1.4)
        family=i//5;amount=(i%5-2)
        if family==0:target[:,0,0]+=.04*amount
        elif family==1:
            angle=math.radians(7.5*amount);target[:,0,3:]=multiply([0,0,math.sin(angle/2),math.cos(angle/2)],target[:,0,3:])
        else:
            name='LeftArm' if family==2 else 'RightArm';joint=backend.rig['joint_names'].index(name);angle=math.radians(7.5*amount)
            target[:,joint,3:]=multiply(target[:,joint,3:],[math.sin(angle/2),0,0,math.cos(angle/2)])
        entry={'case_id':f'case_{i:02d}','family':['translation','turn','left_arm','right_arm'][family],'parameter':amount}
        directory=out/entry['case_id'];directory.mkdir();np.savez(directory/'context.npz',local_poses=context);np.savez(directory/'target.npz',local_poses=target)
        try:
            result=backend.generate(context,target);poses=result['local_poses'];raw=result['raw_local_poses']
            np.savez(directory/'raw_network.npz',features=result['raw_network_features'],num_tokens=result['raw_num_tokens'])
            np.savez(directory/'raw_decoded.npz',local_poses=raw)
            np.savez(out/(entry['case_id']+'.npz'),local_poses=poses,foot_contacts=result['foot_contacts'])
            world=forward_kinematics(poses,backend.rig['parents']);raw_world=forward_kinematics(raw,backend.rig['parents'])
            wanted=forward_kinematics(target[:1],backend.rig['parents'])[0];prior=forward_kinematics(context[-1:],backend.rig['parents'])[0]
            end=float(np.linalg.norm(world[-1,:,:3]-wanted[:,:3],axis=-1).max());start=float(np.linalg.norm(world[0,:,:3]-prior[:,:3],axis=-1).max())
            correction=float(np.linalg.norm(world[:,:,:3]-raw_world[:,:,:3],axis=-1).max())
            step=float(np.linalg.norm(np.diff(poses[:,0,:3],axis=0),axis=-1).max())
            ok=end<=.005 and start<=.005 and step<=.15
            entry.update(passed=bool(ok),frames=len(poses),start_joint_error_m=start,end_joint_error_m=end,maximum_correction_m=correction,
                maximum_root_step_m=step,wall_s=result['wall_s'],engine_stage_ms=result['engine_stage_ms'])
            checks.append({'name':entry['case_id'],'frames':len(poses),'sha256':sha256(out/(entry['case_id']+'.npz'))})
        except Exception as error:entry.update(passed=False,error=str(error),traceback=traceback.format_exc())
        cases.append(entry);(directory/'result.json').write_text(json.dumps(entry,indent=2)+'\n');print('MODEL_CASE',entry['case_id'],entry['passed'],entry.get('frames'),flush=True)
    result={'passed':all(c['passed'] for c in cases),'model_used':True,'case_denominator':20,'cases':cases,'total_wall_s':time.monotonic()-began,
        'limits':'Actual official FP32/N=1 inference and endpoint correction; no Isaac/native playback acceptance or physical contact claim.'}
    (out/'model_acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'fixture_manifest.json').write_text(json.dumps({'model_used':True,'rig_sha256':backend.rig['rig_sha256'],'checks':checks,'model_provenance':backend.provenance,'all_model_cases_passed':result['passed']},indent=2)+'\n')
    print('MODEL_20_DONE',result['passed'],flush=True)
except Exception:
    (out/'failed.txt').write_text(traceback.format_exc());raise
finally:
    if backend:backend.close()
if not result['passed']:raise SystemExit(2)
