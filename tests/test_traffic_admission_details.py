"""Exercise the native admission decision with a real grid, without importing Kit."""
import ast
import math
from pathlib import Path
from types import SimpleNamespace

from simpeople.core.traffic import FairGate, ReservationGrid


def test_admission_reports_clock_and_overlapping_blocker_sources():
    path = Path(__file__).resolve().parents[1] / 'src/simpeople/backends/native/reservations.py'
    tree = ast.parse(path.read_text())
    backend_class = next(node for node in tree.body if getattr(node, 'name', '') == 'ReservationNativeBackend')
    method = next(node for node in backend_class.body if getattr(node, 'name', '') == 'admit_reservation')
    scope = {
        'math': math,
        'candidate_conflicts': lambda *args, **kwargs: {},
    }
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), scope)
    grid = ReservationGrid({(0, 0), (1, 0), (2, 0)}, {})
    grid.claims['reserved'] = {(1, 0)}
    gate = FairGate()
    gate.request('older', 'reserved', {(1, 0)}, 1.0)
    events = []
    backend = SimpleNamespace(
        grid=grid, now=4.0, fair_gate=gate,
        positions={'walker': [0., 0., 0.], 'body': [1.25, 0., 0.], 'reserved': [0., 3., 0.]},
        instances={name: {'traffic_instance_id': name} for name in ['walker', 'body', 'reserved']},
        owner_routes={}, actor_label=str, emit=lambda event, **fields: events.append(event),
        runtime_policy=dict(diagonal_tail_release_enabled=False, goal_claim_wait_enabled=False,
                            traffic_fairness_enabled=True, max_wait_sim_s=30),
    )
    job = dict(step={}, goals=[[2.5, 0., 0.]], goal_index=0, retry_at=0,
               retries=0, recovery_attempts=0)
    admit = scope['admit_reservation']
    assert not admit(backend, 'walker', 'walker-route', job, [[0., 0., 0.], [2.5, 0., 0.]])
    details = job['blocked_details']
    assert details['candidate_checked_sim_time'] == 4.0
    assert details['blocker_ids'] == ['body', 'reserved']
    assert details['body_blocker_ids'] == ['body']
    assert details['reservation_blocker_ids'] == ['reserved']
    assert details['older_ticket_blocker_ids'] == ['reserved']
    assert details['physically_feasible'] is False
    assert grid.claims == {'reserved': {(1, 0)}}
    assert 'traffic_admission_granted' not in events


def test_conflict_evidence_uses_configured_body_clearance():
    from simpeople.core.candidate_paths import conflicts

    class ConservativeGrid(ReservationGrid):
        def clearance(self, actor, start, end, positions):
            # This test's horizontal route crosses the other body's x coordinate.
            return all(abs(body[1] - start[1]) >= self.body_clearance_m
                       for body in positions.values())

    grid = ConservativeGrid({(0, 0), (1, 0)}, {})
    grid.body_clearance_m = 1.1
    evidence = conflicts(grid, 'walker', [[0., 0., 0.], [1.25, 0., 0.]],
                         {'bystander': [0.5, 1.02, 0.]})
    assert not evidence['physical_feasible']
    assert evidence['body_conflicts'][0]['distance_m'] == 1.02
    assert evidence['body_conflicts'][0]['threshold_m'] == 1.1
