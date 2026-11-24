"""Actual helper invariants with a fake SDK sampler; no Native certificate."""
import copy

import pytest

from simpeople.backends.native.local_yield_stop import retain, advance_stops, may_start
from simpeople.core.traffic import ReservationGrid


class Backend:
    def __init__(self):
        self.now = 0.; self.events = []; self.local_yield_stops = {}
        self.instances = {'west': {'traffic_instance_id': 'body1'}}
        self.grid = ReservationGrid(set(), {}); self.grid.claims = {'west': {(1, 2)}, 'witness': {(4, 5)}}
        self.routes = {'old': {'local_yield': {'body_generation': 'body1'}}}
    def assert_thread(self): pass
    def emit(self, kind, **payload): self.events.append((kind, payload))
    def sample(self, tick):
        self.now = tick/30
        return dict(ready=True, action='Idle', position_m=[1., 2., 0.], speed_mps=0.,
                    native_task_id=9, observation_sim_time=self.now,
                    position_source='BehaviorAgent.get_world_translation')


def test_exact_held_claim_waits_for_sixteen_adjacent_actual_samples():
    b = Backend(); assert retain(b, 'west', 'old')
    assert not may_start(b, 'west')
    for tick in range(15): advance_stops(b, {'west': b.sample(tick)})
    assert not may_start(b, 'west') and b.grid.claims['west'] == {(1, 2)}
    advance_stops(b, {'west': b.sample(15)})
    assert may_start(b, 'west') and b.grid.claims == {'witness': {(4, 5)}}
    receipt = b.instances['west']['settled_stop_receipt']
    assert receipt['native_task_id'] == 9 and receipt['body_generation'] == 'body1'
    assert receipt['actual_stable_samples'] == 16 and receipt['settled_sim_time'] == .5
    assert [e for k, e in b.events if k == 'traffic_cancelled_yield_claim_released'][0]['physical_stop_verified']


@pytest.mark.parametrize('fault', ['speed', 'actual_drift', 'stale', 'not_idle', 'gap', 'missing', 'nan'])
def test_invalid_readbacks_restart_the_physical_window_without_releasing(fault):
    b = Backend(); retain(b, 'west', 'old')
    for tick in range(15): advance_stops(b, {'west': b.sample(tick)})
    observation = b.sample(15)
    if fault == 'speed': observation['speed_mps'] = .15
    if fault == 'actual_drift': observation['position_m'][0] += .1
    if fault == 'stale': observation['observation_sim_time'] -= 1/30
    if fault == 'not_idle': observation['action'] = 'MoveAlong'
    if fault == 'gap': b.now += .1; observation['observation_sim_time'] = b.now
    if fault == 'nan': observation['position_m'][0] = float('nan')
    advance_stops(b, {} if fault == 'missing' else {'west': observation})
    assert b.grid.claims['west'] == {(1, 2)} and not may_start(b, 'west')
    assert 'settled_stop_receipt' not in b.instances['west']
    assert b.local_yield_stops['west']['stable_samples'] == 0


@pytest.mark.parametrize('fault', ['new_body', 'new_claim'])
def test_stale_stop_bookkeeping_cannot_release_a_later_owner(fault):
    b = Backend(); retain(b, 'west', 'old')
    if fault == 'new_body': b.instances['west']['traffic_instance_id'] = 'body2'
    else: b.grid.claims['west'] = {(7, 8)}
    claims = copy.deepcopy(b.grid.claims)
    advance_stops(b, {'west': b.sample(1)})
    assert b.grid.claims == claims and may_start(b, 'west')
    assert 'settled_stop_receipt' not in b.instances['west']
    assert b.events[-1][0] == 'traffic_cancelled_yield_settlement_stale'


def test_repeat_cancel_keeps_the_original_stop_clock_and_claim():
    b = Backend(); retain(b, 'west', 'old'); before = copy.deepcopy(b.local_yield_stops)
    b.now = .2
    assert retain(b, 'west', 'old') and b.local_yield_stops == before
    for _ in range(30): advance_stops(b, {'west': b.sample(6)})
    assert not may_start(b, 'west') and b.grid.claims['west'] == {(1, 2)}
