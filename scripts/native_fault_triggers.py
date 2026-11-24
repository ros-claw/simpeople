"""Typed, simulation-clock diagnostic triggers; no Kit imports or mutation."""
import copy
import math

FENCES = ('session_id', 'episode_id', 'actor_id', 'actor_instance_id', 'control_epoch',
          'task_id', 'agent', 'body_instance_id')


def finite(value, name, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError('invalid trigger ' + name)


def validate_triggers(events, actors):
    previous = set()
    count = 0
    declarations = {}
    for event in events:
        if event['event_id'] in previous:
            raise ValueError('duplicate diagnostic event')
        trigger = event.get('trigger')
        if 'trigger' in event:
            count += 1
            if not isinstance(trigger, dict):
                raise ValueError('trigger must be a typed object')
            if trigger.get('kind') in {'native_diagonal_release', 'native_local_yield_motion'}:
                if set(trigger) - {'kind', 'actor_id', 'witness_actor_id', 'placement'}:
                    raise ValueError('unknown native release trigger field')
                if trigger.get('actor_id') not in actors or trigger.get('witness_actor_id') not in actors or trigger['actor_id'] == trigger['witness_actor_id']:
                    raise ValueError('trigger requires different known lead and witness')
                if event['method'] == 'cancel':
                    if 'placement' in trigger or set(event['params']) != {'actor_id'} or event['params'].get('actor_id') != trigger['actor_id']:
                        raise ValueError('cancel trigger actor or placement mismatch')
                elif event['method'] == 'move_prop':
                    p = trigger.get('placement', {})
                    if set(p) != {'forward_m', 'end_margin_m', 'z_m'} or set(event['params']) != {'prop_id'}:
                        raise ValueError('release placement must be explicit and resolved once on the observed path')
                    finite(p['forward_m'], 'forward_m', .1, 5)
                    finite(p['end_margin_m'], 'end_margin_m', .01, .5)
                    finite(p['z_m'], 'z_m', 0, 5)
                elif event['method'] == 'run_activity' and trigger['kind'] == 'native_local_yield_motion':
                    params = event['params']
                    if ('placement' in trigger or set(params) != {'actor_id', 'steps'}
                            or params['actor_id'] != trigger['actor_id']
                            or not isinstance(params['steps'], list) or len(params['steps']) != 1):
                        raise ValueError('yield replacement requires one explicit action for the same actor')
                    step = params['steps'][0]
                    if not isinstance(step, dict):
                        raise ValueError('yield replacement requires a typed action')
                    if step.get('action') == 'move_to':
                        if (set(step) != {'action', 'target', 'timeout_s'}
                                or not isinstance(step['target'], list) or len(step['target']) != 3):
                            raise ValueError('yield replacement requires one finite move target and deadline')
                        for value in step['target']: finite(value, 'replacement target', -100, 100)
                    elif step.get('action') == 'wait':
                        if set(step) != {'action', 'duration_s', 'timeout_s'}:
                            raise ValueError('yield wait replacement requires explicit duration and deadline')
                        finite(step['duration_s'], 'replacement duration', .1, 30)
                    else:
                        raise ValueError('unsupported yield replacement action')
                    finite(step['timeout_s'], 'replacement timeout', 1, 60)
                    if step.get('action') == 'wait' and step['duration_s'] >= step['timeout_s']:
                        raise ValueError('yield wait replacement must finish within its original deadline')
                else:
                    raise ValueError('unsupported native release operation')
            elif trigger.get('kind') == 'activity_succeeded':
                fields = {'kind', 'event_id', 'actor_id', 'witness_actor_id'}
                parent = declarations.get(trigger.get('event_id'), {})
                actor, witness = trigger.get('actor_id'), trigger.get('witness_actor_id')
                parent_steps = parent.get('params', {}).get('steps', [])
                if (set(trigger) - fields - {'resume_via'} or not fields <= set(trigger)
                        or ('resume_via' in trigger and trigger['resume_via'] != 'observed_yield_exit')
                        or actor not in actors or witness not in actors or actor == witness
                        or parent.get('method') != 'run_activity'
                        or parent.get('trigger', {}).get('kind') != 'native_local_yield_motion'
                        or parent.get('params', {}).get('actor_id') != actor
                        or parent.get('trigger', {}).get('witness_actor_id') != witness
                        or len(parent_steps) != 1 or parent_steps[0].get('action') != 'wait'):
                    raise ValueError('activity success requires an earlier same-actor yield wait and the same witness')
                params = event.get('params', {})
                steps = params.get('steps')
                if (event.get('method') != 'run_activity' or set(params) != {'actor_id', 'steps'}
                        or params['actor_id'] != actor or not isinstance(steps, list) or len(steps) != 1):
                    raise ValueError('activity success followup requires one same-actor move')
                step = steps[0]
                if (not isinstance(step, dict) or set(step) != {'action', 'target', 'timeout_s'}
                        or step.get('action') != 'move_to' or not isinstance(step['target'], list) or len(step['target']) != 3):
                    raise ValueError('activity success followup requires a fixed typed move')
                for value in step['target']: finite(value, 'followup target', -100, 100)
                finite(step['timeout_s'], 'followup timeout', 1, 60)
            elif trigger.get('kind') == 'event_applied':
                if set(trigger) != {'kind', 'event_id', 'delay_s'} or trigger['event_id'] not in previous:
                    raise ValueError('event trigger must refer to an earlier event')
                finite(trigger['delay_s'], 'delay_s', 0, 60)
            else:
                raise ValueError('unknown diagnostic trigger kind')
        previous.add(event['event_id'])
        declarations[event['event_id']] = event
    return count


class NativeReleaseTriggers:
    """Observe real backend callbacks, then resolve a single fault placement."""
    def __init__(self, events, actors):
        validate_triggers(events, set(actors))
        self.events = {e['event_id']: copy.deepcopy(e) for e in events}
        self.tracks, self.first, self.applied_times, self.local_first = {}, {}, {}, {}
        self.applied_activities = {}

    def observe(self, kind, payload, context, cell):
        if kind not in {'traffic_tail_tracking', 'traffic_tail_released', 'traffic_local_yield_motion_observed'}:
            return
        if any(context.get(k) is None for k in FENCES):
            raise ValueError('native trigger context lacks ownership/world fences')
        actor = context['actor_id']
        key = actor, payload['route_id'], payload['native_task_id']
        if kind == 'traffic_local_yield_motion_observed':
            local = context.get('local_yield')
            if (not local or payload['agent'] != context['agent']
                    or context['current_route_id'] != payload['route_id']
                    or context['route_native_task_id'] != payload['native_task_id']
                    or context['sdk_task_id'] != payload['native_task_id']
                    or local['native_task_id'] != payload['native_task_id']
                    or local['body_generation'] != context['body_instance_id']
                    or math.dist(context['position_m'], payload['actual_position_m']) > 1e-5):
                raise ValueError('local yield motion is not the current owned SDK/body sample')
            self.local_first.setdefault(actor, {'fences': {k: context[k] for k in FENCES},
                'route_id': payload['route_id'], 'native_task_id': payload['native_task_id'],
                'observed_sim_time': context['sim_time'], 'position_m': copy.deepcopy(payload['actual_position_m']),
                'points_m': copy.deepcopy(local['path_m'])})
            return
        if kind == 'traffic_tail_tracking':
            points = payload['points_m']
            if (payload.get('eligible') is True and payload.get('diagonal_straight_enabled') is True
                    and all(round(points[0][i]/cell) != round(points[-1][i]/cell) for i in [0, 1])):
                self.tracks[key] = {'fences': {k: context[k] for k in FENCES}, 'points_m': copy.deepcopy(points)}
            return
        track = self.tracks.get(key)
        if track is None:
            return  # An axis release cannot start a diagonal fault experiment.
        if (any(context[k] != track['fences'][k] for k in FENCES)
                or payload['agent'] != context['agent']
                or payload['body_instance_id'] != context['body_instance_id']
                or context['current_route_id'] != payload['route_id']
                or context['route_native_task_id'] != payload['native_task_id']
                or context['sdk_task_id'] != payload['native_task_id']
                or payload['original_points_m'] != track['points_m']):
            raise ValueError('release does not belong to the current actual native task/body')
        self.first.setdefault(actor, {'fences': track['fences'], 'route_id': payload['route_id'],
            'native_task_id': payload['native_task_id'], 'observed_sim_time': context['sim_time'],
            'position_m': copy.deepcopy(payload['position_m']), 'points_m': track['points_m'],
            'removed_cells': copy.deepcopy(payload['removed_cells'])})

    def ready(self, event_id, elapsed, context=None):
        event = self.events[event_id]
        if elapsed < event['at_s']:
            return None
        trigger = event.get('trigger')
        params = copy.deepcopy(event['params'])
        if trigger is None:
            return params, None
        if trigger['kind'] == 'activity_succeeded':
            binding = self.applied_activities.get(trigger['event_id'])
            if trigger['event_id'] not in self.applied_times:return None
            if binding is None:raise ValueError('activity success lacks an actual prerequisite receipt')
            scope = binding['receipt'];original = binding['context']
            if context is None or any(context.get(k) != scope.get(k) for k in FENCES[:6]):
                raise ValueError('activity success prerequisite ownership is stale')
            if any(context.get(k) != original.get(k) for k in ['agent', 'body_instance_id']):
                raise ValueError('activity success prerequisite native body is stale')
            if context.get('task_status') in {'accepted', 'running', 'blocked', 'paused'}:return None
            if context.get('task_status') != 'succeeded' or context.get('cancel_requested') is not False:
                raise ValueError('activity success prerequisite did not succeed')
            observed = context.get('actual_observation', {});speed = observed.get('speed_mps')
            stamp = observed.get('observation_sim_time');now = context.get('sim_time')
            if (observed.get('ready') is not True or observed.get('action') != 'Idle'
                    or type(observed.get('native_task_id')) is not int or type(context.get('sdk_task_id')) is not int
                    or observed.get('native_task_id') != context.get('sdk_task_id')
                    or type(speed) not in (float, int) or not math.isfinite(speed) or not 0 <= speed < .15
                    or type(stamp) not in (float, int) or not math.isfinite(stamp)
                    or type(now) not in (float, int) or not math.isfinite(now) or abs(stamp-now) > 1e-7):return None
            witness = context.get('witness', {});previous_witness = original.get('witness', {})
            if (any(witness.get(k) != previous_witness.get(k) for k in ['actor_id', 'actor_instance_id', 'task_id', 'control_epoch'])
                    or witness.get('actor_id') != trigger['witness_actor_id'] or witness.get('status') not in {'running', 'blocked'}):
                raise ValueError('activity success followup lost its independent witness')
            continuation = None
            if trigger.get('resume_via') == 'observed_yield_exit':
                local = original.get('local_yield', {});path = local.get('path_m')
                if (not isinstance(path, list) or not 2 <= len(path) <= 256
                        or any(not isinstance(point, list) or len(point) != 3
                               or any(type(v) not in (float, int) or not math.isfinite(v) for v in point) for point in path)
                        or local.get('body_generation') != original['body_instance_id']
                        or type(local.get('native_task_id')) is not int or local['native_task_id'] <= 0
                        or local.get('native_task_id') != original.get('sdk_task_id')):
                    raise ValueError('resume waypoint lacks the original observed owned yield exit')
                params['steps'][0]['via'] = [copy.deepcopy(path[-1])]
                continuation = {'kind': 'observed_yield_exit', 'source_yield_path_m': copy.deepcopy(path),
                                'source_yield_native_task_id': local['native_task_id'],
                                'source_body_instance_id': local['body_generation'], 'via': copy.deepcopy(params['steps'][0]['via'])}
            return params, {'kind': 'activity_succeeded', 'predecessor_event_id': trigger['event_id'],
                            'predecessor_receipt': copy.deepcopy(scope), 'current': copy.deepcopy(context),
                            'continuation': continuation}

        if trigger['kind'] == 'event_applied':
            start = self.applied_times.get(trigger['event_id'])
            if start is None or elapsed-start < trigger['delay_s']-1e-9:
                return None
            return params, {'kind': 'event_applied', 'event_id': trigger['event_id'],
                            'actual_event_elapsed_s': start, 'delay_s': trigger['delay_s']}
        release = (self.local_first if trigger['kind'] == 'native_local_yield_motion' else self.first).get(trigger['actor_id'])
        if release is None:
            return None
        if (context is None or any(context.get(k) != release['fences'][k] for k in FENCES)
                or context['current_route_id'] != release['route_id']
                or context['route_native_task_id'] != release['native_task_id']
                or context['sdk_task_id'] != release['native_task_id']):
            raise ValueError('first native fault observation is stale; do not rebind to another task')
        if trigger['kind'] == 'native_local_yield_motion':
            local = context.get('local_yield') or {}
            if (local.get('native_task_id') != release['native_task_id']
                    or local.get('body_generation') != release['fences']['body_instance_id']
                    or local.get('path_m') != release['points_m']
                    or not isinstance(local.get('deadline_sim_time'), (int, float))
                    or not math.isfinite(local['deadline_sim_time'])
                    or not release['observed_sim_time'] <= context['sim_time'] <= local['deadline_sim_time']):
                raise ValueError('first local yield observation is stale or its path/deadline changed')
        if context.get('task_status') not in {'running', 'blocked'} or context.get('cancel_requested') is not False:
            raise ValueError('fault requires a still-active uncancelled lead task')
        witness = context['witness']
        if witness.get('actor_id') != trigger['witness_actor_id'] or witness.get('status') not in {'running', 'blocked'}:
            raise ValueError('fault requires a still-active independent witness')
        proof = {'kind': trigger['kind'], 'release': copy.deepcopy(release),
                 'current': copy.deepcopy(context)}
        if event['method'] == 'move_prop':
            if trigger['kind'] == 'native_local_yield_motion':
                params['position_m'], proof['placement'] = polyline_placement(release['points_m'], context['position_m'], trigger['placement'])
                return params, proof
            a, b = release['points_m'][0], release['points_m'][-1]
            length = math.dist(a[:2], b[:2])
            if length < 4:
                raise ValueError('short observed diagonal path')
            unit = [(b[i]-a[i])/length for i in [0, 1]]
            root = context['position_m']
            progress = sum((root[i]-a[i])*unit[i] for i in [0, 1])
            p = trigger['placement']
            target = min(progress+p['forward_m'], length-p['end_margin_m'])
            if not 0 <= progress < target <= length:
                raise ValueError('no forward placement remains on this actual path')
            params['position_m'] = [a[i]+target*unit[i] for i in [0, 1]]+[p['z_m']]
            proof['placement'] = {'strategy': 'min(progress+forward,length-end_margin)',
                'progress_m': progress, 'length_m': length, 'target_progress_m': target, **p}
        return params, proof

    def applied(self, event_id, elapsed, receipt=None, context=None):
        if event_id in self.applied_times:
            raise ValueError('diagnostic fault already applied')
        needs_receipt = any(e.get('trigger', {}).get('kind') == 'activity_succeeded'
                            and e['trigger']['event_id'] == event_id for e in self.events.values())
        if needs_receipt:
            actor = self.events[event_id]['params']['actor_id']
            if (not isinstance(receipt, dict) or any(receipt.get(k) is None for k in FENCES[:6])
                    or receipt['actor_id'] != actor or receipt.get('status') not in {'accepted', 'running', 'blocked', 'succeeded'}
                    or context is None or any(context.get(k) is None for k in FENCES)
                    or any(receipt[k] != context.get(k) for k in FENCES[:4])
                    or any(context.get('witness', {}).get(k) is None for k in ['actor_id', 'actor_instance_id', 'task_id', 'control_epoch'])
                    or receipt['control_epoch'] <= context['control_epoch']
                    or receipt['task_id'] == context['task_id']):
                raise ValueError('activity success requires the actual newly accepted wait receipt')
            self.applied_activities[event_id] = {'receipt': {k: copy.deepcopy(receipt[k]) for k in FENCES[:6]},
                                                 'context': copy.deepcopy(context)}
        self.applied_times[event_id] = elapsed


def polyline_placement(points, root, placement):
    """One predetermined forward arc-distance placement; no rejected retry."""
    segments = []; total = 0.
    for a, b in zip(points, points[1:]):
        length = math.dist(a[:2], b[:2])
        if length <= 1e-9: continue
        unit = [(b[i]-a[i])/length for i in [0, 1]]
        projected = max(0., min(length, sum((root[i]-a[i])*unit[i] for i in [0, 1])))
        distance = math.hypot(*[root[i]-a[i]-projected*unit[i] for i in [0, 1]])
        segments.append((a, length, unit, total, projected, distance)); total += length
    if total < .5: raise ValueError('short actual local yield path')
    nearest = min(segments, key=lambda s: s[-1]); progress = nearest[3]+nearest[4]
    if nearest[-1] > .35: raise ValueError('actual root is off the local yield path')
    target = min(progress+placement['forward_m'], total-placement['end_margin_m'])
    if not 0 <= progress < target <= total: raise ValueError('no forward placement remains on local yield')
    segment = next(s for s in segments if s[3]+s[1] >= target)
    position = [segment[0][i]+(target-segment[3])*segment[2][i] for i in [0, 1]]+[placement['z_m']]
    return position, {'strategy': 'polyline_arc_min(progress+forward,length-end_margin)',
                      'progress_m': progress, 'length_m': total, 'target_progress_m': target, **placement}
