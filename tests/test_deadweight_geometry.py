"""Regression for the rail transform defect found in the first wide render."""
import pytest
pytest.importorskip('pxr.Usd')
from pxr import Usd,UsdGeom,Gf
from simpeople.backends.native.deadweight_set import box


def test_long_rail_rotation_preserves_56_metre_rise_in_actual_usd_transform():
    stage=Usd.Stage.CreateInMemory();UsdGeom.SetStageMetersPerUnit(stage,1)
    rail=box(stage,'/Rail',(0,0,0),(112,.12,.16),(.2,.3,.4))
    rail.AddRotateYOp().Set(-30)
    matrix=UsdGeom.XformCache().GetLocalToWorldTransform(rail.GetPrim())
    a=matrix.Transform(Gf.Vec3d(-56,0,0));b=matrix.Transform(Gf.Vec3d(56,0,0))
    assert (b-a).GetLength()==pytest.approx(112)
    assert b[2]-a[2]==pytest.approx(56)
    assert b[0]-a[0]==pytest.approx(96.99484522385713)
