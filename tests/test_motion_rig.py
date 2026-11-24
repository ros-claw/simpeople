import math
import numpy as np
import pytest
from simpeople.motion.rig import forward_kinematics,convert_root,multiply,project_to_model,expand_from_model,validate_poses


def test_global_basis_change_is_applied_only_to_root():
    poses=np.zeros((1,2,7));poses[:,:,6]=1;poses[0,0,:3]=[0,1,0];poses[0,1,:3]=[0,1,0]
    q=[math.sqrt(.5),0,0,math.sqrt(.5)];converted=convert_root(poses,q)
    assert converted[0,1].tolist()==poses[0,1].tolist()
    world=forward_kinematics(converted,[-1,0])
    assert world[0,0,:3]==pytest.approx([0,0,1])
    assert world[0,1,:3]==pytest.approx([0,0,2])


def test_projection_uses_global_pose_when_an_extra_joint_separates_model_joints():
    ref=np.zeros((4,7));ref[:,6]=1;ref[1,:3]=[0,.3,0];ref[2,:3]=[.2,0,0];ref[3,:3]=[.4,0,0]
    poses=ref[None,:,:].copy();poses[0,1,3:]=[0,0,math.sqrt(.5),math.sqrt(.5)]
    rig={'parents':[-1,0,1,2],'reference_local':ref.tolist(),'model_indices':[0,1,3]}
    rebuilt=expand_from_model(project_to_model(poses,rig),rig)
    assert forward_kinematics(rebuilt,rig['parents'])==pytest.approx(forward_kinematics(poses,rig['parents']))
    assert rebuilt[0,2]==pytest.approx(ref[2])


@pytest.mark.parametrize('bad',[float('nan'),float('inf')])
def test_non_finite_pose_is_never_accepted(bad):
    poses=np.zeros((1,1,7));poses[:,:,6]=1;poses[0,0,0]=bad
    with pytest.raises(ValueError):validate_poses(poses,1)


def test_zero_quaternion_is_not_silently_normalized_to_identity():
    with pytest.raises(ValueError):validate_poses(np.zeros((1,1,7)),1)


def test_actual_world_samples_roundtrip_without_changing_segment_lengths():
    from simpeople.motion.rig import world_to_local
    local=np.array([[[2,3,1,0,0,.707106781,.707106781],[.3,0,0,0,0,0,1],[0,.25,0,.382683432,0,0,.923879533]]])
    parents=[-1,0,1];world=forward_kinematics(local,parents)
    restored=world_to_local(world,parents)
    np.testing.assert_allclose(restored,local,atol=1e-8)


def test_reference_decoder_never_stretches_disconnected_modeled_finger_tips():
    from simpeople.motion.rig import decode_reference_pose
    ref=np.zeros((4,7));ref[:,6]=1;ref[1,:3]=[0,.3,0];ref[2,:3]=[.03,0,0];ref[3,:3]=[.02,0,0]
    rig={'parents':[-1,0,1,2],'reference_local':ref.tolist(),'model_indices':[0,1,3]}
    observed=ref[None].copy();observed[0,2,3:]=[0,0,math.sqrt(.5),math.sqrt(.5)]
    model=project_to_model(observed,rig);decoded=decode_reference_pose(model,rig)
    np.testing.assert_allclose(decoded[0,1:,:3],ref[1:,:3])
    np.testing.assert_allclose(decoded[0,2:],ref[2:])
    np.testing.assert_allclose(decoded[0,:2,3:],observed[0,:2,3:])
