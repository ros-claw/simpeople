import pytest
from simpeople.core.pursuit import PursuitMemory,visible

def test_memory_uses_only_visible_samples_and_reacquires():
    b=PursuitMemory();assert b.update(0,'human',None).target_m is None
    assert b.update(.25,'human',(2,0,0)).state=='PURSUE'
    assert b.update(.50,'human',(2.5,0,0)).state=='PURSUE'
    lost=b.update(.75,'human',None);assert lost.state=='LAST_SEEN' and lost.observation_m is None
    search=b.update(1.5,'human',None);assert search.state=='SEARCH' and search.target_m==(2.5,0,0)
    assert b.update(1.75,'human',(3,2,0)).state=='PURSUE'

def test_identity_change_resets_velocity_and_clock_is_monotonic():
    b=PursuitMemory();b.update(0,'a',(0,0,0));b.update(.25,'a',(1,0,0));v=b.update(.5,'b',(5,5,0));assert v.target_m==(5,5,0)
    with pytest.raises(ValueError):b.update(.5,'b',(5,5,0))

def test_visibility_respects_actual_column_and_fov():
    box=(([1,-.4,0],[2,.4,3]),)
    assert not visible((0,0,0),(1,0,0),(3,0,0),box)
    assert visible((0,0,0),(1,0,0),(3,3,0),box)
    assert not visible((0,0,0),(1,0,0),(-3,0,0),())
