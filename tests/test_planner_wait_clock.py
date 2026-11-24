import ast
import copy
from pathlib import Path

from simpeople.core.traffic import FairGate


class Parent:
    def stop(self, handle): self.stops.append(handle)


def backend():
    source = Path(__file__).parents[1]/'src/simpeople/backends/native/reservations.py'
    tree = ast.parse(source.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ReservationNativeBackend')
    block = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'block')
    module = ast.Module(body=[ast.ClassDef(name='Backend', bases=[ast.Name(id='Parent', ctx=ast.Load())],
        keywords=[], body=[block], decorator_list=[])], type_ignores=[])
    ast.fix_missing_locations(module); ns = {'Parent': Parent}
    exec(compile(module, str(source), 'exec'), ns)
    b = ns['Backend'](); b.fair_gate = FairGate(); b.now = 10.; b.corridor_profile = False
    b.stops = []; b.events = []; b.emit = lambda kind, **data: b.events.append((kind, data))
    return b


def job(status='running'):
    return {'handle': 'actor', 'status': status, 'blocked_since': None,
            'retry_at': 0, 'retry_actor_id': 'actor', 'step_deadline_sim_time': 240}


def test_active_ticket_starts_waiting_when_planner_cannot_reach_admission():
    b = backend(); j = job()
    b.fair_gate.request('route', 'actor', {(1, 0)}, 1, occupant_token='body')
    b.fair_gate.grant('route', 2)
    assert b.fair_gate.pending['route']['wait_since'] is None
    b.block('route', j); ticket = b.fair_gate.pending['route']
    assert ticket['state'] == 'waiting' and ticket['wait_since'] == 10
    assert ticket['since'] == 1 and ticket['sequence'] == 1
    assert j['step_deadline_sim_time'] == 240 and b.stops == ['actor']
    b.now = 41
    assert b.fair_gate.violations(b.now)[0]['wait_sim_s'] == 31
    assert 'route' in b.fair_gate.pending


def test_repeated_planner_wait_cannot_renew_age_or_reissue_stop():
    b = backend(); j = job()
    b.fair_gate.request('route', 'actor', {(1, 0)}, 1, occupant_token='body')
    b.block('route', j); before = copy.deepcopy(b.fair_gate.pending['route'])
    b.now = 20; b.block('route', j)
    assert b.fair_gate.pending['route'] == before and b.stops == ['actor']


def test_no_admission_ticket_is_invented_and_cancelled_fence_stays_absent():
    b = backend(); j = job(); b.block('route', j)
    assert not b.fair_gate.pending
    b.fair_gate.request('route', 'actor', {(1, 0)}, 1)
    b.fair_gate.cancel('route'); b.block('route', j)
    assert not b.fair_gate.pending


def test_other_waiters_order_and_current_claim_intent_are_preserved():
    b = backend(); j = job()
    b.fair_gate.request('older', 'other', {(1, 0)}, 0, occupant_token='other-body')
    b.fair_gate.request('route', 'actor', {(1, 0)}, 1, occupant_token='body')
    original = copy.deepcopy(b.fair_gate.pending)
    b.block('route', j)
    assert b.fair_gate.pending == original
    assert not b.fair_gate.allowed('route', {(1, 0)})
