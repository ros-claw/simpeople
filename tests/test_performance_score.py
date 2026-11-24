import numpy as np
from simpeople.backends.native.performance_score import DoorScore,SameDirectionScore


def test_committed_attack_does_not_chase_the_new_escape_position():
    s=DoorScore();old=s.attack_target(4.65)
    assert np.allclose(s.attack_target(9),old)
    assert np.linalg.norm(s.root('H01',7)[0]-old[:2])>2
    # Random-order score evaluation has no hidden seeking/target mutation.
    before=s.root('F02',6.5)
    for t in [9,0,8,5,3]:s.root('H01',t);s.attack_target(t)
    assert np.allclose(s.root('F02',6.5)[0],before[0])


def test_root_paths_are_continuous_and_shared_destination_has_no_attack():
    s=DoorScore()
    for aid,path in s.paths.items():
        for knot in path.knots[1:-1]:
            p,v=path.sample(knot.t);a,va=path.sample(knot.t-1e-6);b,vb=path.sample(knot.t+1e-6)
            assert np.linalg.norm(a-b)<1e-4
            assert np.linalg.norm(va-vb)<1e-3
    n=SameDirectionScore()
    assert n.attack_target(6) is None
    assert np.allclose(n.root('H01',9)[0]-n.root('F02',9)[0],n.root('H01',0)[0]-n.root('F02',0)[0])


def test_escape_passes_west_of_existing_b3_before_turning_into_the_gate():
    s=DoorScore()
    for t in np.linspace(6.2,10,381):
        x,y=s.root('H01',t)[0]
        # Conservative authored root radius; full skin checked in Kit too.
        assert not (24.525-.26<x<26.175+.26 and 6.45-.26<y<6.995+.26),(t,x,y)
