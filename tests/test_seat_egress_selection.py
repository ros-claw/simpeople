"""Offline exit-choice counterexamples, not native route acceptance."""
import copy
import json

import pytest

from simpeople.core.runtime_policy import load_policy
from simpeople.core.seat_egress import select_exit
from simpeople.core.traffic import ReservationGrid


def test_claim_blocked_primary_can_choose_clear_registered_alternative_without_reserving():
    grid = ReservationGrid({(x, y) for x in range(-5, 6) for y in range(-5, 6)}, {}, 1.25)
    origin, right, left = [0, 0, 0], [2.5, 0, 0], [-2.5, 0, 0]
    grid.claims['other'] = grid.footprint(right)
    claims = copy.deepcopy(grid.claims)
    points = {'right': right, 'left': left}
    result = select_exit(['right', 'left'], 'right', origin, points.__getitem__,
                         lambda a, b: [a, b], lambda a, b: grid.can_reserve('actor', grid.sweep(a, b), {}, a, b))
    assert result['changed'] and result['chosen_target'] == 'left'
    assert grid.claims == claims and not result['fallback_to_legacy']
    assert result['candidates'][0]['reason'] == 'current_body_or_claim_conflict'


def test_clear_primary_preserves_existing_order_even_when_an_alternative_is_shorter():
    points = {'primary': [3, 0, 0], 'shorter': [-1, 0, 0]}
    result = select_exit(list(points), 'primary', [0, 0, 0], points.__getitem__, lambda a, b: [a, b], lambda a, b: True)
    assert result['chosen_target'] == 'primary' and not result['changed']


def test_projected_or_blocked_paths_cannot_establish_an_escape_and_all_blocked_keeps_waiting():
    points = {'primary': [2, 0, 0], 'projected': [-2, 0, 0], 'absent': [0, 2, 0]}
    def query(a, b):
        return [[.03, 0, 0], b] if b == points['projected'] else None if b == points['absent'] else [a, b]
    result = select_exit(list(points), 'primary', [0, 0, 0], points.__getitem__, query, lambda a, b: False)
    assert result['fallback_to_legacy'] and not result['changed'] and result['chosen_target'] == 'primary'
    assert [r['reason'] for r in result['candidates']] == ['current_body_or_claim_conflict', 'projected_endpoint', 'no_static_path']


def test_every_leg_requires_clearance_and_returned_paths_cannot_mutate_query_inputs():
    origin, corner, goal = [0, 0, 0], [1, 1, 0], [2, 0, 0]
    path = [origin, corner, goal]
    original = copy.deepcopy(path)
    result = select_exit(['exit'], 'exit', origin, lambda _: goal, lambda a, b: path, lambda a, b: b != goal)
    assert not result['candidates'][0]['eligible'] and result['fallback_to_legacy']
    result['candidates'][0]['path_m'][1][0] = 99
    assert path == original


def test_experiment_is_off_by_default_and_requires_a_real_boolean(tmp_path):
    assert load_policy()['seat_egress_selection_enabled'] is False
    (tmp_path / 'runtime_policy.json').write_text(json.dumps({'seat_egress_selection_enabled': True}))
    assert load_policy(tmp_path)['seat_egress_selection_enabled'] is True
    (tmp_path / 'runtime_policy.json').write_text(json.dumps({'seat_egress_selection_enabled': 1}))
    with pytest.raises(ValueError, match='invalid seat egress'):
        load_policy(tmp_path)


def test_nonfinite_native_path_cannot_make_an_exit_eligible():
    result = select_exit(['exit'], 'exit', [0, 0, 0], lambda _: [1, 0, 0],
                         lambda a, b: [[float('nan'), 0, 0], b], lambda a, b: True)
    assert result['fallback_to_legacy'] and not result['changed']
    assert result['candidates'][0]['reason'] == 'invalid_static_path'
    json.dumps(result, allow_nan=False)


def test_observed_shared_origin_claim_cannot_be_evaded_by_changing_exit():
    # Closed basic30 cleanup at301.9s: the current footprint itself intersects
    # another route's future claim. Every sweep includes its origin. Alternate
    # exit selection must NOT pretend this can be escaped through a free goal.
    origin = [7.514947891235352, -14.207293510437012, 0]
    points = {'primary': [8.8, -15.05, 0], 'alternate': [6.2, -15.05, 0]}
    grid = ReservationGrid({(x, y) for x in range(3, 10) for y in range(-15, -8)}, {}, 1.25)
    grid.claims['other'] = {(6, -12), (7, -12)}
    assert grid.footprint(origin) & grid.claims['other'] == {(6, -12)}
    result = select_exit(list(points), 'primary', origin, points.__getitem__, lambda a, b: [a, b],
                         lambda a, b: grid.can_reserve('actor', grid.sweep(a, b), {}, a, b))
    assert result['fallback_to_legacy'] and not result['changed']
    assert all(not row['eligible'] for row in result['candidates'])
