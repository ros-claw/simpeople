"""Independent measured readiness windows, without a global actor barrier."""
import math


class ActorAdmissionWindows:
    """Latch one admission; schedule on the first True, without waiting again."""
    def __init__(self, actors, started, budget_s=8):
        if (not isinstance(actors, (list, tuple)) or not actors
                or any(not isinstance(a, str) or not a for a in actors)
                or len(set(actors)) != len(actors) or budget_s != 8
                or type(started) not in (int, float) or not math.isfinite(started) or started < 0):
            raise ValueError('distinct actors and original eight-second budget required')
        self.started = started
        self.windows = {actor: [] for actor in actors}
        self.ready = {}

    def observe(self, actor, stamp, frame, passed):
        if actor not in self.windows:
            raise ValueError('actor is outside this admission')
        if (type(stamp) not in (int, float) or not math.isfinite(stamp)
                or not self.started < stamp <= self.started+8+1e-7
                or type(frame) is not int or frame < 1 or type(passed) is not bool):
            raise ValueError('invalid actual readiness sample or original budget exceeded')
        if actor in self.ready:
            return True
        window = self.windows[actor]
        if not passed:
            window.clear(); return False
        if window and stamp == window[-1][0] and frame == window[-1][1]:
            return False
        if window and (frame != window[-1][1]+1 or abs(stamp-window[-1][0]-1/30) > 1e-7):
            window.clear()
        window.append((stamp, frame))
        if len(window) >= 4:
            self.ready[actor] = list(window[-4:])
            return True
        return False
