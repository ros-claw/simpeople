import copy
from types import SimpleNamespace

import pytest

from simpeople.backends.native import canonical_recovery_stop as stop


POSE = [[0., 0., 0., 0., 0., 0., 1.], [0., 0., 1., 0., 0., 0., 1.]]


class Backend:
    def __init__(self):
        self.now = 10.; self.current = 35; self.states = {35: 'running', 48: 'running', 49: 'running'}
        self.commands = []; self.events = []; self.pose = copy.deepcopy(POSE)
        self.canonical_recovery_stop_probe_enabled = True
        self.timeline = SimpleNamespace(get_current_time=lambda: self.now)
        self.instances = {'actor': dict(traffic_instance_id='body1', engine_native_ids=[35], asset_id='default')}
        self.assets = [dict(asset_id='default', content_hash='asset1')]
        reference = dict(world_pose=copy.deepcopy(POSE), actual_observation=dict(facing_direction=[0., 1., 0.]))
        self.custom_actions = {'recovery': dict(internal_stop_recovery=True, source_goal_clip='canonical',
            stop_source_asset_sha256='asset1', status='discovered', stop_joint_paths=['Root', 'Root/Pelvis'],
            stop_entry_world_pose=copy.deepcopy(POSE), stop_entry_reference=reference, stop_neutral_reference=reference)}
        self.on_event = lambda kind, **p: self.events.append((kind, p))

    def assert_thread(self): pass
    def get_action_task_id(self): return self.current
    def get_task_name(self, tid): return 'canonical' if tid == 35 else 'recovery'
    def task_state(self, handle, tid): return self.states[tid]
    def observe(self, handle):
        return dict(ready=True, observation_sim_time=self.now, native_task_id=self.current,
                    speed_mps=0., facing_direction=[0., 1., 0.])
    def custom_action(self, name, **kw):
        self.commands.append(('custom', name, kw)); self.current = 48; self.states[35] = 'failed'; return 48
    def idle(self): self.commands.append(('idle', 49)); return 49
    def cancel_task(self, tid): self.commands.append(('cancel', tid)); self.states[tid] = 'failed'
    def request(self):
        return stop.request(self, 'actor', dict(canonical_entry={'pose': 'ref'}, entry_base_action='Idle'),
                            35, 'canonical', self)
    def tick(self, elapsed):
        self.now = 10+elapsed
        return stop.advance(self, 'actor', self.instances['actor']['custom_stop'], self.observe('actor'), self)


@pytest.fixture(autouse=True)
def actual_pose_reader(monkeypatch):
    monkeypatch.setattr(stop, 'capture', lambda b, *_: copy.deepcopy(b.pose))


def test_recovery_replaces_the_owned_sdk_task_without_an_intermediate_idle():
    b = Backend(); assert b.request()
    assert b.commands == [('custom', 'recovery', {'duration': 14.})]
    record = b.instances['actor']['custom_stop']
    assert record['retired_native_task_id'] == 35 and record['recovery_native_task_id'] == 48
    assert record['idle_request_native_task_id'] is None
    assert record['body_generation'] == 'body1' and record['requested_sim_time'] == 10.
    for elapsed in [1/30, 2/30, 3/30]: assert not b.tick(elapsed)
    assert b.commands == [('custom', 'recovery', {'duration': 14.})]
    assert not b.tick(4/30)
    assert b.commands[-2:] == [('cancel', 48), ('idle', 49)]
    assert record['idle_requested_sim_time'] == pytest.approx(10+4/30)
    assert not record['forced_idle_request']
    b.current = 49
    assert b.tick(5/30)


@pytest.mark.parametrize('fault', ['disabled', 'foreign', 'generation', 'asset', 'unmatched', 'wrong_goal'])
def test_no_preloaded_match_never_issues_a_recovery_or_writes_a_stop_record(fault):
    b = Backend()
    if fault == 'disabled': b.canonical_recovery_stop_probe_enabled = False
    if fault == 'foreign': b.instances['actor']['engine_native_ids'] = []
    if fault == 'generation': b.instances['actor']['traffic_instance_id'] = ''
    if fault == 'asset': b.assets[0]['content_hash'] = 'other'
    if fault == 'unmatched': b.pose[1][0] = .03
    if fault == 'wrong_goal': b.custom_actions['recovery']['source_goal_clip'] = 'other'
    assert not b.request()
    assert not b.commands and 'custom_stop' not in b.instances['actor']


@pytest.mark.parametrize('fault', ['foreign', 'generation', 'stale', 'expired', 'old_running'])
def test_settlement_never_overrides_a_new_owner_or_a_stale_body(fault):
    b = Backend(); assert b.request(); record = b.instances['actor']['custom_stop']
    b.now = 24.2; observation = b.observe('actor')
    if fault == 'foreign': b.current = 99; observation['native_task_id'] = 99
    if fault == 'generation': b.instances['actor']['traffic_instance_id'] = 'body2'
    if fault == 'stale': observation['observation_sim_time'] -= 1/30
    if fault == 'expired': b.now = 25.1; observation['observation_sim_time'] = b.now
    if fault == 'old_running': b.states[35] = 'running'
    assert not stop.advance(b, 'actor', record, observation, b)
    assert b.commands == [('custom', 'recovery', {'duration': 14.})]


def test_target_is_anchored_once_and_does_not_follow_later_root_drift():
    b = Backend(); assert b.request(); record = b.instances['actor']['custom_stop']
    original = copy.deepcopy(record['recovery_target_world_pose'])
    for p in b.pose: p[0] += .2
    for tick in range(1, 20): assert not b.tick(tick/30)
    assert record['recovery_target_world_pose'] == original
    assert not record['recovery_neutral_times'] and len(b.commands) == 1


def test_duplicate_or_missing_reads_cannot_establish_four_neutral_frames():
    b = Backend(); assert b.request(); record = b.instances['actor']['custom_stop']
    for _ in range(20): assert not b.tick(1/30)
    assert len(record['recovery_neutral_times']) == 1 and len(b.commands) == 1
    assert not b.tick(3/30)
    assert len(record['recovery_neutral_times']) == 1


def test_failed_idle_is_not_retried_and_the_original_budget_is_never_extended():
    b = Backend(); assert b.request(); b.pose[1][0] = .03
    b.idle = lambda: 0
    assert not b.tick(14.)
    record = b.instances['actor']['custom_stop']
    assert record['forced_idle_request'] and record['idle_request_failed']
    commands = copy.deepcopy(b.commands)
    assert not b.tick(14.2) and not b.tick(15.1)
    assert b.commands == commands and record['requested_sim_time'] == 10.
