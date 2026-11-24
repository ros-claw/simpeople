import numpy as np
import pytest
from simpeople.motion.retarget_chain import retarget_chain


def poses(count=3):
    a=np.zeros((4,count,7));a[...,6]=1;return a


def test_each_stage_consumes_normalized_output_raw_evidence_is_preserved():
    original=poses();seen=[]
    def first(p):
        p[:,6]=1.005;return p
    def second(p):
        seen.append(p.copy());return p
    result,raw,errors=retarget_chain(original,[('to_human',3,first),('to_soma',3,second)])
    assert np.array_equal(original,poses())
    assert np.array_equal(result,original)
    assert np.all(raw['to_human'][...,6]==1.005)
    assert all(np.array_equal(p,original[0]) for p in seen)
    assert errors['to_human']==pytest.approx(.005) and errors['to_soma']==0


@pytest.mark.parametrize('bad',['nan','quat','shape','empty_input','empty_route','duplicate_stage','boolean_count'])
def test_bad_route_never_repairs_or_drops_channels(bad):
    original=poses();stages=[('s',3,lambda p:p)]
    if bad=='nan':original[0,0,0]=np.nan
    elif bad=='quat':stages=[('s',3,lambda p:p*2)]
    elif bad=='shape':stages=[('s',2,lambda p:p)]
    elif bad=='empty_input':original=original[:0]
    elif bad=='empty_route':stages=[]
    elif bad=='duplicate_stage':stages*=2
    else:stages=[('s',True,lambda p:p)]
    with pytest.raises(ValueError):retarget_chain(original,stages)


def test_stage_callback_cannot_mutate_input_or_prior_saved_stage():
    original=poses();before=original.copy()
    def mutate(p):p[:,0]=42;return p
    result,raw,_=retarget_chain(original,[('first',3,lambda p:p),('last',3,mutate)])
    assert np.array_equal(original,before) and np.array_equal(raw['first'],before)
    assert np.all(result[...,0]==42)
