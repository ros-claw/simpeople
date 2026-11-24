import copy
import math
import pytest
from simpeople.core.gestures import angle,rotate,stage_vector,public_vector,measure,return_ready,validate_target
from simpeople.core.errors import SimPeopleError


def pose():
    return {'ready':True,'position_m':[0,0,0],'speed_mps':0,'facing_direction':[0,-1,0],
        'head_local_forward':[0,-1,0],'joint_rotations_xyzw_stage':{'Head':[0,0,0,1]},
        'joints_m':{'Head':[0,0,1.6],'RightArm':[-.2,0,1.4],'RightForeArm':[-.2,0,1.1],'RightHand':[-.2,0,.85]}}


def test_quaternion_and_y_up_vectors_preserve_direction():
    q=[0,0,math.sqrt(.5),math.sqrt(.5)];v=[1,0,0]
    assert rotate(q,v)==pytest.approx([0,1,0])
    assert rotate(q,rotate(q,v),inverse=True)==pytest.approx(v)
    assert public_vector(stage_vector([.2,.3,.4],'Y'),'Y')==[.2,.3,.4]
    assert angle([0,0,0],[0,1,0]) is None


def test_rest_bind_head_axis_is_used_instead_of_an_idle_head_assumption():
    b=pose();b['joint_rotations_xyzw_stage']['Head']=[0,0,math.sin(.2),math.cos(.2)]
    now=pose()
    result=measure('head_look',None,[0,-1,1.6],b,now)
    assert result['head_angle_error_deg']==pytest.approx(0) and result['aligned']


def test_endpoint_success_does_not_hide_root_motion_or_bone_stretch():
    b=pose();now=copy.deepcopy(b);target=[-.2,0,.85]
    assert measure('reach_hand','right',target,b,now)['aligned']
    now['position_m'][0]=.1
    assert not measure('reach_hand','right',target,b,now)['aligned']
    now=copy.deepcopy(b);now['joints_m']['RightForeArm'][2]=1.2
    assert not measure('reach_hand','right',target,b,now)['aligned']


def test_return_uses_shoulder_relative_hand_not_a_stale_world_point():
    b=pose();now=copy.deepcopy(b)
    for p in now['joints_m'].values():p[0]+=.15
    now['position_m'][0]+=.15
    assert return_ready('reach_hand','right',b,now)
    now['joints_m']['RightHand'][1]=-.4
    assert not return_ready('reach_hand','right',b,now)


def test_unreachable_hand_and_moving_actor_are_rejected():
    domain={'min_height_m':1,'max_height_m':1.5,'min_forward_m':.2,'max_forward_m':.5,'max_arm_fraction':.9}
    b=pose();validate_target('reach_hand','right',[-.2,-.3,1.2],b,domain)
    with pytest.raises(SimPeopleError) as error:validate_target('reach_hand','right',[-.2,-2,1.2],b,domain)
    assert error.value.code=='TARGET_UNREACHABLE'
    b['speed_mps']=.3
    with pytest.raises(SimPeopleError) as error:validate_target('reach_hand','right',[-.2,-.3,1.2],b,domain)
    assert error.value.code=='ACTOR_BUSY'


def test_head_behind_actor_is_not_silently_turned_into_whole_body_facing():
    domain={'min_distance_m':.4,'max_distance_m':2,'max_yaw_deg':45,'max_pitch_deg':35}
    validate_target('head_look',None,[.3,-1,1.6],pose(),domain)
    with pytest.raises(SimPeopleError) as error:validate_target('head_look',None,[0,1,1.6],pose(),domain)
    assert error.value.code=='TARGET_UNREACHABLE'
