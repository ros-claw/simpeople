"""Counterexamples to unsafe drain permissions; no native execution claim."""
import copy

import pytest

from simpeople.core.drainage_candidate import check_candidate
from simpeople.core.traffic import FairGate, ReservationGrid


def fixture():
    grid = ReservationGrid({(x, y) for x in range(-5, 6) for y in range(-5, 6)}, {})
    gate = FairGate()
    protected = {(0, 0), (1, 0), (2, 0)}
    gate.request('older', 'a', protected, 0, drainers=['body-b'], occupant_token='body-a')
    gate.request('mine', 'b', protected, 1, occupant_token='body-b')
    positions = {'a': [-3, 0, 0], 'b': [0, 0, 0], 'other': [4, 4, 0]}
    return grid, gate.pending, 'mine', 'body-b', [[0, 0, 0], [0, 2.5, 0]], positions, 2


def test_existing_generation_can_propose_leaving_while_every_age_and_claim_stays_unchanged():
    args = fixture(); before = copy.deepcopy((args[0].claims, args[1], args[5]))
    result = check_candidate(*args)
    assert result['eligible'] and result['reason'] == 'geometric_candidate_only'
    assert result['waiting_age_s'] == 1
    assert result['drained_older_fences'][0]['route_id'] == 'older'
    assert (args[0].claims, args[1], args[5]) == before


@pytest.mark.parametrize('mutation,reason', [
    (lambda a: a.__setitem__(3, 'recreated-body-b'), 'not_current_waiting_body_generation'),
    (lambda a: a[1]['older'].update(drainers={'former-body-b'}), 'not_preexisting_occupant_leaving_every_older_fence'),
    (lambda a: a[1]['older'].update(drainers={'mine'}), 'not_preexisting_occupant_leaving_every_older_fence'),
    (lambda a: a.__setitem__(4, [[.1, 0, 0], [0, 2.5, 0]]), 'path_does_not_start_at_actual_body'),
    (lambda a: a.__setitem__(4, [[0, 0, 0], [1.25, 0, 0]]), 'not_preexisting_occupant_leaving_every_older_fence'),
    (lambda a: a.__setitem__(4, [[0, 0, 0], [0, 3.1, 0]]), 'not_bounded_local_drainage'),
    (lambda a: a.__setitem__(4, [[0, 0, 0], [0, 1, .1], [0, 2.5, 0]]), 'not_bounded_local_drainage'),
    (lambda a: a.__setitem__(4, [[0, 0, 0], [0, float('nan'), 0]]), 'invalid_actual_origin_path_or_clock'),
    (lambda a: a[0].claims.update({'other': {(0, 1)}}), 'foreign_exclusive_claim'),
    (lambda a: a[0].claims.update({'b': {(0, 0)}}), 'existing_owned_claim_requires_settlement'),
    (lambda a: a[5].update(other=[0, 1, 0]), 'actual_body_clearance'),
    (lambda a: a[1]['mine'].update(state='active'), 'not_current_waiting_body_generation'),
    (lambda a: a[1]['mine'].update(since=3), 'invalid_wait_age'),
    (lambda a: a[1]['older'].update(since=float('nan')), 'invalid_older_priority'),
    (lambda a: a[1]['older'].update(sequence=True), 'invalid_older_priority'),
    (lambda a: a[5].update(other=[float('nan'), 1, 0]), 'invalid_actual_body_positions'),
    (lambda a: a[5].update(b=[0, float('nan'), 0]), 'invalid_actual_body_positions'),
])
def test_unsafe_or_unbound_candidate_rejected_without_mutation(mutation, reason):
    args = list(fixture()); mutation(args); before = copy.deepcopy((args[0].claims, args[1], args[5]))
    result = check_candidate(*args)
    assert not result['eligible'] and result['reason'] == reason
    assert (args[0].claims, args[1], args[5]) == before


def test_must_leave_every_older_fence_not_only_the_reported_cycle_neighbor():
    args = list(fixture()); second = copy.deepcopy(args[1]['older'])
    second.update(key='second-older', since=.1, sequence=3, cells={(0, 2)})
    args[1]['second-older'] = second
    assert not check_candidate(*args)['eligible']


def test_target_inside_a_coarse_old_goal_cell_is_not_silently_declared_disjoint():
    args = list(fixture()); args[4] = [[0, 0, 0], [0, .6, 0]]
    assert not check_candidate(*args)['eligible']
