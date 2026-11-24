"""Read-only geometry for a bounded preexisting-occupant drainage candidate.

Not an admission, NavMesh proof, recovery command or permission to change a goal.
The native caller must independently verify a path and all current identities.
No runtime hook or default policy enables this experimental helper yet.
"""
import math

from .tail_release import conservative_swept_cells


def check_candidate(grid, pending, route_id, body_generation, path, positions, now):
    def reject(reason):
        return {'eligible': False, 'reason': reason}
    row = pending.get(route_id)
    if (not row or row.get('state') != 'waiting' or not isinstance(body_generation, str) or not body_generation
            or row.get('occupant_token') != body_generation):
        return reject('not_current_waiting_body_generation')
    actor = row['actor']; origin = positions.get(actor)
    if (origin is None or len(path) < 2 or any(len(p) != 3 or any(
            not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in p) for p in path)
            or not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now)):
        return reject('invalid_actual_origin_path_or_clock')
    if any(len(p) != 3 or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)
                              for v in p) for p in positions.values()):
        return reject('invalid_actual_body_positions')
    for key, ticket in pending.items():
        if (not isinstance(ticket['since'], (int, float)) or isinstance(ticket['since'], bool)
                or not math.isfinite(ticket['since']) or not 0 <= ticket['since'] <= now
                or not isinstance(ticket['sequence'], int) or isinstance(ticket['sequence'], bool) or ticket['sequence'] < 1
                or not isinstance(ticket['actor'], str) or not ticket['actor']
                or (ticket['wait_since'] is not None and (not isinstance(ticket['wait_since'], (int, float))
                    or isinstance(ticket['wait_since'], bool) or not math.isfinite(ticket['wait_since'])
                    or not ticket['since'] <= ticket['wait_since'] <= now))):
            return reject('invalid_wait_age' if key == route_id else 'invalid_older_priority')
    if math.dist(path[0], origin) > 1e-5:
        return reject('path_does_not_start_at_actual_body')
    distance = math.dist(path[0][:2], path[-1][:2])
    length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
    if not .5 <= distance <= 3 or length > 4 or any(abs(p[2]-origin[2]) > .02 for p in path):
        return reject('not_bounded_local_drainage')
    if grid.claims.get(actor):
        return reject('existing_owned_claim_requires_settlement')
    cells = conservative_swept_cells(grid, path)
    if cells & grid.claimed(actor):
        return reject('foreign_exclusive_claim')
    if not all(grid.clearance(actor, a, b, positions) for a, b in zip(path, path[1:])):
        return reject('actual_body_clearance')
    def priority(p):
        return p['since'], p['sequence'], p['actor']
    start = grid.footprint(origin); end = grid.footprint(path[-1]); drained = []
    for old_id, old in pending.items():
        if old_id == route_id or priority(old) >= priority(row) or not old['cells'] & cells:
            continue
        # Existing body generations may leave the FULL protected area, never
        # remain within it, borrow another route's token or waive a newer fence.
        if (body_generation not in old['drainers'] or not start & old['cells']
                or end & old['cells']):
            return reject('not_preexisting_occupant_leaving_every_older_fence')
        drained.append({'route_id': old_id, 'priority_since_sim_time': old['since'],
                        'sequence': old['sequence'], 'protected_cells': sorted(old['cells'])})
    if not drained:
        return reject('no_older_fence_drained')
    if row['since'] > now or row['wait_since'] is None or row['wait_since'] > now:
        return reject('invalid_wait_age')
    return {'eligible': True, 'reason': 'geometric_candidate_only', 'actor': actor,
        'route_id': route_id, 'body_generation': body_generation, 'path_m': [list(p) for p in path],
        'conservative_cells': sorted(cells), 'drained_older_fences': drained,
        'priority_since_sim_time': row['since'], 'wait_since_sim_time': row['wait_since'],
        'priority_age_s': now-row['since'], 'waiting_age_s': now-row['wait_since'],
        'path_length_m': length, 'scope': 'Read-only geometric candidate, no NavMesh/SDK execution certification. No claim, priority, wait budget or original logical target changes.'}
