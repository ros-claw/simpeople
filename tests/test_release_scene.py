import copy

import pytest

from simpeople.core.release_scene import narrow_release_semantics


def fixture():
    return {'t2_narrow_layout': {'revision': 'floor_spanning_door_v1',
                                'wall_boxes': [{'position': [0, -16.4, 1], 'size': [.3, 11.2, 2]}]},
            'queue_2': {'egress_targets': [[0., -15, 0], [-5., -15, 0]], 'slots_m': [[-2.5, -15, 0]]}}


def test_only_observed_bad_exit_and_explicit_scene_metadata_change():
    original=fixture();before=copy.deepcopy(original);result=narrow_release_semantics(original)
    assert original==before
    assert result['queue_2']['egress_targets']==[[-1.25,-15,0],[-5,-15,0]]
    assert result['queue_2']['slots_m']==before['queue_2']['slots_m']
    assert result['t2_narrow_layout']['wall_boxes']==before['t2_narrow_layout']['wall_boxes']
    assert result['t2_narrow_layout']['revision']=='floor_spanning_door_release_v2'
    assert result['t2_narrow_layout']['semantic_adjustments'][0]['original_m']==[0,-15,0]


def test_an_unrecognized_scene_or_already_changed_exit_cannot_silently_inherit_repair():
    original=fixture();original['queue_2']['egress_targets'][0]=[2,-15,0]
    with pytest.raises(ValueError,match='observed original'):narrow_release_semantics(original)
    original=fixture();original['t2_narrow_layout']['revision']='other'
    with pytest.raises(ValueError,match='original floor-spanning'):narrow_release_semantics(original)
