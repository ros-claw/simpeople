import copy
import json

import pytest

from simpeople.core.fair_edges import FairEdges
from simpeople.core.runtime_policy import load_policy
from simpeople.core.traffic import ClearanceEdges, FairGate, ReservationGrid


def grid():
    nodes = {(x, y) for x in range(5) for y in range(-2, 3)}
    return ReservationGrid(nodes, {n: sorted(m for m in nodes if abs(n[0]-m[0])+abs(n[1]-m[1]) == 1) for n in nodes})


def test_search_finds_a_detour_around_a_physically_free_but_older_fence():
    g = grid(); gate = FairGate()
    gate.request('old', 'waiter', {(2, 0)}, 0)
    gate.request('new', 'actor', {(0, 0)}, 1, occupant_token='actor-body', origin_cells={(0, 0)})
    before = copy.deepcopy(gate.pending)
    direct = g.path((0, 0), (4, 0), set())
    assert (2, 0) in direct
    edges = FairEdges(g, ClearanceEdges(g, 'actor', {}), gate, 'new', {(4, 0)})
    path = g.path((0, 0), (4, 0), set(), edges=edges)
    assert path and (2, 0) not in path
    assert all(gate.allowed('new', g.sweep(g.point(a), g.point(b)), {(4, 0)}) for a, b in zip(path, path[1:]))
    assert gate.pending == before and not g.claims


def test_a_fence_cannot_be_bypassed_if_there_is_no_alternative():
    g = grid(); gate = FairGate()
    gate.request('old', 'waiter', {(2, y) for y in range(-2, 3)}, 0)
    gate.request('new', 'actor', {(0, 0)}, 1, occupant_token='actor-body', origin_cells={(0, 0)})
    edges = FairEdges(g, g.edges, gate, 'new', {(4, 0)})
    assert g.path((0, 0), (4, 0), set(), edges=edges) is None
    assert gate.pending['old']['since'] == 0 and not g.claims


def test_preexisting_escape_is_only_a_search_hypothesis_not_permission_to_start():
    g = grid(); gate = FairGate()
    gate.request('old', 'waiter', {(0, 0), (1, 0)}, 0, drainers={'body'})
    gate.request('escape', 'actor', {(0, 0)}, 1, occupant_token='body', origin_cells={(0, 0)})
    edges = FairEdges(g, g.edges, gate, 'escape', {(4, 0)})
    assert edges.allows(g.point((0, 0)), g.point((1, 0)))
    # A first inside leg still fails ordinary admission without a separately
    # verified complete escape. The search does not change this requirement.
    cells = g.sweep(g.point((0, 0)), g.point((1, 0)))
    assert not gate.allowed('escape', cells, {(1, 0)})
    assert gate.allowed('escape', cells, {(4, 0)})
    assert not g.claims


def test_recreated_body_cannot_inherit_an_escape_or_old_fence_priority():
    g = grid(); gate = FairGate()
    gate.request('old', 'waiter', {(0, 0)}, 0, drainers={'body-v1'})
    gate.request('new', 'actor', {(0, 0)}, 1, occupant_token='body-v2', origin_cells={(0, 0)})
    assert not FairEdges(g, g.edges, gate, 'new', {(4, 0)}).allows(g.point((0, 0)), g.point((1, 0)))


def test_missing_route_is_fail_closed_and_cache_is_per_search():
    g = grid(); gate = FairGate()
    assert FairEdges(g, g.edges, gate, 'missing', {(4, 0)}).get((0, 0)) == []
    gate.request('old', 'other', {(1, 0)}, 0); gate.request('new', 'actor', {(0, 0)}, 1)
    assert (1, 0) not in FairEdges(g, g.edges, gate, 'new', {(4, 0)}).get((0, 0))
    gate.cancel('old')
    assert (1, 0) in FairEdges(g, g.edges, gate, 'new', {(4, 0)}).get((0, 0))


def test_physical_bodies_and_exclusive_claims_still_block_the_wrapped_search():
    g = grid(); gate = FairGate(); gate.request('new', 'actor', {(0, 0)}, 1)
    g.claims['owner'] = {(1, 0)}
    edges = FairEdges(g, ClearanceEdges(g, 'actor', {'body': [0, .7, 0]}), gate, 'new', {(4, 0)})
    assert edges.get((0, 0)) == [(0, -1)]  # Original close-body escape away is retained.
    assert g.claims == {'owner': {(1, 0)}}


def test_new_path_option_defaults_off_and_keeps_original_budgets(tmp_path):
    defaults = load_policy()
    assert defaults['fair_path_edges_enabled'] is False
    (tmp_path/'runtime_policy.json').write_text(json.dumps({'fair_path_edges_enabled': True}))
    value = load_policy(tmp_path)
    assert value['fair_path_edges_enabled'] is True
    assert all(value[k] == defaults[k] for k in defaults if k != 'fair_path_edges_enabled')


@pytest.mark.parametrize('bad', [0, 1, 'true', None])
def test_new_path_option_requires_a_boolean(tmp_path, bad):
    (tmp_path/'runtime_policy.json').write_text(json.dumps({'fair_path_edges_enabled': bad}))
    with pytest.raises(ValueError): load_policy(tmp_path)
