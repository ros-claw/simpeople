"""Recovery invariants with a fake Native executor; no Native pass inferred."""
import copy
import ast
import gzip
import heapq
import importlib.util
import json
import math
from pathlib import Path

import pytest

from simpeople.backends.native.arrival_recovery import ArrivalRecoveryMixin, stationary_window
from simpeople.core.traffic import ReservationGrid
from simpeople.core.route_history import history_path
from simpeople.core.candidate_paths import destination as candidate_destination
from simpeople.core.path_diagnostics import select_candidate,report_search_wait


class Parent:
    def task_state(self, handle, tid):
        return self.states[tid]

    def start(self, handle, step):
        self.commands.append((self.now, handle, step))
        if step['action'] == 'move_to':
            assert 'via' not in step
            self.current = 10; self.states[10] = 'running'
            return 10
        assert step == {'action': 'settle'}
        if self.stop_error:
            raise RuntimeError('simulated Native stop failure')
        self.current = 9
        self.states[9] = 'running'
        return 9


class Backend(ArrivalRecoveryMixin, Parent):
    def __init__(self, retries=0, enabled=True):
        self.arrival_recovery_probe_enabled = enabled
        self.local_yield_stops = {}
        self.now = 0.; self.current = 0; self.stop_error = False
        self.states = {8: 'succeeded'}; self.commands = []; self.events = []
        self.instances = {'a': {'traffic_instance_id': 'body-a'}}; self.owner_routes = {'a': 'r'}
        self.grid = ReservationGrid({(x, 0) for x in range(20)}, {})
        self.grid.claims = {'a': {(0, 0), (1, 0), (2, 0)}, 'witness': {(5, 0)}}
        self.job = {'handle': 'a', 'native_task_id': 8, 'status': 'running', 'phase': 'travel',
                    'segment_goal': [12, 0, 0], 'goals': [[12, 0, 0]], 'goal_index': 0,
                    'step': {'action': 'move_to', 'target': [12, 0, 0], 'timeout_s': 240},
                    'requested_sim_time': 0., 'retries': retries, 'retry_delay_s': .23}

    def assert_thread(self):
        pass

    def agent(self, handle):
        assert handle == 'a'
        return self

    def get_action_task_id(self):
        return self.current

    def get_task_name(self, tid):
        return 'Idle' if tid in {0, 9} else 'MoveAlong'

    def is_standing(self, handle, obs):
        return obs.get('joints_m', {}).get('Hips', [0, 0, 0])[2] - obs['position_m'][2] > .75

    def emit(self, kind, **payload):
        self.events.append((kind, copy.deepcopy(payload)))

    def complete(self, rid, job, status, error):
        assert rid == 'r'
        job.update(status=status, error=error)
        self.grid.release('a')

    def observation(self, tick):
        self.now = tick / 30
        return {'ready': True, 'position_m': [0, 0, 0], 'speed_mps': 0.,
                'observation_sim_time': self.now, 'position_source': 'BehaviorAgent.get_world_translation',
                'action': 'Idle', 'native_task_id': self.current, 'joints_m': {'Hips': [0, 0, .95]}}


def confirm(backend):
    for i in range(16):
        handled = backend._arrival_shortfall('a', 'r', backend.job, backend.observation(i))
        assert handled == (i == 15)
    assert backend.job['phase'] == 'arrival_braking'


def settle(backend):
    for i in range(16, 32):
        assert backend._tick_arrival_recovery('a', 'r', backend.job, backend.observation(i))


def test_disabled_profile_has_no_side_effect_or_native_getter():
    b = Backend(enabled=False); before = copy.deepcopy((b.job, b.grid.claims))
    b.agent = lambda _: (_ for _ in ()).throw(AssertionError('unexpected Native read'))
    for i in range(40):
        assert not b._arrival_shortfall('a', 'r', b.job, b.observation(i))
    assert (b.job, b.grid.claims) == before and not b.commands


def test_no_claim_released_until_new_owned_idle_has_full_window():
    b = Backend(); original = copy.deepcopy(b.job); claims = copy.deepcopy(b.grid.claims)
    confirm(b)
    assert len(b.commands) == 1 and b.grid.claims == claims
    for i in range(16, 31):
        b._tick_arrival_recovery('a', 'r', b.job, b.observation(i))
        assert b.grid.claims == claims
    b._tick_arrival_recovery('a', 'r', b.job, b.observation(31))
    assert b.grid.claims == {'a': {(0, 0)}, 'witness': {(5, 0)}}
    assert b.job['native_task_id'] is None and b.job['phase'] == 'travel'
    assert b.job['arrival_segment_fallback'] is True and b.job['intent_points'] is None
    assert b.job['retry_at'] == pytest.approx(31/30+.23) and b.job['retries'] == 1
    for k in ['goals', 'goal_index', 'step', 'requested_sim_time']:
        assert b.job[k] == original[k]
    assert b.owner_routes == {'a': 'r'} and len(b.commands) == 1
    assert [k for k, _ in b.events].count('traffic_wait_started') == 1
    assert [k for k, _ in b.events].count('traffic_wait_ended') == 1


@pytest.mark.parametrize('bad', ['moving', 'stale', 'other_sdk', 'standing', 'gap', 'wrong_body', 'wrong_route', 'goal_changed'])
def test_unverified_stop_cannot_release_future_claims(bad):
    b = Backend(); confirm(b); claims = copy.deepcopy(b.grid.claims)
    for i in range(16, 45):
        obs = b.observation(i)
        if bad == 'moving': obs['speed_mps'] = .15
        elif bad == 'stale': obs['observation_sim_time'] -= 1/30
        elif bad == 'other_sdk': obs['native_task_id'] = 0
        elif bad == 'standing': obs['joints_m']['Hips'][2] = .5
        elif bad == 'gap': b.now = i*.1; obs['observation_sim_time'] = b.now
        elif bad == 'wrong_body': b.instances['a']['traffic_instance_id'] = 'recreated'
        elif bad == 'wrong_route': b.owner_routes['a'] = 'new-route'
        elif bad == 'goal_changed': b.job['segment_goal'] = [11, 0, 0]
        b._tick_arrival_recovery('a', 'r', b.job, obs)
    assert b.grid.claims == claims and b.job['native_task_id'] == 8
    assert len(b.commands) == 1


def test_failed_stop_remains_explicit_and_preserves_original_budget():
    b = Backend(); b.stop_error = True; original = copy.deepcopy(b.job); confirm(b)
    for i in range(16, 100):
        b._tick_arrival_recovery('a', 'r', b.job, b.observation(i))
    assert len(b.commands) == 1 and b.job['phase'] == 'arrival_braking'
    assert 'stop_error' in b.job['blocked_details'] and len(b.grid.claims['a']) == 3
    assert b.job['step'] == original['step'] and b.job['requested_sim_time'] == 0


def test_native_failure_retries_share_the_same_three_attempt_limit():
    b = Backend(retries=2); confirm(b); assert len(b.grid.claims['a']) == 3
    settle(b)
    assert b.job['status'] == 'failed' and b.job['retries'] == 3
    assert b.job['error']['code'] == 'NATIVE_ARRIVAL_MISMATCH'
    assert b.job['error']['details']['physical_stop_verified'] is True
    assert 'a' not in b.grid.claims and b.grid.claims['witness'] == {(5, 0)}
    assert len(b.commands) == 1


def test_cancelled_route_cannot_release_or_dispatch_again():
    b = Backend(); confirm(b); b.job['status'] = 'cancelled'; before = copy.deepcopy(b.grid.claims)
    for i in range(16, 50):
        assert not b._tick_arrival_recovery('a', 'r', b.job, b.observation(i))
    assert b.grid.claims == before and len(b.commands) == 1


def test_cleanup_already_requested_finishes_if_profile_is_turned_off():
    b = Backend(); confirm(b); b.arrival_recovery_probe_enabled = False; settle(b)
    assert b.job['native_task_id'] is None and len(b.grid.claims['a']) == 1


@pytest.mark.parametrize('change', ['near', 'sdk_running', 'sdk_failed', 'sdk_mismatch', 'sit_phase', 'other_owner', 'invalid_body', 'default_sdk_id'])
def test_normal_arrival_running_or_unowned_tasks_never_trigger_repair(change):
    b = Backend()
    for i in range(30):
        obs = b.observation(i)
        if change == 'near': obs['position_m'] = [11.8, 0, 0]; obs['joints_m']['Hips'] = [11.8, 0, .95]
        elif change == 'sdk_running': b.states[8] = 'running'
        elif change == 'sdk_failed': b.states[8] = 'failed'
        elif change == 'sdk_mismatch': obs['native_task_id'] = 11
        elif change == 'sit_phase': b.job['phase'] = 'sit'
        elif change == 'other_owner': b.owner_routes['a'] = 'another'
        elif change == 'invalid_body': b.instances['a']['traffic_instance_id'] = True
        elif change == 'default_sdk_id': b.job['native_task_id'] = 0
        assert not b._arrival_shortfall('a', 'r', b.job, obs)
    assert not b.commands and len(b.grid.claims['a']) == 3


@pytest.mark.parametrize('receipt', [None, True, 0, 8])
def test_invalid_or_retired_stop_receipt_cannot_authorize_release(monkeypatch, receipt):
    monkeypatch.setattr(Parent, 'start', lambda *args: receipt)
    b = Backend(); confirm(b)
    for i in range(16, 50): b._tick_arrival_recovery('a', 'r', b.job, b.observation(i))
    assert b.job['arrival_stop_id'] is None and 'stop_error' in b.job['blocked_details']
    assert len(b.grid.claims['a']) == 3


def test_duplicate_queries_and_changed_clock_or_identity_do_not_count_as_samples():
    b = Backend(); state = None
    for _ in range(30): state, ready = stationary_window(state, b.observation(0), 0., ['body-a'])
    assert state['count'] == 1 and not ready
    for i in range(1, 16): state, ready = stationary_window(state, b.observation(i), b.now, ['body-a'])
    assert ready
    state, ready = stationary_window(state, b.observation(16), b.now, ['new-body'])
    assert state['count'] == 1 and not ready
    state, ready = stationary_window(state, b.observation(0), b.now, ['new-body'])
    assert state['count'] == 1 and not ready


def test_actual_sdk_success_shortfall_rows_exercise_confirmation_without_native_claim():
    path = Path(__file__).parents[1]/'reports/evidence/iteration_20261115_sdk_success_shortfall/actual_task_window.jsonl.gz'
    if not path.is_file():
        pytest.skip('Native replay capture is retained in the local acceptance workspace')
    rows = [json.loads(s) for s in gzip.decompress(path.read_bytes()).splitlines()]
    b = Backend(); b.job['segment_goal'] = [8.085507713487434, -5.042952060699463, .002749995794147253]
    for row in rows:
        b.now = row['sim_time']; b.current = row['native_task_id']
        if b._arrival_shortfall('a', 'r', b.job, row): break
    assert len(b.commands) == 1 and b.job['phase'] == 'arrival_braking'
    assert 1.733 < b.now < 3 and len(b.grid.claims['a']) == 3
    # The new Idle and replanning remain fake-executor checks, not new Native evidence.


@pytest.mark.parametrize('enabled', [False, True])
def test_exact_native_route_hooks_delegate_only_after_verified_stop(enabled):
    root = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location('arrival_candidate', root/'scripts/prepare_arrival_recovery_candidate.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    # Hooks now live in Root. Exercise that implementation without applying
    # the historical experimental patch a second time.
    code = (root/'src/simpeople/backends/native/reservations.py').read_text()
    tree = ast.parse(code)
    original = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ReservationNativeBackend')
    method = next(n for n in original.body if isinstance(n, ast.FunctionDef) and n.name == 'tick_route')
    wrapper = ast.Module(body=[ast.ClassDef(name='Replay', bases=[ast.Name(id='Backend', ctx=ast.Load())],
        keywords=[], body=[method], decorator_list=[])], type_ignores=[])
    ast.fix_missing_locations(wrapper); namespace = {'Backend': Backend, 'math': math, 'heapq': heapq,
        'history_path': history_path, 'candidate_destination': candidate_destination,
        'select_candidate': select_candidate, 'report_search_wait': report_search_wait}
    exec(compile(wrapper, 'exact_candidate_tick_route', 'exec'), namespace)
    b = namespace['Replay'](enabled=enabled); b.routes = {'r': b.job}; b.corridor_profile = True
    b.job.update(retry_at=0., continuous_active=False)
    def corridor(*args):
        raise AssertionError('the failed multi-waypoint mode must not be immediately repeated')
    b.start_continuous_corridor = corridor
    nodes = {(x, y) for x in range(20) for y in range(-2, 3)}
    b.grid.nodes = nodes
    b.grid.edges = {n: [(n[0]+dx, n[1]+dy) for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]
                       if (n[0]+dx, n[1]+dy) in nodes] for n in nodes}
    b.positions = {'a': [0, 0, 0], 'witness': [18.75, 2.5, 0]}
    b.runtime_policy = {'goal_claim_wait_enabled': False, 'dynamic_edges_enabled': False, 'candidate_repair_enabled': False}
    b.grid_connection = lambda *args, **kwargs: True
    b.admit_reservation = lambda handle, rid, job, points, **kwargs: b.grid.reserve_polyline(handle, points, b.positions)
    b.block = lambda *args: (_ for _ in ()).throw(AssertionError('unexpected geometric refusal'))
    for i in range(16): b.tick_route('a', 'r', b.observation(i))
    if not enabled:
        assert not b.commands and b.job['native_task_id'] == 8
        return
    assert len(b.commands) == 1 and len(b.grid.claims['a']) == 3
    for i in range(16, 32): b.tick_route('a', 'r', b.observation(i))
    assert len(b.commands) == 1 and b.grid.claims['a'] == {(0, 0)}
    assert b.job['native_task_id'] is None
    for i in range(32, 38): b.tick_route('a', 'r', b.observation(i))
    assert len(b.commands) == 1
    b.tick_route('a', 'r', b.observation(38))
    assert len(b.commands) == 2 and b.job['native_task_id'] == 10
    assert b.commands[-1][2]['action'] == 'move_to' and 'via' not in b.commands[-1][2]
    assert b.job['goals'] == [[12, 0, 0]] and b.corridor_profile is True


def test_candidate_builder_refuses_unreviewed_or_duplicate_hooks():
    root = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location('arrival_candidate', root/'scripts/prepare_arrival_recovery_candidate.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    source = (root/'src/simpeople/backends/native/reservations.py').read_text()
    with pytest.raises(ValueError): builder.integrate_reservations(source.replace('job[\'segment_goal\']', 'job[\'another_goal\']'))
    with pytest.raises(ValueError): builder.integrate_reservations(builder.integrate_reservations(source))


def test_generic_activity_recovery_cannot_bypass_unverified_native_stop():
    root = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location('arrival_candidate', root/'scripts/prepare_arrival_recovery_candidate.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    code = (root/'src/simpeople/backends/native/reservations.py').read_text()
    cls = next(n for n in ast.parse(code).body if isinstance(n, ast.ClassDef) and n.name == 'ReservationNativeBackend')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'request_recovery')
    tree = ast.Module(body=[ast.ClassDef(name='Replay', bases=[ast.Name(id='Backend', ctx=ast.Load())],
        keywords=[], body=[method], decorator_list=[])], type_ignores=[])
    ast.fix_missing_locations(tree); namespace = {'Backend': Backend}
    exec(compile(tree, 'exact_candidate_request_recovery', 'exec'), namespace)
    b = namespace['Replay'](); b.routes = {'r': b.job}; b.stop_error = True; confirm(b)
    before = copy.deepcopy((b.job, b.grid.claims, b.commands))
    assert b.request_recovery('a', 'r') == {'accepted': False, 'reason': 'native_arrival_stop_in_progress'}
    assert (b.job, b.grid.claims, b.commands) == before
