import pytest
from simpeople.core.action_space import action_cells
from simpeople.core.traffic import ReservationGrid
from simpeople.core.protocol import activity
from simpeople.core.errors import SimPeopleError


def test_dance_area_prevents_other_routes_until_released():
    grid=ReservationGrid({(x,y) for x in range(-10,11) for y in range(-10,11)}, {})
    grid.claims['dancer']=action_cells(grid,[0,0,0],2.5)
    assert not grid.reserve_polyline('walker',[[-5,0,0],[5,0,0]],{'dancer':[0,0,0]})
    assert grid.reserve_polyline('walker',[[-5,6,0],[5,6,0]],{'dancer':[0,0,0]})
    grid.release('dancer')
    assert grid.reserve_polyline('walker',[[-5,0,0],[5,0,0]],{})


@pytest.mark.parametrize('name',[[0,0,0],'../dance','dance; code','',None])
def test_custom_action_is_a_registered_name_not_code_or_coordinate(name):
    with pytest.raises(SimPeopleError):activity({'actor_id':'a','steps':[{'action':'custom_action','target':name,'duration_s':3}]})
