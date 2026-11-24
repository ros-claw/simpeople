import math
import random

import pytest

from simpeople.core.body_buckets import BodyBuckets
from simpeople.core.traffic import BODY_CLEARANCE_M, ClearanceEdges, ReservationGrid


def test_seeded_edge_clearance_matches_full_body_scan_without_changing_inputs():
    rng = random.Random(1115); grid = ReservationGrid(set(), {})
    positions = {str(i): [rng.uniform(-22, 22), rng.uniform(-22, 22), 0] for i in range(50)}
    index = BodyBuckets(positions, BODY_CLEARANCE_M); pairs = 0; selected = 0
    for _ in range(3000):
        a = [rng.uniform(-22, 22), rng.uniform(-22, 22), 0]
        b = [a[0]+rng.uniform(-1.25, 1.25), a[1]+rng.uniform(-1.25, 1.25), 0]
        nearby = index.candidates(a, b); selected += len(nearby); pairs += len(positions)
        assert grid.clearance('0', a, b, nearby) == grid.clearance('0', a, b, positions)
    assert selected < pairs/10
    assert not grid.claims


@pytest.mark.parametrize('offset', [.9, .9-1e-12, .9+1e-12, -.9, -.9+1e-12, -.9-1e-12])
def test_boundary_rounding_is_conservative(offset):
    grid = ReservationGrid(set(), {}); positions = {'other': [2, offset, 0]}
    index = BodyBuckets(positions, BODY_CLEARANCE_M)
    assert grid.clearance('a', [0, 0, 0], [4, 0, 0], index.candidates([0, 0, 0], [4, 0, 0])) == grid.clearance('a', [0, 0, 0], [4, 0, 0], positions)


@pytest.mark.parametrize('end', [[-1.25, 0, 0], [1.25, 0, 0], [0, 1.25, 0], [.1, 0, 0]])
def test_close_initial_body_exception_still_uses_the_original_predicate(end):
    grid = ReservationGrid(set(), {}); positions = {'other': [.2, 0, 0]}
    index = BodyBuckets(positions, BODY_CLEARANCE_M)
    assert grid.clearance('a', [0, 0, 0], end, index.candidates([0, 0, 0], end)) == grid.clearance('a', [0, 0, 0], end, positions)


def test_long_and_large_coordinate_queries_fall_back_to_a_bounded_full_scan():
    positions = {'a': [0, 0, 0], 'b': [1e16, 0, 0]}; index = BodyBuckets(positions, .9)
    assert len(index.candidates([-1e20, 0, 0], [1e20, 1e20, 0])) == 2


def test_nonfinite_data_is_not_silently_dropped_by_the_index():
    positions = {'a': [math.nan, 0, 0], 'b': [10, 0, 0]}; index = BodyBuckets(positions, .9)
    assert index.buckets is None and set(index.candidates([0, 0, 0], [1, 0, 0])) == {'a', 'b'}
    valid = BodyBuckets({'a': [0, 0, 0]}, .9)
    assert set(valid.candidates([math.inf, 0, 0], [1, 0, 0])) == {'a'}


def test_empty_and_negative_bucket_coordinates():
    assert BodyBuckets({}, .9).candidates([0, 0, 0], [1, 0, 0]) == {}
    index = BodyBuckets({'a': [-2.01, -2.01, 0]}, .9)
    assert set(index.candidates([-2.1, -2, 0], [-1, -2, 0])) == {'a'}


def test_index_and_edge_cache_are_per_search_snapshots():
    points = {'b': [1, 0, 0]}; first = BodyBuckets(points, .9)
    points['b'][0] = 20
    assert first.candidates([0, 0, 0], [2, 0, 0])['b'][0] == 1
    assert not BodyBuckets(points, .9).candidates([0, 0, 0], [2, 0, 0])
    grid = ReservationGrid({(0, 0), (1, 0)}, {(0, 0): [(1, 0)]})
    assert ClearanceEdges(grid, 'a', points).get((0, 0)) == [(1, 0)]
    grid.claims['held'] = {(1, 0)}
    assert ClearanceEdges(grid, 'a', points).get((0, 0)) == []
