import copy
from types import SimpleNamespace

import pytest

from simpeople.backends.native import phase_end_stop as stop

POSE = [[0., 0., 0., 0., 0., 0., 1.], [0., 0., 1., 0., 0., 0., 1.]]


class Backend:
    def __init__(self):
        self.now = 10.; self.current = 35; self.commands = []; self.events = []
        self.states = {35: 'failed'}; self.pose = copy.deepcopy(POSE)
        self.phase_end_stop_probe_enabled = True
        self.instances = {'actor': dict(asset_id='default', traffic_instance_id='body1', engine_native_ids=[35])}
        self.assets = [dict(asset_id='default', content_hash='asset1')]
        self.timeline = SimpleNamespace(get_current_time=lambda: self.now)
        self.on_event = lambda kind, **p: self.events.append((kind, p))
        self.entry = dict(experimental_phase_sources=[{}], entry_base_action='Idle', canonical_entry=dict(
            source_asset_sha256='asset1', joint_paths=['Root', 'Root/Pelvis'],
            world_pose=copy.deepcopy(POSE), facing_direction=[0., 1., 0.]))
    def assert_thread(self): pass
    def get_action_task_id(self): return self.current
    def get_task_name(self, tid): return 'canonical' if tid == 35 else 'Idle'
    def task_state(self, handle, tid): return self.states[tid]
    def observe(self, handle):
        return dict(ready=True, observation_sim_time=self.now, native_task_id=self.current,
                    action='canonical' if self.current == 35 else 'Idle',
                    facing_direction=[0., 1., 0.], speed_mps=0.)
    def cancel_task(self, tid): self.commands.append(('cancel', tid))
    def idle(self): self.commands.append(('idle', 39)); return 39
    def start(self):
        assert stop.request(self, 'actor', self.entry, 35, 'canonical', self)
        return self.instances['actor']['custom_stop']
    def tick(self, tick):
        self.now = 10+tick/30
        return stop.advance(self, 'actor', self.instances['actor']['custom_stop'], self.observe('actor'), self)


@pytest.fixture(autouse=True)
def capture_actual_pose(monkeypatch):
    monkeypatch.setattr(stop, 'capture', lambda b, *_: copy.deepcopy(b.pose))


def test_sdk_idle_status_alone_never_certifies_a_non_neutral_end_phase():
    b = Backend(); b.pose[1][0] = .05; r = b.start(); b.current = 0
    for tick in range(1, 10): assert not b.tick(tick)
    assert b.commands == [('cancel', 35)] and not r['neutral_times']
    b.pose = copy.deepcopy(POSE)
    for tick in range(10, 14): assert not b.tick(tick)
    assert b.commands == [('cancel', 35), ('idle', 39)]
    assert r['idle_requested_sim_time'] == pytest.approx(10+13/30)
    assert not r['forced_idle_request'] and len(r['neutral_times']) == 4
    # No new custom action exists anywhere in the cancellation sequence.
    b.current = 39
    assert b.tick(14) and b.commands == [('cancel', 35), ('idle', 39)]


@pytest.mark.parametrize('fault', ['disabled', 'no_variants', 'foreign', 'generation', 'wrong_asset'])
def test_unqualified_cancel_does_not_claim_a_phase_exit(fault):
    b = Backend()
    if fault == 'disabled': b.phase_end_stop_probe_enabled = False
    if fault == 'no_variants': b.entry.pop('experimental_phase_sources')
    if fault == 'foreign': b.instances['actor']['engine_native_ids'] = []
    if fault == 'generation': b.instances['actor']['traffic_instance_id'] = ''
    if fault == 'wrong_asset':
        b.assets[0]['content_hash'] = 'other'
        with pytest.raises(ValueError): stop.request(b, 'actor', b.entry, 35, 'canonical', b)
    else:
        assert not stop.request(b, 'actor', b.entry, 35, 'canonical', b)
    assert not b.commands and 'custom_stop' not in b.instances['actor']


@pytest.mark.parametrize('fault', ['foreign', 'generation', 'stale', 'expired'])
def test_no_cleanup_command_can_take_a_later_owner_or_changed_body(fault):
    b = Backend(); r = b.start(); b.current = 0; b.now = 24.2; obs = b.observe('actor')
    if fault == 'foreign': b.current = 88; obs['native_task_id'] = 88
    if fault == 'generation': b.instances['actor']['traffic_instance_id'] = 'body2'
    if fault == 'stale': obs['observation_sim_time'] -= 1/30
    if fault == 'expired': b.now = 25.1; obs['observation_sim_time'] = b.now
    assert not stop.advance(b, 'actor', r, obs, b)
    assert b.commands == [('cancel', 35)]


def test_neutral_target_does_not_follow_later_root_motion_and_duplicates_do_not_count():
    b = Backend(); r = b.start(); b.current = 0
    for _ in range(20): assert not b.tick(1)
    assert len(r['neutral_times']) == 1
    assert not b.tick(3) and len(r['neutral_times']) == 1
    target = copy.deepcopy(r['neutral_target_world_pose'])
    for p in b.pose: p[0] += .1
    for tick in range(4, 20): assert not b.tick(tick)
    assert not r['neutral_times'] and r['neutral_target_world_pose'] == target


def test_forced_cleanup_retains_the_original_fifteen_second_budget():
    b = Backend(); b.pose[1][0] = .05; r = b.start(); b.current = 0
    assert not b.tick(419)
    assert not b.tick(420)
    assert r['forced_idle_request'] and r['requested_sim_time'] == 10.
    assert b.commands == [('cancel', 35), ('idle', 39)]
    b.current = 39
    assert not b.tick(451)
