import math
from dataclasses import replace
import pytest
from simpeople.core.funicular import Funicular,FunicularParameters

def moving(a=4800,b=4000,**kwargs):
    p=FunicularParameters(empty_A_kg=a,empty_B_kg=b,water_B_kg=0,speed_limit_mps=10)
    c=Funicular(p,q=56,auto_dock=False,**kwargs);c.doors_closed=c.authorized=True;assert c.release();return c

def test_mass_is_causal_equal_swap_and_increment():
    equal=moving(4000,4000);equal.step(.01);assert equal.v==0 and equal.q==56
    heavy=moving();heavy.step(.01);swap=moving(4000,4800);swap.step(.01)
    assert heavy.v>0 and swap.v==pytest.approx(-heavy.v)
    lighter=moving(4600,4000);lighter.step(.01);assert 0<lighter.v<heavy.v
    assert heavy.acceleration==pytest.approx(((4800-4000)*9.81*.5-400)/(4800+4000+160))

def test_identity_door_and_authorization_interlocks():
    c=Funicular();assert not c.release()
    kw=dict(inside=True,feet_supported=True,stable_s=.5,speed_mps=0)
    assert c.add_passenger('a','A',74,**kw);assert not c.add_passenger('a','A',74,**kw)
    with pytest.raises(ValueError):c.add_passenger('a','B',74,**kw)
    c.authorized=True;assert not c.release();c.step(.1);assert c.q==0

def stop_distance(force,dt):
    c=moving(v=3);start=c.q;c.fault_door_contact();assert c.v==3
    c.p=replace(c.p,brake_max_N=force)
    for _ in range(10000):
        c.step(dt)
        if c.locked:break
    assert c.locked and abs(c.v)<1e-10
    assert abs(c.sample()['energy_residual_J'])<1e-5
    return c.q-start

def test_braking_is_finite_dissipative_and_convergent():
    a=stop_distance(11200,1/120);b=stop_distance(8400,1/120)
    expected=3**2*(4800+4000+160)/(2*(11200+400-800*9.81*.5))
    assert a==pytest.approx(expected,abs=1e-8);assert b>a
    assert stop_distance(11200,1/60)==pytest.approx(a,abs=1e-8)

def test_governed_full_trip_stops_by_braking_without_position_clamp():
    c=Funicular();kw=dict(inside=True,feet_supported=True,stable_s=.5,speed_mps=0)
    for i in range(23):c.add_passenger(str(i),'A',74,**kw)
    c.add_passenger('hero','A',76,**kw)
    for i in range(12):c.add_passenger('b'+str(i),'B',75,**kw)
    c.doors_closed=c.authorized=True;assert c.release()
    peak=0
    for _ in range(20000):
        c.step(1/120);peak=max(peak,c.v)
        if c.locked:break
    assert c.locked and c.q==pytest.approx(112,abs=1e-6) and c.v==0
    assert peak<=2.0000001 and c.t>56
    assert abs(c.sample()['energy_residual_J'])<.001
