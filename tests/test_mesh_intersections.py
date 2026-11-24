import numpy as np
import pytest
from simpeople.backends.native.mesh_intersections import triangle_pairs_intersect,surface_intersections

@pytest.mark.parametrize('other,expected',[
    ([[.2,.2,-1],[.2,.2,1],[.8,.2,0]],True),
    ([[.2,.2,1],[.2,.8,1],[.8,.2,1]],False),
    ([[.1,.1,0],[.2,.1,0],[.1,.2,0]],True),
    ([[2,2,0],[3,2,0],[2,3,0]],False),
    ([[1,0,0],[2,0,0],[1,1,0]],True),
])
def test_crossing_displaced_coplanar_and_touch(other,expected):
    a=np.array([[[0,0,0],[1,0,0],[0,1,0]]],float);b=np.array([other],float)
    assert bool(triangle_pairs_intersect(a,b)[0])==expected
    assert bool(surface_intersections(a,b)['intersecting_pairs'])==expected
