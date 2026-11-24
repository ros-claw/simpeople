"""CPU-only official SOMA rig extraction and deterministic no-model fixtures."""
import argparse,hashlib,json,math,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--upstream',required=True);p.add_argument('--output',required=True);args=p.parse_args()
upstream=Path(args.upstream).resolve();out=Path(args.output).resolve();out.mkdir(exist_ok=False,parents=True)
sys.path.insert(0,str(upstream));sys.path.insert(0,str(ROOT/'src'))
import numpy as np
import warp as wp
wp.init();wp.set_device('cpu')
from motionbricks.io.usd import load_skeleton_from_usd
from simpeople.motion.rig import validate_rig,rig_digest,convert_root,project_to_model,expand_from_model,forward_kinematics,multiply
from pxr import Usd,UsdGeom
source=upstream/'motionbricks/assets/human/soma_base_skel_minimal_no_root.usd';prim='/OUTPUT/c_skeleton_grp/Hips'
skeleton=load_skeleton_from_usd(source,prim);names=skeleton.joint_names;parents=skeleton.parent_indices.numpy().tolist();reference=skeleton.reference_local_transforms.numpy()
model=json.loads((upstream/'motionbricks/assets/onnx/soma/soma_n1.json').read_text())['joint_names']
rotation=np.array([math.sqrt(.5),0,0,math.sqrt(.5)])
reference=convert_root(reference[None,:,:],rotation)[0]
rig={'schema_version':'simpeople.soma-rig.v1','joint_names':names,'parents':parents,'reference_local':reference.tolist(),
 'model_joint_names':model,'model_indices':[names.index(n) for n in model],'extra_joint_policy':'reference',
 'frame_spec':{'units':'metres','up_axis':'Z','root_space':'world','child_space':'joint-local','quaternion':'xyzw'},
 'source_usd':str(source),'skeleton_prim_path':prim,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
 'source_meters_per_unit':UsdGeom.GetStageMetersPerUnit(Usd.Stage.Open(str(source))),'model_to_runtime_xyzw':rotation.tolist()}
validate_rig(rig);rig['rig_sha256']=rig_digest(rig);(out/'rig.json').write_text(json.dumps(rig,indent=2)+'\n')
fixtures={}
fixtures['reference']=np.repeat(reference[None,:,:],31,axis=0)
fixtures['translate_x']=fixtures['reference'].copy();fixtures['translate_x'][:,0,0]+=np.linspace(0,1,31)
for sign in [-1,1]:
 poses=fixtures['reference'].copy()
 for i,t in enumerate(np.linspace(0,sign*math.pi/2,31)):
  poses[i,0,3:]=multiply([0,0,math.sin(t/2),math.cos(t/2)],reference[0,3:])
 fixtures['yaw_'+str(sign)]=poses
poses=fixtures['reference'].copy();index=names.index('LeftArm')
for i,t in enumerate(np.linspace(0,math.pi/6,31)):poses[i,index,3:]=multiply(reference[index,3:],[math.sin(t/2),0,0,math.cos(t/2)])
fixtures['left_arm_30deg']=poses
checks=[]
for name,poses in fixtures.items():
 np.savez(out/(name+'.npz'),local_poses=poses.astype(np.float32))
 expanded=expand_from_model(project_to_model(poses,rig),rig)
 original_world=forward_kinematics(poses,parents);expanded_world=forward_kinematics(expanded,parents)
 error=float(np.max(np.linalg.norm(original_world[:,:,:3]-expanded_world[:,:,:3],axis=-1)))
 assert error<1e-5,(name,error)
 checks.append({'name':name,'frames':len(poses),'projection_full_joint_max_error_m':error,'sha256':hashlib.sha256((out/(name+'.npz')).read_bytes()).hexdigest()})
(out/'fixture_manifest.json').write_text(json.dumps({'model_used':False,'rig_sha256':rig['rig_sha256'],'checks':checks},indent=2)+'\n')
print('SOMA_RIG_FIXTURES_EXPORTED',len(names),'joints',len(checks),'fixtures')
