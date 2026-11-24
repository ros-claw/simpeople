import numpy as np
import pytest
from simpeople.motion.quality import support_quality


def test_horizontal_slip_cannot_disappear_from_contact_selection():
    times = np.arange(90) / 30
    points = np.zeros((90, 2, 3))
    points[:, :, 0] = times[:, None] * .1
    result, contact = support_quality(times, points)
    assert contact.all()
    assert result['two_second_windows'] > 0
    assert result['worst_support']['max_selected_vertex_drift_m'] == pytest.approx(.2)
    assert result['passed'] is False


def test_stationary_support_passes_but_persistent_penetration_does_not():
    times = np.arange(90) / 30
    points = np.zeros((90, 2, 3))
    result, _ = support_quality(times, points)
    assert result['passed']
    points[20:30, :, 2] = -.03
    result, _ = support_quality(times, points)
    assert not result['passed'] and result['penetration_failures']
    points[:] = 0
    points[20, :, 2] = -.03
    result, _ = support_quality(times, points)
    assert not result['penetration_failures']


def test_support_audit_rejects_missing_or_non_finite_frames():
    points = np.zeros((90, 2, 3))
    times = np.arange(90) / 30
    times[35] += .01
    with pytest.raises(ValueError, match='consecutive'):
        support_quality(times, points)
    points[35, 0, 0] = np.nan
    with pytest.raises(ValueError):
        support_quality(np.arange(90) / 30, points)
