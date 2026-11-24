import numpy as np
import pytest
from simpeople.core.deadweight import DeadweightDispatch,cabin_handoff


def board(d,aid='a',slot='s',**kw):
    return d.observe_boarding(aid,slot,76,inside=True,feet_supported=True,stable_s=.6,speed_mps=0,sim_time=1,**kw)


def test_duplicate_actor_never_adds_weight_and_slot_is_exclusive():
    d=DeadweightDispatch();assert board(d);assert not board(d,slot='another');assert d.load_kg==76
    with pytest.raises(ValueError):board(d,aid='b')


def test_weight_doors_and_independent_authorization_all_required():
    d=DeadweightDispatch(threshold_kg=70);board(d)
    for _ in range(3):assert d.advance(10)['upper_s_m']==0
    d.upper_closed=d.lower_closed=d.booth_closed=True
    assert d.advance(11)['upper_s_m']==0
    d.driver_release=True;d.advance(12)
    assert d.advance(29)['upper_s_m']==pytest.approx(56)
    for t in np.linspace(29,60,100):
        r=d.advance(t);assert r['upper_s_m']+r['lower_s_m']==pytest.approx(112)
    with pytest.raises(ValueError):board(d,aid='late',slot='late')


def test_pose_transfer_has_no_world_discontinuity():
    cabin=np.eye(4);cabin[3,:3]=[23,-14,56]
    world=np.eye(4);world[3,:3]=[24,-12,57]
    assert np.allclose(cabin_handoff(world,cabin)@cabin,world)


def test_midjourney_door_loss_aborts_and_cannot_be_hidden_by_driver_release():
    d=DeadweightDispatch(threshold_kg=70);board(d)
    d.upper_closed=d.lower_closed=d.booth_closed=d.driver_release=True
    d.advance(2);d.advance(5);d.booth_closed=False
    with pytest.raises(ValueError,match='door contact lost'):d.advance(6)


def test_clock_cannot_rewind_and_invalid_dispatch_configuration_is_rejected():
    with pytest.raises(ValueError):DeadweightDispatch(travel_s=0)
    d=DeadweightDispatch();d.advance(2)
    with pytest.raises(ValueError):d.advance(1)
    with pytest.raises(ValueError):d.advance(float('nan'))
