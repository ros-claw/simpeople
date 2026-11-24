"""Read-only static navigation inputs; deliberately not a task feasibility grade."""
import math


def fixture_points(case, semantics):
    """Keep every use-site, including alternate interaction exit locations."""
    points = []

    def add(target, label):
        if isinstance(target, str):
            record = semantics.get(target, {})
            if 'position_m' not in record:
                raise ValueError('navigation location has no position_m: ' + target)
            target = record['position_m']
        if not isinstance(target, (list, tuple)) or len(target) != 3:
            raise ValueError('navigation location must contain three coordinates: ' + label)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in target):
            raise ValueError('navigation location must be finite: ' + label)
        points.append({'use': label, 'position_m': list(target)})

    for actor in case['actors']:
        add(actor['spawn_anchor'], 'spawn:' + actor['actor_id'])
    for request in case['requests']:
        for index, step in enumerate(request['steps']):
            label = request['request_case_id'] + ':step' + str(index)
            action = step['action']
            if action == 'move_to':
                for n, point in enumerate(step.get('via', [])):
                    add(point, label + ':via' + str(n))
                add(step['target'], label + ':goal')
            elif action == 'sit':
                record = semantics[step['target']]
                add(record['approach'], label + ':seat_approach')
                exits = record.get('egress_targets') or [record['egress']]
                for n, point in enumerate(exits):
                    add(point, label + ':seat_exit' + str(n))
            elif action == 'queue':
                record = semantics[step['target']]
                if not record.get('slots_m') or not record.get('egress_targets'):
                    raise ValueError('queue requires slots and physical exits: ' + step['target'])
                for n, point in enumerate(record['slots_m']):
                    add(point, label + ':queue_slot' + str(n))
                for n, point in enumerate(record['egress_targets']):
                    add(point, label + ':queue_exit' + str(n))
            elif action not in {'wait', 'leave_seat', 'look_at'}:
                raise ValueError('unhandled fixture action: ' + action)
    return points


def path_quality(start, goal, path, tolerance_m=.3):
    """Check BOTH endpoints; the native query can project an invalid start."""
    finite = bool(path) and all(len(p) == 3 and all(math.isfinite(v) for v in p) for p in path)
    start_error = math.dist(start, path[0]) if finite else None
    end_error = math.dist(goal, path[-1]) if finite else None
    return {'passed': finite and start_error <= tolerance_m and end_error <= tolerance_m,
            'start_projection_m': start_error, 'end_projection_m': end_error,
            'path_length_m': sum(math.dist(a, b) for a, b in zip(path, path[1:])) if finite else None,
            'endpoint_tolerance_m': tolerance_m}
