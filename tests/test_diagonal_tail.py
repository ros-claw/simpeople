"""Geometric diagonal-tail counterexamples; not native animation acceptance."""
import itertools
import json
import math

import pytest

from simpeople.core.runtime_policy import load_policy
from simpeople.core.tail_release import StraightTail, conservative_swept_cells
from simpeople.core.traffic import ReservationGrid


@pytest.mark.parametrize('end', [[12, 3, 0], [-12, 3, 0], [12, -3, 0], [-12, -3, 0], [9, 9, 0]])
def test_entire_released_cell_stays_behind_original_two_metre_trailing_plane(end):
    grid = ReservationGrid(set(), {}, 1.25)
    start = [0, 0, 0]
    cells = grid.sweep(start, end)
    assert StraightTail(grid, [start, end], cells, 0, 1.2).disabled == 'grid_lane_change'
    tail = StraightTail(grid, [start, end], cells, 0, 1.2, allow_diagonal=True)
    assert tail.disabled is None
    length = math.dist(start, end)
    released = set()
    for frame in range(1, int(length / 1.2 * 30)):
        now = frame / 30
        position = [v * (1.2 * now / length) for v in end]
        result = tail.observe(position, now)
        assert not result.get('brake') and not result.get('disabled')
        for cell in result['remove']:
            center = grid.point(cell)
            for dx, dy in itertools.product([-.625, .625], repeat=2):
                assert tail.project([center[0] + dx, center[1] + dy, 0])[0] < result['progress_m'] - 2 - .05
        assert not result['remove'] & grid.footprint(position)
        assert not result['remove'] & grid.footprint(end)
        tail.commit(result['remove'])
        released.update(result['remove'])
    assert released


def test_corners_and_reversals_still_refuse_diagonal_reclamation():
    grid = ReservationGrid(set(), {}, 1.25)
    for points in [[[0, 0, 0], [4, 4, 0], [8, 3, 0]],
                   [[0, 0, 0], [8, 8, 0], [6, 6, 0]]]:
        cells = set().union(*(grid.sweep(a, b) for a, b in zip(points, points[1:])))
        assert StraightTail(grid, points, cells, 0, 1.2, allow_diagonal=True).disabled == 'nonstraight_or_reversing'


def test_after_real_reclamation_lateral_escape_still_requires_a_brake():
    grid = ReservationGrid(set(), {}, 1.25)
    points = [[0, 0, 0], [12, 3, 0]]
    tail = StraightTail(grid, points, grid.sweep(*points), 0, 1.2, allow_diagonal=True)
    direction = tail.direction
    for frame in range(1, 151):
        position = [direction[0] * 1.2 * frame / 30, direction[1] * 1.2 * frame / 30, 0]
        result = tail.observe(position, frame / 30)
        tail.commit(result['remove'])
    assert tail.released
    bad = [position[0] - direction[1] * .5, position[1] + direction[0] * .5, 0]
    assert tail.observe(bad, 151 / 30)['brake'] == 'off_path'


def test_diagonal_mode_is_explicit_and_cannot_enable_itself_without_tail_release(tmp_path):
    assert load_policy()['diagonal_tail_release_enabled'] is False
    path = tmp_path / 'runtime_policy.json'
    path.write_text(json.dumps({'diagonal_tail_release_enabled': True}))
    with pytest.raises(ValueError, match='requires tail release'):
        load_policy(tmp_path)
    path.write_text(json.dumps({'diagonal_tail_release_enabled': True, 'tail_release_enabled': True}))
    assert load_policy(tmp_path)['diagonal_tail_release_enabled']


def test_recorded_diagonal_graze_requires_an_additional_cell_before_any_release():
    grid = ReservationGrid(set(), {}, 1.25)
    points = [[3.7578768730163574, -16.25226593017578, 0],
              [15.64140286443632, -14.58439003312952, 0]]
    sampled = grid.sweep(*points)
    exact = conservative_swept_cells(grid, points)
    assert exact - sampled == {(10, -13)} and sampled <= exact
    tail = StraightTail(grid, points, sampled, 0, 1.2, allow_diagonal=True)
    assert tail.disabled == 'incomplete_swept_claim' and not tail.observe(points[0], 1/30)['remove']
    assert StraightTail(grid, points, exact, 0, 1.2, allow_diagonal=True).disabled is None


def test_additional_coverage_is_reserved_atomically_and_cannot_steal_a_foreign_claim():
    grid = ReservationGrid(set(), {}, 1.25)
    points = [[3.7578768730163574, -16.25226593017578, 0],
              [15.64140286443632, -14.58439003312952, 0]]
    exact = conservative_swept_cells(grid, points)
    grid.claims['other'] = {(10, -13)}
    assert not grid.reserve_polyline('actor', points, {}, extra_cells=exact)
    assert grid.claims == {'other': {(10, -13)}}
    grid.release('other')
    assert grid.reserve_polyline('actor', points, {}, extra_cells=exact)
    assert grid.claims['actor'] == exact


def test_conservative_line_cover_contains_dense_footprints_for_subcell_origins():
    grid = ReservationGrid(set(), {}, 1.25)
    for start, end in [([.134, -.29, 0], [11.13, 2.18, 0]),
                       ([-4.2, .62, 0], [5.4, -8.01, 0]),
                       ([3.757876873, -16.25226593, 0], [15.641402864, -14.584390033, 0])]:
        exact = conservative_swept_cells(grid, [start, end])
        for sample in range(10001):
            point = [start[i] + (end[i] - start[i]) * sample / 10000 for i in range(3)]
            assert grid.footprint(point) <= exact


def test_forward_spike_freezes_only_without_new_releases_and_still_monitors_retreat():
    grid = ReservationGrid(set(), {}, 1.25)
    points = [[0, 0, 0], [12, 3, 0]]
    tail = StraightTail(grid, points, conservative_swept_cells(grid, points), 0, 1.2, allow_diagonal=True)
    ux, uy = tail.direction
    for frame in range(1, 151):
        p = [ux * frame * .04, uy * frame * .04, 0]
        result = tail.observe(p, frame/30)
        tail.commit(result['remove'])
    before = tail.released.copy()
    # Forward sample jump, with modest lateral error inside the unchanged .35m
    # path bound. No new claim can be removed from this or subsequent samples.
    spike = [ux * 6.14 - uy * .07, uy * 6.14 + ux * .07, 0]
    result = tail.observe(spike, 151/30)
    assert result['frozen'] == 'forward_sample_spike' and not result['remove']
    assert tail.released == before
    assert tail.observe([ux * 6.18, uy * 6.18, 0], 152/30)['frozen']
    assert tail.observe([ux * 5.88, uy * 5.88, 0], 155/30)['brake'] == 'regression'
