from types import SimpleNamespace

import pytest

from simpeople.backends.native.custom_stop import ready
from simpeople.backends.native.deferred_custom_stop import advance, request


class Backend:
    def __init__(self):
        self.now = 10.
        self.current = 35
        self.states = {35: 'running', 38: 'running'}
        self.commands = []
        self.events = []
        self.deferred_custom_stop_probe_enabled = True
        self.instances = {'actor': {'traffic_instance_id': 'body1', 'engine_native_ids': [35]}}
        self.api = SimpleNamespace(get_agent=lambda _: self)
        self.timeline = SimpleNamespace(get_current_time=lambda: self.now)
        self.on_event = lambda kind, **p: self.events.append((kind, p))

    def assert_thread(self):
        pass

    def get_action_task_id(self):
        return self.current

    def get_task_name(self, tid):
        return 'canonical' if tid == 35 else 'Idle'

    def task_state(self, handle, tid):
        return self.states[tid]

    def cancel_task(self, tid):
        self.commands.append(('cancel', tid))

    def idle(self):
        self.commands.append(('idle', 38))
        return 38

    def start(self):
        assert request(self, 'actor', {'canonical_entry': {'pose': 'reference'},
                                     'entry_base_action': 'Idle'}, 35, 'canonical', self)
        return self.instances['actor']['custom_stop']

    def obs(self, elapsed, action='Idle', current=0):
        self.now = 10 + elapsed
        self.current = current
        return dict(ready=True, action=action, native_task_id=current,
                    observation_sim_time=self.now, speed_mps=0.)


def test_request_only_cancels_once_and_preserves_the_original_clock():
    b = Backend()
    r = b.start()
    b.now = 11.
    assert request(b, 'actor', {'canonical_entry': {'pose': 'reference'},
                              'entry_base_action': 'Idle'}, 35, 'canonical', b)
    assert b.commands == [('cancel', 35)]
    assert r['requested_sim_time'] == 10. and r['idle_request_native_task_id'] is None
    assert len(b.events) == 1


@pytest.mark.parametrize('fault', ['opt_out', 'no_reference', 'wrong_base', 'unowned', 'generation'])
def test_unqualified_request_does_not_mutate_or_issue_sdk_commands(fault):
    b = Backend()
    entry = {'canonical_entry': {'pose': 'reference'}, 'entry_base_action': 'Idle'}
    if fault == 'opt_out': b.deferred_custom_stop_probe_enabled = False
    if fault == 'no_reference': entry['canonical_entry'] = {}
    if fault == 'wrong_base': entry['entry_base_action'] = 'Sit'
    if fault == 'unowned': b.instances['actor']['engine_native_ids'] = []
    if fault == 'generation': b.instances['actor']['traffic_instance_id'] = ''
    assert not request(b, 'actor', entry, 35, 'canonical', b)
    assert 'custom_stop' not in b.instances['actor'] and not b.commands and not b.events


def test_native_cancel_is_allowed_to_finish_before_requesting_owned_idle():
    b = Backend(); r = b.start()
    assert not advance(b, 'actor', r, b.obs(.2, 'canonical', 35), b)
    assert b.commands == [('cancel', 35)]
    b.states[35] = 'failed'
    assert not advance(b, 'actor', r, b.obs(.4), b)
    assert r['idle_request_native_task_id'] == 38
    assert r['idle_requested_sim_time'] == 10.4 and not r['forced_idle_request']
    assert b.commands == [('cancel', 35), ('idle', 38)]
    # The issuing frame and default Idle can never count toward settlement.
    assert not ready(b, 'actor', b.obs(.4), True)
    for tick in range(1, 16):
        assert not ready(b, 'actor', b.obs(.4 + tick/30, current=38), True)
    assert ready(b, 'actor', b.obs(.4 + 16/30, current=38), True)
    assert len(r['actual_idle_times']) == 16
    assert b.commands == [('cancel', 35), ('idle', 38)]


@pytest.mark.parametrize('fault', ['foreign_idle', 'changed_generation', 'stale', 'expired', 'same_tick', 'not_ready'])
def test_invalid_ownership_or_observation_never_issues_idle(fault):
    b = Backend(); r = b.start(); b.states[35] = 'failed'
    obs = b.obs(.5)
    if fault == 'foreign_idle': obs = b.obs(14.2, current=99)
    if fault == 'changed_generation': b.instances['actor']['traffic_instance_id'] = 'newbody'
    if fault == 'stale': obs['observation_sim_time'] -= 1/30
    if fault == 'expired': obs = b.obs(15.1)
    if fault == 'same_tick': obs = b.obs(0.)
    if fault == 'not_ready': obs['ready'] = False
    assert not advance(b, 'actor', r, obs, b)
    assert b.commands == [('cancel', 35)]


def test_fallback_still_requires_owned_slot_and_leaves_no_extended_budget():
    b = Backend(); r = b.start()
    assert not advance(b, 'actor', r, b.obs(13.9, 'canonical', 35), b)
    assert not advance(b, 'actor', r, b.obs(14., 'canonical', 35), b)
    assert r['forced_idle_request']
    assert b.commands == [('cancel', 35), ('idle', 38)]
    assert not ready(b, 'actor', b.obs(15.01, current=38), True)
    assert not r['actual_idle_times']


def test_failed_idle_receipt_is_recorded_and_never_retried():
    b = Backend(); r = b.start(); b.states[35] = 'failed'
    def bad_idle():
        b.commands.append(('idle', 0))
        return 0
    b.idle = bad_idle
    for elapsed in [.2, .3, 14.]:
        assert not advance(b, 'actor', r, b.obs(elapsed), b)
    assert r['idle_request_failed']
    assert b.commands == [('cancel', 35), ('idle', 0)]
    assert [e[0] for e in b.events] == ['native_custom_stop_requested', 'native_custom_idle_request_failed']
