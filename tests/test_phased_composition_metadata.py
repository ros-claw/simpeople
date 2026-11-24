import copy

import pytest

from simpeople.motion.compose import rebase_phased_metadata


def fixture():
    entry = {'frame_count': 1463, 'sample_rate': 30, 'playback_mode': 'out_and_back',
             'native_phase_ranges': {'ActionStart': [0, 15], 'ActionLoop': [15, 1447],
                                     'ActionEnd': [1447, 1462]},
             'native_loop_duration_s': 1432/30, 'native_task_timeout_s': 60,
             'canonical_entry': {'world_pose': 'unchanged'},
             'offline_boundary_composition': {'proof_file': 'parent-proof'}}
    sequence = {'frame_count': 1463, 'prefix_frames': 251, 'outbound': [250, 691],
                'target_hold': [692, 781], 'return': [781, 1211], 'tail': [1212, 1462]}
    proof = {'source_frames': 1463, 'output_frames': 1623,
             'source_range_inclusive': [75, 1537], 'all_original_poses_preserved_exactly': True}
    return entry, sequence, proof


def test_full_source_and_loop_annotations_shift_together_without_extending_deadlines():
    args = fixture(); before = copy.deepcopy(args)
    entry, sequence = rebase_phased_metadata(*args)
    assert entry['frame_count'] == sequence['frame_count'] == 1623
    assert entry['native_phase_ranges'] == {'ActionStart': [0, 90], 'ActionLoop': [90, 1522],
                                            'ActionEnd': [1522, 1622]}
    assert entry['native_loop_duration_s'] == args[0]['native_loop_duration_s']
    assert entry['native_task_timeout_s'] == 60
    assert entry['nominal_source_duration_s'] == 1622/30
    assert sequence['prefix_frames'] == 326
    assert sequence['outbound'] == [325, 766]
    assert sequence['target_hold'] == [767, 856]
    assert sequence['return'] == [856, 1286]
    assert sequence['tail'] == [1287, 1622]
    assert entry['canonical_entry'] == before[0]['canonical_entry']
    assert entry['offline_boundary_composition'] == before[0]['offline_boundary_composition']
    assert args == before


@pytest.mark.parametrize('section,key,value', [
    (0, 'frame_count', True), (0, 'sample_rate', 29), (0, 'sample_rate', True),
    (0, 'playback_mode', 'loop'), (0, 'native_loop_duration_s', 1462/30),
    (0, 'native_loop_duration_s', float('nan')), (0, 'native_loop_duration_s', True),
    (1, 'frame_count', 1462), (1, 'prefix_frames', True), (1, 'prefix_frames', 1464),
    (1, 'outbound', [-1, 691]), (1, 'target_hold', [781, 692]),
    (1, 'return', [781, 1463]), (1, 'tail', [1212, 1461]),
    (2, 'source_frames', 1462), (2, 'output_frames', True),
    (2, 'all_original_poses_preserved_exactly', False),
    (2, 'source_range_inclusive', [True, 1537]),
    (2, 'source_range_inclusive', [75, 1536]),
    (2, 'source_range_inclusive', [200, 1662]),
])
def test_inconsistent_or_truncated_source_cannot_get_rebased_annotations(section, key, value):
    args = list(fixture()); args[section][key] = value
    with pytest.raises(ValueError):
        rebase_phased_metadata(*args)


def test_existing_native_phase_gaps_are_preserved_not_silently_added_to_the_loop():
    entry, sequence, proof = fixture()
    entry['native_phase_ranges'] = {'ActionStart': [0, 10], 'ActionLoop': [15, 1447],
                                    'ActionEnd': [1452, 1462]}
    result, _ = rebase_phased_metadata(entry, sequence, proof)
    phases = result['native_phase_ranges']
    assert phases['ActionLoop'][0]-phases['ActionStart'][1] == 5
    assert phases['ActionEnd'][0]-phases['ActionLoop'][1] == 5
    assert result['native_loop_duration_s'] == 1432/30
