import numpy as np
import pytest
from simpeople.backends.native.linear_sweep import triangle_sweep,swept_surface_intersections


def test_crossing_between_clear_endpoints_is_detected():
    a=np.array([[0.,0,0],[1,0,0],[0,1,0]])
    b=np.array([[.1,.1,-.4],[.4,.1,-.4],[.1,.4,-.4]])
    end=b+[0,0,.8]
    t,_=triangle_sweep(a,a,b,end)
    assert t==pytest.approx(.5)
    report=swept_surface_intersections(a[None],a[None],b[None],end[None])
    assert report['contact_pairs']==1


def test_separated_sweep_is_clear_and_coplanar_motion_is_not_certified():
    a=np.array([[0.,0,0],[1,0,0],[0,1,0]])
    b=a+[0,0,2]
    assert swept_surface_intersections(a[None],a[None],b[None],(b+[.1,0,0])[None])['candidate_pairs']==0
    # Coplanar crossing must never silently pass merely because its cubic is zero.
    b=a+[-2,0,0];t,unresolved=triangle_sweep(a,a,b,b+[4,0,0])
    assert t is not None or unresolved
    accelerated=swept_surface_intersections(a[None],a[None],b[None],(b+[4,0,0])[None])
    assert accelerated['contact_pairs'] or accelerated['unresolved_coplanar_pairs']
