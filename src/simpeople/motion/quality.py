"""Array-only measured support audits; contact selection never filters slip."""


def intervals(mask):
    import numpy as np
    edges = np.diff(np.r_[False, mask, False].astype(int))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def support_quality(times_s, selected_points_world_m):
    import numpy as np
    times = np.asarray(times_s, dtype=float)
    points = np.asarray(selected_points_world_m, dtype=float)
    if times.ndim != 1 or len(times) < 4 or points.ndim != 3 or points.shape[0] != len(times) or points.shape[1] < 1 or points.shape[2] != 3:
        raise ValueError('contiguous times and fixed sole point arrays required')
    if not np.isfinite(times).all() or not np.isfinite(points).all() or not np.allclose(np.diff(times), 1 / 30, atol=1e-7, rtol=0):
        raise ValueError('finite consecutive 30 Hz support samples required')
    z = points[:, :, 2].min(axis=1)
    contact = (np.abs(z) <= .025) & (np.abs(np.gradient(z, times)) <= .15)
    supports = []
    for start, end in intervals(contact):
        for first in range(start, end):
            last = min(end - 1, first + 60)
            if times[last] - times[first] < .1 - 1e-7:
                continue
            drift = float(np.linalg.norm(points[first:last + 1, :, :2] - points[first, :, :2], axis=-1).max())
            supports.append({'start_sim_time': float(times[first]), 'duration_s': float(times[last] - times[first]), 'max_selected_vertex_drift_m': drift})
    penetrations = [{'start_sim_time': float(times[a]), 'duration_s': float(times[b - 1] - times[a]), 'minimum_z_m': float(z[a:b].min())}
                    for a, b in intervals(z < -.02) if times[b - 1] - times[a] > .1 + 1e-7]
    long_windows = [s for s in supports if s['duration_s'] >= 2 - 1e-7]
    worst = max(supports, key=lambda s: s['max_selected_vertex_drift_m'], default=None)
    return {'min_sole_z_m': float(z.min()), 'penetration_failures': penetrations, 'support_windows': len(supports),
            'two_second_windows': len(long_windows), 'worst_support': worst,
            'passed': not penetrations and bool(long_windows) and all(s['max_selected_vertex_drift_m'] <= .03 for s in supports)}, contact
