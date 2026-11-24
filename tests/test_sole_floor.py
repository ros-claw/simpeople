import numpy as np
import pytest
from simpeople.backends.native.sole_floor import SoleFloor


def test_shoe_clearance_accounts_for_tactile_strip_but_not_bench_height():
    boxes=[{'name':'tactile','kind':'solid','center':[0,.2,.01],'size':[2,.4,.02]},
           {'name':'bench','kind':'solid','center':[0,1,.5],'size':[1,.5,.1]}]
    f=SoleFloor(boxes)
    assert f.heights([[0,.2],[0,1],[4,.2]]).tolist()==[.02,0,0]
    assert f.correction(np.array([[0,.2,.003],[0,1,.003]]))==pytest.approx(.02)
    assert f.correction(np.array([[0,.2,.025]]))==0
