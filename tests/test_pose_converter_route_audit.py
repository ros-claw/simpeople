import importlib.util
from pathlib import Path
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

spec=importlib.util.spec_from_file_location('converter_route_audit',Path(__file__).parents[1]/'scripts/audit_pose_converter_route.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def poses():
    result=np.zeros((4,101,7));result[...,6]=1;return result


def test_full_joint_roundtrip_checks_angle_as_well_as_position():
    source=poses();recovered=source.copy();recovered[:,100,3:]=Rotation.from_euler('x',45,degrees=True).as_quat()
    result=m.measure(source,recovered)
    assert result['max_position_m']==0 and result['max_angle_deg']==pytest.approx(45)
    assert not result['within_2cm_2deg']


def test_full_joint_roundtrip_does_not_ignore_a_single_foot():
    source=poses();recovered=source.copy();recovered[0,3,0]=.021
    assert not m.measure(source,recovered)['within_2cm_2deg']


def test_quaternion_sign_and_bounded_numeric_roundoff():
    source=poses();recovered=source.copy();recovered[...,6]=-1.001
    assert m.measure(source,recovered)['within_2cm_2deg']
    assert np.all(recovered[...,6]==-1.001)


@pytest.mark.parametrize('bad',['count','nan','zero_quaternion','large_renormalization'])
def test_invalid_stage_data_is_rejected(bad):
    a=poses();shape=a.shape
    if bad=='count':a=a[:,:100]
    elif bad=='nan':a[0,0,0]=float('nan')
    elif bad=='zero_quaternion':a[0,0,6]=0
    else:a[0,0,6]=1.011
    with pytest.raises(ValueError):m.quaternion_pose(a,shape)


def test_missing_plan_cannot_verify_converter(tmp_path):
    plan=tmp_path/'plan.json';plan.write_text('{}')
    assert not m.audit(tmp_path,plan)['converter_route_arrays_verified']
