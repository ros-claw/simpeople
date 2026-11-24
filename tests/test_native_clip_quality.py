import pytest
from simpeople.core.clip_quality import LONG_BONES,validate_native_sample


def test_retarget_finite_garbage_is_rejected_before_native_play():
    names=sorted(LONG_BONES);reference={n:.3 for n in names};q=[[0,0,0,1]]*len(names)
    assert validate_native_sample(names,[[.3,0,0]]*len(names),q,reference)==0
    with pytest.raises(ValueError,match='bone length'):
        validate_native_sample(names,[[1e-38,0,0]]*len(names),q,reference)


def test_missing_or_non_unit_retarget_joints_are_rejected():
    names=sorted(LONG_BONES);reference={n:.3 for n in names}
    with pytest.raises(ValueError,match='non-unit'):
        validate_native_sample(names,[[.3,0,0]]*len(names),[[0,0,0,0]]*len(names),reference)
    with pytest.raises(ValueError,match='required long bones'):
        validate_native_sample(names[:-1],[[.3,0,0]]*(len(names)-1),[[0,0,0,1]]*(len(names)-1),reference)


def test_generated_transition_does_not_loop_back_to_its_first_pose():
    from simpeople.core.clip_quality import phase_ranges
    phases=phase_ranges('transition_then_hold',0,25)
    assert phases['ActionStart']==[0,25]
    assert phases['ActionLoop']==phases['ActionEnd']==[25,26]
    assert phase_ranges('transition_then_hold',0,25,15)['ActionLoop']==[25,40]
    for bad in [0,31,True,1.5]:
        with pytest.raises(ValueError):phase_ranges('transition_then_hold',0,25,bad)
    with pytest.raises(ValueError):phase_ranges('unknown',0,25)
    with pytest.raises(ValueError):phase_ranges('loop',1,0)


def test_generated_out_and_back_uses_native_start_goal_loop_and_return_end():
    from simpeople.core.clip_quality import phase_ranges
    spans={'ActionStart':[0,120],'ActionLoop':[120,195],'ActionEnd':[195,320]}
    assert phase_ranges('out_and_back',0,320,ranges=spans)==spans
    for bad in [{**spans,'ActionLoop':[119,195]},{**spans,'ActionEnd':[195,321]},{**spans,'ActionStart':[0,float('nan')]}]:
        with pytest.raises(ValueError):phase_ranges('out_and_back',0,320,ranges=bad)
