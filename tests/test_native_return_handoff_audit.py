"""Synthetic independent-auditor counterexamples, never native proof."""
import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from audit_native_return_handoff import readback


def fixture():
    def row(tick, hand, idle=False):
        task = dict(actor_id='a', actor_instance_id='i', session_id='s', episode_id='e',
                    control_epoch=2, task_id='clip', status='failed' if idle else 'running')
        return dict(actor_id='a', actor_instance_id='i', activity_task_id='clip', step_index=0,
            joint_paths=['Root', 'Hand'], source_tick=tick, sim_time=tick/30,
            phase='canonical_explicit_idle' if idle else 'canonical_left_low', task=task,
            world_pose=[[0, 0, 0, 0, 0, 0, 1], [0, hand, 1, 0, 0, 0, 1]],
            actual_observation=dict(ready=True, action='Idle' if idle else 'canonical_operator__left_low',
                native_task_id=8 if idle else 7, facing_direction=[0, -1, 0], observation_sim_time=tick/30, speed_mps=0))
    anchor = row(0, 0); anchor['actual_observation'].update(action='Idle', native_task_id=6)
    rows = [anchor]
    for tick in range(1, 136):
        hand = .2*tick/30 if tick < 30 else .2 if tick <= 94 else .2*(124-tick)/30 if tick < 124 else 0
        rows.append(row(tick, hand))
    rows.extend(row(i, 0, True) for i in range(136, 211))
    reference = dict(entry=anchor, goal={'world_pose': row(0, .2)['world_pose']})
    receipt = dict(proof={'clip': 'canonical_operator__left_low', 'native_task_id': 7,
                         'task': copy.deepcopy(rows[1]['task']), 'pose_stream_source_tick': 135, 'ready_sim_time': 4.5},
                   idle_native_task_id=8, before=copy.deepcopy(rows[135]))
    return rows, anchor, reference, receipt


def test_measured_fixed_world_goal_return_and_75_native_idle_samples():
    result = readback(*fixture())
    assert result['readback_passed'] and not result['errors']
    assert result['active_samples'] == 135 and result['explicit_idle_samples'] == 75
    assert result['max_entry_clip_idle_position_step_m'] < .007


@pytest.mark.parametrize('mutation', [
    lambda a: a[0][136]['world_pose'][1].__setitem__(0, .5),
    lambda a: a[0][136]['world_pose'][0].__setitem__(slice(3, 7), [0, 0, 1, 0]),
    lambda a: a[0][136]['world_pose'][0].__setitem__(slice(3, 7), [1, 0, 0, 0]),
    lambda a: a[0][136]['actual_observation'].update(native_task_id=0),
    lambda a: a[0][136]['task'].update(status='succeeded'),
    lambda a: a[0][136]['task'].update(control_epoch=3),
    lambda a: a[0][136].update(source_tick=137),
    lambda a: a[0][136].update(actor_instance_id='recreated'),
    lambda a: a[0][136]['actual_observation'].update(observation_sim_time=0),
    lambda a: a[0][136]['actual_observation'].update(observation_sim_time=float('nan')),
    lambda a: a[3]['proof'].update(ready_sim_time=3),
    lambda a: a[0][128]['actual_observation'].update(speed_mps=.2),
])
def test_return_cannot_hide_seam_wrong_idle_owner_or_false_success(mutation):
    args = copy.deepcopy(fixture()); mutation(args); result = readback(*args)
    assert result['errors'] and not result['readback_passed']


def test_missing_actual_samples_never_passes_by_receipt_alone():
    args = fixture(); args[0].pop()
    with pytest.raises(ValueError, match='readback absent'):
        readback(*args)


def test_command_time_is_not_the_first_native_idle_frame():
    args = list(fixture()); rows = args[0]
    for r in rows[136:138]:
        r['actual_observation'].update(action='canonical_operator__left_low', native_task_id=7)
    result = readback(*args)
    assert not result['readback_passed']  # Only 73 measured Idle samples remain.
    assert result['handoff_pair_pose_stream_ticks'] == [137, 138]
    assert result['SDK_command_to_Idle_latency_s'] == pytest.approx(.1)
    assert result['max_entry_clip_idle_angle_step_deg'] == 0
    assert result['errors'] == ['fewer than 75 actual explicit Idle samples after SDK command latency']
