
def test_spatial_candidates_preserve_exact_overlap_pairs():
    import math
    import random
    from simpeople.core.quality import nearby_pairs
    rng=random.Random(1031);radii={'small':.2,'large':.7}
    ready={str(i):{'asset_id':rng.choice(list(radii)),'position_m':[rng.uniform(-4,4),rng.uniform(-4,4),rng.uniform(0,2)]} for i in range(300)}
    def overlaps(a,b):
        p,q=ready[a]['position_m'],ready[b]['position_m']
        return abs(p[2]-q[2])<.8 and math.dist(p[:2],q[:2])<.8*(radii[ready[a]['asset_id']]+radii[ready[b]['asset_id']])
    ids=list(ready)
    brute={frozenset((a,b)) for i,a in enumerate(ids) for b in ids[i+1:] if overlaps(a,b)}
    candidates=list(nearby_pairs(ready,radii))
    assert len(candidates)<len(ids)*(len(ids)-1)//2
    assert {frozenset((a,b)) for a,b in candidates if overlaps(a,b)}==brute
    assert len(candidates)==len({frozenset(p) for p in candidates})
