"""Traffic budget events must respect a fixed-step clock's float rounding."""

from simpeople.core.traffic import FairGate


def test_wait_budget_ignores_roundoff_at_boundary_but_reports_next_tick_once():
    gate = FairGate(max_wait_sim_s=30)
    gate.request('route', 'person', {(0, 0)}, 2.500000000000001)

    # Actual 30-second boundary from a native 1/30-second simulation trace.
    assert gate.violations(32.50000000000072) == []

    violations = gate.violations(32.53333333333405)
    assert len(violations) == 1
    assert violations[0]['key'] == 'route'
    assert violations[0]['wait_sim_s'] > 30
    assert gate.violations(32.56666666666738) == []


def test_wait_budget_still_reports_excess_beyond_clock_tolerance():
    gate = FairGate(max_wait_sim_s=30)
    gate.request('route', 'person', {(0, 0)}, 0.0)

    violations = gate.violations(30.000000002)
    assert len(violations) == 1
    assert violations[0]['wait_sim_s'] > 30
