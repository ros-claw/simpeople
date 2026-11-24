import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from runtime_fixture_points import fixture_points, path_quality


def test_interaction_nav_points_include_both_exits_and_every_queue_slot():
    semantics = {'chair': {'approach': 'approach', 'egress_targets': ['exit_a', 'exit_b']},
                 'approach': {'position_m': [1, 2, 0]}, 'exit_a': {'position_m': [2, 2, 0]},
                 'exit_b': {'position_m': [0, 2, 0]},
                 'queue': {'slots_m': [[4, 0, 0], [4, 1, 0]], 'egress_targets': [[5, 0, 0], [3, 0, 0]]}}
    case = {'actors': [{'actor_id': 'person', 'spawn_anchor': [0, 0, 0]}],
            'requests': [{'request_case_id': 'r', 'steps': [
                {'action': 'sit', 'target': 'chair'}, {'action': 'leave_seat'},
                {'action': 'queue', 'target': 'queue'},
                {'action': 'move_to', 'via': ['exit_b'], 'target': [9, 0, 0]}, {'action': 'wait'}]}]}
    original = copy.deepcopy((case, semantics))
    points = fixture_points(case, semantics)
    assert len(points) == 10 and len({p['use'] for p in points}) == 10
    assert (case, semantics) == original
    assert {p['use'] for p in points if ':seat_exit' in p['use']} == {'r:step0:seat_exit0', 'r:step0:seat_exit1'}
    assert [p['position_m'] for p in points if ':queue_slot' in p['use']] == [[4, 0, 0], [4, 1, 0]]


def test_projected_start_and_missing_paths_cannot_establish_connectivity():
    assert path_quality([0, 0, 0], [1, 0, 0], [[0, 0, 0], [1, 0, 0]])['passed']
    assert not path_quality([0, 0, 0], [1, 0, 0], [[.31, 0, 0], [1, 0, 0]])['passed']
    assert not path_quality([0, 0, 0], [1, 0, 0], [[0, 0, 0], [1.31, 0, 0]])['passed']
    for path in [None, [], [[float('nan'), 0, 0]], [[0, 0]]]:
        assert not path_quality([0, 0, 0], [1, 0, 0], path)['passed']


def test_unknown_actions_and_unresolved_semantics_fail_closed():
    case = {'actors': [], 'requests': [{'request_case_id': 'r', 'steps': [{'action': 'new_action'}]}]}
    with pytest.raises(ValueError, match='unhandled'): fixture_points(case, {})
    case['requests'][0]['steps'] = [{'action': 'move_to', 'target': 'absent'}]
    with pytest.raises(ValueError, match='position_m'): fixture_points(case, {})
