import copy

import pytest

from simpeople.backends.native.stationary_detour import start
from simpeople.backends.native import stationary_detour
from simpeople.core.traffic import ReservationGrid
from simpeople.core.stationary_blockers import settled_stop_receipt


class Backend:
    def __init__(self):
        self.now = 10.; self.events = []; self.commands = []; self.queries = 0; self.horizon = 4.
        self.runtime_policy = {'stationary_blocker_repair_enabled': True}
        self.instances = {h: {'traffic_instance_id': h+'-body'} for h in ['east', 'west']}
        self.instances.update({str(i): {'traffic_instance_id': str(i)} for i in range(11)})
        self.positions = {'east': [1.317, -9.504, 0.], 'west': [-1.24, -10.11, 0.]}
        self.grid = ReservationGrid({(-1, -7), (-1, -6)}, {})
        self.owner_routes = {'east': 'route1'}; self.local_yield_stops = {}
        self.observations = {'west': (10., dict(ready=True, action='Idle', speed_mps=0.,
            observation_sim_time=10., native_task_id=7, position_m=self.positions['west'],
            position_source='BehaviorAgent.get_world_translation'))}
        obs = self.observations['west'][1]
        stop = dict(body_generation='west-body', stable_since=9.5, stable_samples=16,
                    last_sample_time=10., last_position_m=list(obs['position_m']))
        self.instances['west']['settled_stop_receipt'] = settled_stop_receipt(stop, obs, 'west-body', 10.)
        self.job = dict(phase='travel', native_task_id=None, status='blocked', blocked_since=5.,
            blocked_details={'blocker_handles': ['west']}, goals=[[-5.25, -8.75, 0.]],
            goal_index=0, step={'action': 'move_to', 'timeout_s': 30., 'gait': 'walk'},
            requested_sim_time=0., step_deadline_sim_time=30., recovery_attempts=1,
            intent_points=[[1.317, -9.504, 0.], [-2.6, -9.3, 0.]],
            drain_escape_points=None, corridor_candidate={'goal_index': 0, 'horizon_m': 4.})
        self.routes = {'route1': self.job}; self.admission_allowed = True
    def assert_thread(self): pass
    def segment(self, first, last):
        self.queries += 1
        if first == self.positions['east']:
            return [first, [-.3008, -9.768, 0.], last]
        return [first, last]
    def admit_reservation(self, handle, rid, job, points, *, polyline, drain_exit_cells):
        assert polyline and drain_exit_cells == self.grid.footprint(job['goals'][job['goal_index']])
        return self.admission_allowed and self.grid.reserve_polyline(handle, points, self.positions)
    def submit(self, handle, spec): self.commands.append((handle, spec)); return 11
    def emit(self, kind, **payload): self.events.append((kind, payload))
    def run(self):
        return start(self, 'east', 'route1', self.job,
                     {'position_m': self.positions['east']}, self.submit, horizon_m=self.horizon)


def test_detour_keeps_nav_corners_original_goal_horizon_and_deadline():
    b = Backend(); before = copy.deepcopy(b.job); positions = copy.deepcopy(b.positions)
    assert b.run()
    for key in ['goals', 'goal_index', 'step', 'requested_sim_time',
                'step_deadline_sim_time', 'recovery_attempts']:
        assert b.job[key] == before[key]
    assert b.positions == positions and len(b.commands) == 1 and b.commands[0][0] == 'east'
    event = next(v for k, v in b.events if k == 'traffic_stationary_body_detour')
    assert [-.3008, -9.768, 0.] in event['submitted_points_m']
    assert event['prefix_profile']['requested_horizon_m'] == 4.
    assert b.job['continuous_next_goal_index'] == 0 and b.job['native_task_id'] == 11
    assert event['actual_blockers'][0]['body_generation'] == 'west-body'


def test_occupied_final_leg_is_rejected_even_when_first_leg_is_clear():
    b = Backend(); b.positions['third'] = list(b.job['goals'][0])
    assert not b.run() and not b.commands and not b.grid.claims


@pytest.mark.parametrize('fault', ['disabled', 'active_blocker', 'retained_stop', 'foreign_route', 'tail_mode', 'startup_idle'])
def test_noneligible_routes_never_query_or_command_the_native_driver(fault):
    b = Backend()
    if fault == 'disabled': b.runtime_policy.clear()
    if fault == 'active_blocker': b.owner_routes['west'] = 'another-route'
    if fault == 'retained_stop': b.local_yield_stops['west'] = {}
    if fault == 'foreign_route': b.owner_routes['east'] = 'another-route'
    if fault == 'tail_mode': b.runtime_policy['tail_release_enabled'] = True
    if fault == 'startup_idle': b.instances['west'].pop('settled_stop_receipt')
    assert not b.run() and not b.queries and not b.commands


def test_rejected_admission_restores_the_original_planning_hypothesis():
    b = Backend(); b.admission_allowed = False; before = copy.deepcopy(b.job)
    assert not b.run() and b.job == before and not b.commands and not b.grid.claims


def test_current_mandatory_goal_is_not_skipped_for_a_later_goal():
    b = Backend(); b.job['goals'].insert(0, [-2., -8.75, 0.])
    assert b.run()
    assert b.commands[0][1]['target'] == [-2., -8.75, 0.]
    assert len(b.job['goals']) == 2 and b.job['continuous_next_goal_index'] == 0


def test_missing_existing_horizon_does_not_invent_a_new_profile():
    b = Backend(); b.horizon = None
    assert not b.run() and not b.commands and not b.grid.claims


def test_redundant_close_first_waypoint_is_not_submitted_to_native_move_along():
    b = Backend(); original = b.segment
    def dense(first, last):
        path = original(first, last)
        if first == b.positions['east']:
            close = [first[i]+.005*(path[1][i]-first[i]) for i in range(3)]
            path.insert(1, close)
        return path
    b.segment = dense
    assert b.run()
    first = b.commands[0][1]['via'][0]
    assert sum((a-c)**2 for a, c in zip(first, b.positions['east'])) > .3**2
    event = next(v for k, v in b.events if k == 'traffic_stationary_body_detour')
    assert len(event['raw_navmesh_path_m']) > len(event['full_navmesh_path_m'])


def test_simplified_chord_must_pass_the_same_body_predicate(monkeypatch):
    b = Backend()
    monkeypatch.setattr(stationary_detour, 'simplify_polyline', lambda p, _: [p[0], p[-1]])
    assert not b.run() and not b.commands and not b.grid.claims
