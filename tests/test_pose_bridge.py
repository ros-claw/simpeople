import copy
import numpy as np
import pytest
from simpeople.core.errors import SimPeopleError
from simpeople.motion.contracts import digest
from simpeople.motion.pose_bridge import ExecutedPoseHistory, PoseBridge


FENCE = {'session_id': 's', 'episode_id': 'e', 'actor_id': 'a', 'actor_instance_id': 'i', 'control_epoch': 1, 'task_id': 't'}
NAMES = ['Hips'] + ['joint_' + str(i) for i in range(1, 30)]
REFERENCE = [[0, 0, 1 if i == 0 else .02, 0, 0, 0, 1] for i in range(30)]
RIG = {'rig_sha256': 'c' * 64, 'joint_names': NAMES, 'parents': [-1] + [0] * 29,
       'reference_local': REFERENCE, 'model_joint_names': NAMES, 'model_indices': list(range(30)),
       'extra_joint_policy': 'reference'}
PROFILE = {'source_asset_sha256': 'a' * 64, 'joint_paths_sha256': digest(NAMES),
           'rig_sha256': RIG['rig_sha256'], 'mapping_revision': 'test-calibration'}


def sample(index, **task_changes):
    task = {**FENCE, 'status': 'running', **task_changes}
    return {'sample_source': 'behavior_sdk', 'actor_id': task['actor_id'], 'actor_instance_id': task['actor_instance_id'],
            'task': task, 'source_asset_sha256': 'a' * 64, 'source_tick': index, 'sim_time': index / 30,
            'joint_paths': copy.deepcopy(NAMES), 'world_pose': copy.deepcopy(REFERENCE), 'actual_observation': {'ready': True}}


def filled():
    h = ExecutedPoseHistory()
    for i in range(4):
        h.record(sample(i))
    return h


@pytest.mark.parametrize('field,value', [('session_id', 'new'), ('episode_id', 'new'), ('actor_instance_id', 'new'), ('control_epoch', 2), ('task_id', 'new')])
def test_new_execution_identity_cannot_reuse_three_old_frames(field, value):
    h = filled()
    h.record(sample(4, **{field: value}))
    with pytest.raises(SimPeopleError, match='four consecutive'):
        h.window({**FENCE, field: value}, 4 / 30)
    for i in range(5, 8):
        h.record(sample(i, **{field: value}))
    rows = h.window({**FENCE, field: value}, 7 / 30)
    assert [r['source_tick'] for r in rows] == [4, 5, 6, 7]


def test_pause_gap_clears_history_instead_of_inventing_intermediate_samples():
    h = filled()
    h.record(sample(9))
    with pytest.raises(SimPeopleError, match='four consecutive'):
        h.window(FENCE, .3)


def test_duplicate_tick_and_broken_readback_invalidate_the_old_window():
    h = filled()
    with pytest.raises(SimPeopleError, match='duplicate'):
        h.record(sample(3))
    with pytest.raises(SimPeopleError, match='four consecutive'):
        h.window(FENCE, .1)
    h = filled()
    bad = sample(4)
    bad['world_pose'][1][2] = float('nan')
    with pytest.raises(SimPeopleError):
        h.record(bad)
    with pytest.raises(SimPeopleError, match='four consecutive'):
        h.window(FENCE, 4 / 30)


def test_actual_observation_cannot_be_replaced_with_predicted_pose():
    h = filled()
    bad = sample(4)
    bad['sample_source'] = 'predicted'
    with pytest.raises(SimPeopleError, match='actual Behavior'):
        h.record(bad)


def test_window_rejects_stale_future_and_other_task_requests():
    h = filled()
    for now in [.2, .05]:
        with pytest.raises(SimPeopleError, match='stale or in the future'):
            h.window(FENCE, now)
    with pytest.raises(SimPeopleError, match='another execution'):
        h.window({**FENCE, 'task_id': 'other'}, .1)
    rows = h.window(FENCE, .1)
    rows[0]['world_pose'][0][0] = 99
    assert h.window(FENCE, .1)[0]['world_pose'][0][0] == 0


def test_asset_revision_change_needs_four_new_observations():
    h = filled()
    changed = sample(4)
    changed['source_asset_sha256'] = 'b' * 64
    h.record(changed)
    with pytest.raises(SimPeopleError, match='four consecutive'):
        h.window(FENCE, 4 / 30)


def test_same_asset_with_changed_active_bind_data_needs_new_samples_and_profile():
    h=filled();row=sample(4);row['active_skeleton_sha256']='f'*64;h.record(row)
    with pytest.raises(SimPeopleError,match='four consecutive'):h.window(FENCE,4/30)
    for i in range(5,8):
        row=sample(i);row['active_skeleton_sha256']='f'*64;h.record(row)
    converter=Converter();bridge=PoseBridge(RIG,converter)
    with pytest.raises(SimPeopleError,match='actual skeleton'):bridge.to_model_context(h,PROFILE,FENCE,7/30)
    assert converter.calls==0
    result=bridge.to_model_context(h,{**PROFILE,'active_skeleton_sha256':'f'*64},FENCE,7/30)
    assert result['active_skeleton_sha256']=='f'*64


def test_step_transition_inside_same_activity_cannot_include_previous_native_task():
    h=filled();row=sample(4);row['sample_native_task_id']=22;row['step_index']=1;h.record(row)
    with pytest.raises(SimPeopleError,match='four consecutive'):h.window(FENCE,4/30)


def test_calibrated_profile_cannot_upgrade_unversioned_samples():
    converter=Converter()
    with pytest.raises(SimPeopleError,match='actual skeleton'):
        PoseBridge(RIG,converter).to_model_context(filled(),{**PROFILE,'active_skeleton_sha256':'f'*64},FENCE,.1)
    assert converter.calls==0


class Converter:
    def __init__(self):
        self.calls = 0

    def convert_world_history(self, rows, profile):
        self.calls += 1
        return np.repeat(np.array(REFERENCE)[None], 4, axis=0), {'scope': 'test conversion'}


def test_bridge_fences_full_context_and_checks_profile_before_conversion():
    c = Converter()
    bridge = PoseBridge(RIG, c)
    for field in ['source_asset_sha256', 'joint_paths_sha256', 'rig_sha256']:
        with pytest.raises(SimPeopleError):
            bridge.to_model_context(filled(), {**PROFILE, field: 'wrong'}, FENCE, .1)
    assert c.calls == 0
    result = bridge.to_model_context(filled(), PROFILE, FENCE, .1)
    assert c.calls == 1
    assert result['binding']['context_revision'] == digest(result['context'])
    assert result['source_ticks'] == [0, 1, 2, 3]
    assert result['context']['source'] == 'executed_history'
    assert result['online_application_verified'] is False
