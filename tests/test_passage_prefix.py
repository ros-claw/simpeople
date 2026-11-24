import math

import pytest

from simpeople.core.passage_prefix import inside, protected_prefix, zone_from_approaches
from simpeople.core.traffic import ReservationGrid


ZONE = zone_from_approaches('door', [-2., -10., 0.], [2., -10., 0.], 1.25)


@pytest.mark.parametrize('sign', [-1, 1])
def test_short_horizon_extends_through_the_door_and_keeps_the_requested_goal(sign):
    points = [[-5.25*sign, -10., 0.], [5.25*sign, -10., 0.]]
    prefix, proof = protected_prefix(points, 4., [ZONE])
    assert prefix[-1] == pytest.approx([2.1*sign, -10., 0.])
    assert proof['extended_for_passages'] == ['door']
    assert proof['actual_horizon_m'] == pytest.approx(7.35)
    assert points[-1] == [5.25*sign, -10., 0.]


def test_route_before_or_beyond_passage_keeps_original_horizon():
    points = [[-12., -10., 0.], [12., -10., 0.]]
    for horizon in [4., 16., 30.]:
        result, proof = protected_prefix(points, horizon, [ZONE])
        assert result[-1] == pytest.approx([min(-12+horizon, 12), -10, 0])
        assert not proof['extended_for_passages']


def test_lateral_exit_keeps_the_actual_corner_instead_of_cutting_through_the_wall():
    points = [[-5., -10., 0.], [0., -10., 0.], [0., -7., 0.], [5., -7., 0.]]
    result, _ = protected_prefix(points, 4., [ZONE])
    assert result == [[-5., -10., 0.], [0., -10., 0.], [0., -8.65, 0.]]
    assert not inside(result[-1], ZONE)


def test_final_goal_inside_passage_is_never_relocated_or_reported_reached():
    with pytest.raises(ValueError, match='final goal'):
        protected_prefix([[-5., -10., 0.], [0., -10., 0.]], 4., [ZONE])


def test_rotated_passage_has_the_same_geometric_result():
    zone = zone_from_approaches('north', [3., -2., 0.], [3., 2., 0.], 1.25)
    result, proof = protected_prefix([[3., -5.25, 0.], [3., 5.25, 0.]], 4., [zone])
    assert result[-1] == pytest.approx([3., 2.1, 0.])
    assert proof['extended_for_passages'] == ['north']


def test_exit_does_not_grant_permission_to_cross_a_body_or_existing_claim():
    points, _ = protected_prefix([[-5.25, -10., 0.], [5.25, -10., 0.]], 4., [ZONE])
    grid = ReservationGrid(set(), {})
    assert not grid.reserve_polyline('west', points, {'east': [1.25, -10., 0.]})
    assert not grid.claims
    grid.claims['east'] = grid.footprint([0., -10., 0.])
    before = dict(grid.claims)
    assert not grid.reserve_polyline('west', points, {})
    assert grid.claims == before


@pytest.mark.parametrize('bad', [0, -1, math.nan, math.inf, True])
def test_invalid_horizon_fails_closed(bad):
    with pytest.raises(ValueError):
        protected_prefix([[-5., -10., 0.], [5., -10., 0.]], bad, [ZONE])


def test_multiple_overlapping_passages_leave_both_and_preserve_every_turn():
    second = zone_from_approaches('second', [1., -10., 0.], [5., -10., 0.], 1.25)
    result, proof = protected_prefix([[-5.25, -10., 0.], [8., -10., 0.]], 4., [ZONE, second])
    assert result[-1] == pytest.approx([5.1, -10., 0.])
    assert proof['extended_for_passages'] == ['door', 'second']
