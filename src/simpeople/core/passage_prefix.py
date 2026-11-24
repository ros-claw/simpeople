"""Do not end a bounded route inside an explicitly authored passage zone.

This selects an endpoint only. NavMesh validation, body clearance, fair order
and atomic reservation must still accept every leg of the resulting polyline.
"""
import math

from .traffic import polyline_prefix


def zone_from_approaches(name, first, second, half_width_m):
    values = [*first, *second, half_width_m]
    if (len(first) != 3 or len(second) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in values)
            or half_width_m <= 0 or abs(first[2]-second[2]) > .02):
        raise ValueError('finite horizontal passage approaches and width required')
    dx, dy = second[0]-first[0], second[1]-first[1]
    length = math.hypot(dx, dy)
    if length < .9:
        raise ValueError('distinct passage approaches required')
    return dict(name=name, center=[(a+b)/2 for a, b in zip(first, second)],
                axis=[dx/length, dy/length], half_length_m=length/2,
                half_width_m=half_width_m)


def coordinates(point, zone):
    dx, dy = point[0]-zone['center'][0], point[1]-zone['center'][1]
    x, y = zone['axis']
    return dx*x+dy*y, -dx*y+dy*x


def inside(point, zone):
    along, across = coordinates(point, zone)
    return (abs(along) < zone['half_length_m']+1e-8
            and abs(across) < zone['half_width_m']+1e-8)


def protected_prefix(points, distance_m, zones, landing_m=.1):
    """Extend a normal horizon through its containing zone, preserving corners.

    A requested final goal in the protected zone is rejected explicitly; this
    helper never moves a requested goal or silently calls it completed.
    """
    if (type(distance_m) not in (int, float) or not math.isfinite(distance_m)
            or distance_m <= 0 or type(landing_m) not in (int, float)
            or not math.isfinite(landing_m) or landing_m <= 0
            or len(points) < 2):
        raise ValueError('positive finite horizon and a polyline required')
    if any(len(p) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in p) for p in points):
        raise ValueError('finite three-dimensional route required')
    total = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    chosen = min(total, distance_m); touched = []
    # Each pass either leaves a zone or raises. A finite number of overlapping
    # zones therefore cannot turn endpoint selection into an unbounded loop.
    for _ in range(len(zones)+1):
        prefix = polyline_prefix(points, max(chosen, 1e-9))
        occupied = [z for z in zones if inside(prefix[-1], z)]
        if not occupied:
            return prefix, {'requested_horizon_m': distance_m, 'actual_horizon_m': chosen,
                            'extended_for_passages': touched}
        zone = occupied[0]
        if inside(points[-1], zone):
            raise ValueError('requested final goal lies inside no-stop passage: '+zone['name'])
        # Find the first true exit after the chosen endpoint. Line/box clipping
        # computes an exit on each route leg, without stepping across corners.
        walked = 0.; exit_at = None
        for a, b in zip(points, points[1:]):
            length = math.dist(a, b)
            if walked+length >= chosen-1e-9 and length > 1e-9:
                begin = max(0., (chosen-walked)/length)
                p = [a[k]+(b[k]-a[k])*begin for k in range(3)]
                if inside(p, zone):
                    uv = coordinates(p, zone); end_uv = coordinates(b, zone)
                    candidates = []
                    for value, end, bound in zip(uv, end_uv, [zone['half_length_m'], zone['half_width_m']]):
                        delta = end-value
                        if abs(delta) > 1e-12:
                            fraction = ((bound if delta > 0 else -bound)-value)/delta
                            if 0 <= fraction <= 1+1e-8:
                                candidates.append(fraction)
                    if candidates:
                        exit_at = walked+length*(begin+(1-begin)*min(candidates))
                        break
            walked += length
        if exit_at is None:
            raise ValueError('no verified route exit from passage: '+zone['name'])
        chosen = min(total, exit_at+landing_m)
        if zone['name'] not in touched:
            touched.append(zone['name'])
    raise ValueError('overlapping passage zones have no stable endpoint')
