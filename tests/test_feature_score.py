import numpy as np
from simpeople.backends.native.platform04_feature_score import FeatureScore,PARTS

def test_feature_roots_do_not_jump_at_editorial_or_door_boundaries():
    s=FeatureScore()
    assert len(s.paths)==24
    for aid in s.paths:
        for t in [9,21,25,28,33,46,53,63,77,80,84]:
            assert np.linalg.norm(s.root(aid,t+.00001)[0]-s.root(aid,t-.00001)[0])<.001,(aid,t)

def test_gate_waits_for_every_survivor_and_door_commit_stays_fixed():
    s=FeatureScore()
    assert s.gate(79.05)==-6.35
    for aid in ['H01','H02','H03']:
        assert s.root(aid,79.05)[0][1]>10.45
    assert np.allclose(s.door.attack_target(5),s.door.attack_target(9))
    assert s.root('H01',63)[0][1]<6
    assert set(s.paths)==set().union(*(set(p[2]) for p in PARTS.values()))
