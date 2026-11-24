import numpy as np
import pytest

from simpeople.backends.native.local_pose import FixedAnatomy, slerp


def test_half_turn_transition_preserves_arm_and_leg_lengths():
    names = ['root', 'root/shoulder', 'root/shoulder/elbow',
             'root/shoulder/elbow/wrist', 'root/thigh', 'root/thigh/knee']
    p = np.array([[0,0,0], [0,0,1], [.3,0,1], [.55,0,1], [0,0,.8], [0,0,.4]])
    q = np.tile([0.,0,0,1], (6,1))
    anatomy = FixedAnatomy(names, p, q)
    a = anatomy.from_global(p, q)
    b = anatomy.from_global(p, q)
    b.rotations[1] = [0,0,1,0]
    b.rotations[4] = [0,1,0,0]
    for weight in np.linspace(0,1,101):
        world, _ = anatomy.forward(anatomy.blend(a,b,weight))
        assert np.linalg.norm(world[2]-world[1]) == pytest.approx(.3)
        assert np.linalg.norm(world[3]-world[2]) == pytest.approx(.25)
        assert np.linalg.norm(world[5]-world[4]) == pytest.approx(.4)
    other, _ = anatomy.forward(b)
    # This reproduces the old failure: world-space position mixing collapses it.
    old_midpoint = (p+other)/2
    assert np.linalg.norm(old_midpoint[3]-old_midpoint[2]) < 1e-12


def test_quaternion_sign_and_free_root_translation_do_not_change_anatomy():
    p=np.array([[0.,0,0], [1,0,0], [2,0,0]])
    q=np.tile([0.,0,0,1], (3,1))
    rig=FixedAnatomy(['root','root/a','root/a/b'],p,q)
    a=rig.from_global(p,q);b=rig.from_global(p+[3,2,1],-q)
    world,rot=rig.forward(rig.blend(a,b,.5))
    np.testing.assert_allclose(world,p+[1.5,1,.5])
    np.testing.assert_allclose(np.linalg.norm(rot,axis=1),1)
    np.testing.assert_allclose(slerp(q,-q,.3),q)
