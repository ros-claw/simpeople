"""Choose among registered seat exits without changing leases or movement.

This is an optional pre-admission choice. It does not reserve cells, release a
chair, bypass fairness, change a deadline or move an actor. The normal native
route and physical occupancy checks still decide execution and completion.
"""
import math


def select_exit(candidates, legacy, origin, resolve, query_path, can_traverse):
    rows = []
    for index, target in enumerate(candidates):
        if target is None:
            continue
        goal = resolve(target)
        path = query_path(origin, goal)
        row = {'target': target, 'declared_index': index, 'path_m': path,
               'eligible': False, 'reason': 'no_static_path'}
        if path and not all(len(p) == 3 and all(math.isfinite(v) for v in p) for p in path):
            row['reason'] = 'invalid_static_path'
            row['rejected_path_repr'] = repr(path)
            row['path_m'] = None
        elif path:
            # Do not use a query's projected start to skip the actor-to-path leg.
            row.update(start_projection_m=math.dist(origin, path[0]), end_projection_m=math.dist(goal, path[-1]))
            if row['start_projection_m'] > .02 or row['end_projection_m'] > .02:
                row['reason'] = 'projected_endpoint'
            else:
                points = [list(origin), *[list(p) for p in path[1:-1]], list(goal)]
                row['path_m'] = points
                row['length_m'] = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
                row['eligible'] = all(can_traverse(a, b) for a, b in zip(points, points[1:]))
                row['reason'] = 'clear' if row['eligible'] else 'current_body_or_claim_conflict'
        rows.append(row)
    clear = [row for row in rows if row['eligible']]
    # Preserve the old choice when it is already clear. Only a currently rejected
    # primary path justifies selecting a different registered exit.
    chosen = next((row['target'] for row in clear if row['target'] == legacy), None)
    if chosen is None and clear:
        chosen = min(clear, key=lambda r: (r['length_m'], r['declared_index']))['target']
    return {'chosen_target': legacy if chosen is None else chosen,
            'changed': chosen is not None and chosen != legacy, 'candidates': rows,
            'fallback_to_legacy': not clear}
