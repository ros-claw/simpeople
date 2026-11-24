"""Frame-driven camera math. No wall clock, Kit imports or world advancement."""
import math

CORE_EYE = [16, -19, 8.5]
CORE_TARGET = [6.5, -4, 1]


def ease(value):
    u = max(0.0, min(1.0, value))
    return u * u * u * (u * (u * 6 - 15) + 10)


def mix(a, b, u):
    return [x + (y - x) * u for x, y in zip(a, b)]


def rail(t, keys):
    if t <= keys[0][0]:
        return list(keys[0][1]), list(keys[0][2])
    for left, right in zip(keys, keys[1:]):
        if t <= right[0]:
            u = ease((t - left[0]) / (right[0] - left[0]))
            return mix(left[1], right[1], u), mix(left[2], right[2], u)
    return list(keys[-1][1]), list(keys[-1][2])


class CinematicCamera:
    def __init__(self, mode, fps=30):
        if mode not in {'technical', 'director', 'master'} or fps != 30:
            raise ValueError('supported production modes use 30 simulation frames/s')
        self.mode, self.fps = mode, fps
        self.filtered = {}
        self.last_frame = None
        self.handoff_pose = None

    def follow(self, actor_id, positions, offset):
        point = positions.get(actor_id, self.filtered.get(actor_id, [0, -5, 0]))
        before = self.filtered.get(actor_id, point)
        alpha = 1 - math.exp(-1 / (self.fps * .18))
        point = mix(before, point, alpha)
        self.filtered[actor_id] = point
        target = [point[0], point[1], 1.0]
        return [target[i] + offset[i] for i in range(3)], target

    def pose(self, frame, positions):
        if frame == self.last_frame:
            return self.last_pose
        self.last_frame = frame
        t = frame / self.fps
        if self.mode == 'technical':
            if t < 10:
                eye, target = [1, -12, 2.6], [-4, -5, .9]
                shot = 'technical_static'
            elif t < 20:
                eye, target = rail(t - 10, [(0, [9, -15, 3.3], [5, -6, 1.2]), (10, [15, -11, 3.3], [8, -4, 1.2])])
                shot = 'technical_dolly'
            else:
                eye, target = self.follow('patrol_orange', positions, [2.5, -6, 1.7])
                shot = 'technical_follow'
            lens = 32
        elif self.mode == 'director':
            if t < 5:
                eye, target = rail(t, [(0, [16, -20, 12], [1, -8, 0]), (5, CORE_EYE, CORE_TARGET)])
            else:
                eye, target = CORE_EYE, CORE_TARGET
            shot, lens = ('director_core' if t >= 5 else 'director_establish'), 23
        else:
            if t < 10:
                eye, target = rail(t, [(0, [17, -20, 8.8], [0, -2, 1]), (10, [-6, -11, 3.2], [-7, -5, 1])])
                shot, lens = 'hall_entry', 28
            elif t < 21:
                eye, target = self.follow('patrol_orange', positions, [2.5, -6, 1.7])
                shot, lens = 'patrol_follow', 32
            elif t < 33:
                eye, target = rail(t, [(21, [13, -14, 3.2], [7.5, -8.75, 1]), (24, [11.2, -12.3, 2.15], [7.5, -8.75, .85]), (33, [11.2, -12.3, 2.15], [7.5, -8.75, .85])])
                shot, lens = 'seat_cycle', 35
            elif t < 40:
                eye, target = self.follow('jogger', positions, [1.2, -6, 1.6])
                self.handoff_pose = (eye, target)
                shot, lens = 'jogger_handoff', 30
            elif t < 44:
                start = self.handoff_pose or ([16, -12, 3], [14, -6.25, 1])
                u = ease((t - 40) / 4)
                eye, target = mix(start[0], CORE_EYE, u), mix(start[1], CORE_TARGET, u)
                shot, lens = 'junction_settle', 30+(23-30)*u
            elif t < 68:
                eye, target = CORE_EYE, CORE_TARGET
                shot, lens = 'agent_core_uncut', 23
            elif t < 80:
                eye, target = rail(t, [(68, [20, -12, 4.7], [14.5, -4.4, 1]), (80, [20, -10, 4.7], [14.5, -4, 1])])
                shot, lens = 'b_area_arrival', 32
            else:
                eye, target = rail(t, [(80, [20, -10, 4.7], [14.5, -4, 1]), (86, [17, -20, 8.8], [0, -2, 1]), (90, [17, -20, 8.8], [0, -2, 1])])
                shot, lens = 'hall_return', 32+(28-32)*ease((t-80)/6)
        self.last_pose = {'eye_m': list(eye), 'look_at_m': list(target), 'focal_mm': lens, 'shot': shot,
                          'frame': frame, 'film_time_s': t, 'up': [0, 0, 1]}
        return self.last_pose
