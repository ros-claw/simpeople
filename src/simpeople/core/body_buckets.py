"""Conservative candidate lookup for one synchronous planning snapshot.

The caller still runs its exact swept-body predicate. This lookup grants no
clearance, claims or motion; invalid data falls back to the complete snapshot.
"""
import math


class BodyBuckets:
    def __init__(self, positions, radius_m):
        self.positions = {actor: tuple(p) if isinstance(p, (list, tuple)) else p
                          for actor, p in positions.items()}
        self.radius = radius_m
        self.cell = 2.0
        self.buckets = None
        if (type(radius_m) not in (int, float) or not math.isfinite(radius_m) or radius_m <= 0
                or any(not isinstance(p, (list, tuple)) or len(p) < 2
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in p[:2])
                    for p in self.positions.values())):
            return
        self.buckets = {}
        for actor, point in self.positions.items():
            key = (math.floor(point[0]/self.cell), math.floor(point[1]/self.cell))
            self.buckets.setdefault(key, []).append(actor)

    def candidates(self, start, end):
        if self.buckets is None:
            return self.positions
        if any(type(v) not in (int, float) or not math.isfinite(v) for p in (start, end) for v in p[:2]):
            return self.positions
        # Outward padding only enlarges the broad phase. Exact distance and the
        # close-initial-body exception remain in ReservationGrid.clearance.
        padding = 1e-9*max(1, *(abs(v) for p in (start, end) for v in p[:2]))
        lo = [math.floor((min(start[i], end[i])-self.radius-padding)/self.cell) for i in (0, 1)]
        hi = [math.floor((max(start[i], end[i])+self.radius+padding)/self.cell) for i in (0, 1)]
        if (hi[0]-lo[0]+1)*(hi[1]-lo[1]+1) > max(16, 2*len(self.positions)):
            return self.positions  # Long chords must not enumerate an unbounded grid.
        selected = {}
        for x in range(lo[0], hi[0]+1):
            for y in range(lo[1], hi[1]+1):
                for actor in self.buckets.get((x, y), ()):
                    selected[actor] = self.positions[actor]
        return selected
