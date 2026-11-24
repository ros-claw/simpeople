"""Explicit semantic revision of the diagnostic narrow layout; no Kit access."""
import copy


def narrow_release_semantics(original):
    """Keep v1 intact; move its wall-covered queue exit onto the west side."""
    if original.get('t2_narrow_layout', {}).get('revision') != 'floor_spanning_door_v1':
        raise ValueError('expected original floor-spanning diagnostic layout')
    if original.get('queue_2', {}).get('egress_targets', [None])[0] != [0.0, -15, 0]:
        raise ValueError('expected the observed original queue_2 exit')
    result = copy.deepcopy(original)
    result['queue_2']['egress_targets'][0] = [-1.25, -15, 0]
    result['t2_narrow_layout'].update(revision='floor_spanning_door_release_v2',
        semantic_adjustments=[{'interaction': 'queue_2', 'field': 'egress_targets[0]',
            'original_m': [0.0, -15, 0], 'revised_m': [-1.25, -15, 0],
            'reason': 'Original exit lies inside the floor-spanning south wall; keep a reachable west-side exit.'}])
    return result
