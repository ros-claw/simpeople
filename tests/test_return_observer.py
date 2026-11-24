"""Synthetic gate/counterexamples only; native return remains a separate gate."""
import copy

import pytest

from simpeople.motion.return_observer import ReturnObserver


def sample(tick, raised=False):
    pose = [[0, 0, 0, 0, 0, 0, 1], [0, .2 if raised else 0, 1, 0, 0, 0, 1]]
    task = dict(actor_id='a', actor_instance_id='instance', session_id='s', episode_id='e',
                task_id='clip-task', control_epoch=2, status='running')
    return dict(actor_id='a', actor_instance_id='instance', activity_task_id='clip-task',
                step_index=0, joint_paths=['Root', 'Hand'], source_tick=tick, sim_time=tick/30,
                world_pose=pose, task=task,
                actual_observation=dict(ready=True, action='generated', native_task_id=7,
                    observation_sim_time=tick/30, speed_mps=0, facing_direction=[0, -1, 0]))


def observer():
    entry = sample(0)
    ref = {'world_pose': entry['world_pose'], 'actual_observation': entry['actual_observation']}
    return ReturnObserver(ref, {'world_pose': sample(0, True)['world_pose']}, entry, 'generated')


def test_return_requires_actual_goal_then_full_return_duration_not_source_time():
    gate = observer()
    for i in range(200):
        assert gate.update(sample(i)) is None  # Waiting in entry cannot trigger.
    for i in range(200, 261):
        assert gate.update(sample(i, True)) is None
    for i in range(261, 270):
        assert gate.update(sample(i)) is None
    receipt = gate.update(sample(270))
    assert receipt['goal_end_sim_time']-receipt['goal_start_sim_time'] == pytest.approx(2)
    assert receipt['all_actual_joints'] == 2
    assert receipt['native_task_id'] == 7
    with pytest.raises(ValueError, match='one-shot'):
        gate.update(sample(271))


def test_broken_goal_hold_does_not_accumulate_disjoint_intervals():
    gate = observer()
    for i in range(180):
        assert gate.update(sample(i, i % 60 < 59)) is None
    assert gate.goal_end is None


def test_return_reset_by_world_drift_and_speed_without_normalizing_root():
    gate = observer()
    for i in range(61):
        gate.update(sample(i, True))
    for i in range(61, 70):
        row = sample(i)
        if i == 65:
            row['actual_observation']['speed_mps'] = .2
        assert gate.update(row) is None
    for i in range(70, 80):
        row = sample(i)
        row['world_pose'][0][0] += .025
        assert gate.update(row) is None
    for i in range(80, 89):
        assert gate.update(sample(i)) is None
    assert gate.update(sample(89))


@pytest.mark.parametrize('mutate', [
    lambda r: r.update(source_tick=4),
    lambda r: r['actual_observation'].update(native_task_id=8),
    lambda r: r['task'].update(control_epoch=3),
    lambda r: r['task'].update(status='cancelled'),
    lambda r: r['actual_observation'].update(action='Idle'),
    lambda r: r['actual_observation'].update(observation_sim_time=0),
    lambda r: r['actual_observation'].update(observation_sim_time=float('nan')),
    lambda r: r['actual_observation'].update(speed_mps=True),
    lambda r: r['world_pose'][1].__setitem__(0, float('nan')),
    lambda r: r['task'].update(episode_id='old-episode'),
])
def test_bad_sample_permanently_invalidates_attempt(mutate):
    gate = observer()
    gate.update(sample(0))
    bad = sample(1, True)
    mutate(bad)
    with pytest.raises(ValueError):
        gate.update(bad)
    with pytest.raises(ValueError, match='invalidated'):
        gate.update(sample(2, True))


def test_anchor_and_goal_are_detached_and_cannot_be_identical():
    entry = sample(0)
    ref = {'world_pose': copy.deepcopy(entry['world_pose']), 'actual_observation': entry['actual_observation']}
    with pytest.raises(ValueError, match='indistinguishable'):
        ReturnObserver(ref, ref, entry, 'generated')
    gate = ReturnObserver(ref, {'world_pose': sample(0, True)['world_pose']}, entry, 'generated')
    entry['world_pose'][0][0] = 50
    assert gate.entry[0, 0] == 0
