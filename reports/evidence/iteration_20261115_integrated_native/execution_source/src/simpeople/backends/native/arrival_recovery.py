"""Opt-in route reconciliation; Native remains the only live pose writer.

This mixin is installed only by the private candidate builder. It does not
change the default adapter, activity deadline, goal or arrival tolerances.
"""
import copy
import math


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def point(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(finite(v) for v in value)


def stationary_window(previous, observation, now, identity):
    """Sixteen fresh 30-Hz Idle samples covering .5 simulation seconds."""
    if (not finite(now) or observation.get('ready') is not True
            or observation.get('position_source') != 'BehaviorAgent.get_world_translation'
            or not finite(observation.get('observation_sim_time'))
            or abs(observation['observation_sim_time'] - now) > 1e-7
            or not point(observation.get('position_m'))
            or not finite(observation.get('speed_mps')) or not 0 <= observation['speed_mps'] < .15
            or observation.get('action') != 'Idle'):
        return None, False
    same = previous and previous['identity'] == identity
    if same and abs(now - previous['last']) < 1e-9:
        return previous, previous['count'] >= 16 and now - previous['since'] >= .5 - 1e-7
    continuous = same and abs(now - previous['last'] - 1 / 30) < 1e-6
    state = {'identity': copy.deepcopy(identity), 'since': previous['since'] if continuous else now,
             'last': now, 'count': previous['count'] + 1 if continuous else 1}
    return state, state['count'] >= 16 and now - state['since'] >= .5 - 1e-7


class ArrivalRecoveryMixin:
    def _arrival_identity(self, handle, rid, job):
        body = self.instances.get(handle, {}).get('traffic_instance_id')
        if (not isinstance(body, str) or not body or self.owner_routes.get(handle) != rid
                or type(job.get('native_task_id')) is not int or job['native_task_id'] <= 0
                or not point(job.get('segment_goal'))):
            return None
        return [handle, body, rid, job['native_task_id'], list(job['segment_goal'])]

    def _arrival_idle_matches(self, handle, obs, expected=None):
        agent = self.agent(handle)
        current = agent.get_action_task_id()
        return (type(current) is int and current == obs.get('native_task_id')
                and (expected is None or current == expected and self.task_state(handle, current) == 'running')
                and agent.get_task_name(current) == 'Idle' and self.is_standing(handle, obs))

    def _arrival_shortfall(self, handle, rid, job, obs):
        if not getattr(self, 'arrival_recovery_probe_enabled', False):
            return False
        self.assert_thread()
        identity = self._arrival_identity(handle, rid, job)
        if not identity or job['phase'] != 'travel' or job['status'] != 'running':
            job.pop('arrival_confirmation', None)
            return False
        try:
            far = point(obs.get('position_m')) and math.dist(obs['position_m'][:2], job['segment_goal'][:2]) > .3
            idle = far and super().task_state(handle, job['native_task_id']) == 'succeeded' and self._arrival_idle_matches(handle, obs)
        except Exception:
            idle = False
        window, confirmed = stationary_window(job.get('arrival_confirmation'), obs, self.now, identity) if idle else (None, False)
        job['arrival_confirmation'] = window
        if not confirmed:
            return False
        # Count anomalous success in the existing finite native retry budget.
        # Do not reset requested_sim_time, goals, step or activity clocks.
        job['retries'] += 1
        job.update(phase='arrival_braking', status='blocked', blocked_since=self.now, retry_at=self.now,
                   arrival_identity=identity, arrival_stop_window=None, arrival_stop_id=None)
        job['blocked_details'] = {'reason': 'native_arrival_shortfall', 'since_sim_time': self.now,
            'retired_native_task_id': job['native_task_id'], 'segment_goal_m': list(job['segment_goal']),
            'actual_position_m': list(obs['position_m']), 'native_retry_count': job['retries'],
            'retry_limit': 3, 'capacity_wait': False}
        self.emit('traffic_arrival_shortfall', route_id=rid, agent=handle, identity=identity,
                  actual_observation=obs, original_goals_m=job['goals'], retry=job['retries'],
                  confirmation_window=window, retained_cells=sorted(self.grid.claims.get(handle, set())))
        self.emit('traffic_wait_started', route_id=rid, agent=handle, blocked_details=job['blocked_details'])
        try:
            # Bypass ReservationNativeBackend.start, which would cancel this
            # route. NativeBackend returns the explicitly owned Idle receipt.
            tid = super().start(handle, {'action': 'settle'})
            if type(tid) is not int or tid <= 0 or tid == identity[3]:
                raise ValueError('new owned Native Idle receipt unavailable')
            job['arrival_stop_id'] = tid
            self.emit('traffic_arrival_stop_requested', route_id=rid, agent=handle,
                      retired_native_task_id=identity[3], idle_native_task_id=tid)
        except Exception as error:
            job['blocked_details']['stop_error'] = str(error)
            self.emit('traffic_arrival_stop_unavailable', route_id=rid, agent=handle, error=str(error))
        return True

    def _tick_arrival_recovery(self, handle, rid, job, obs):
        if job['phase'] != 'arrival_braking' or job['status'] in {'succeeded', 'failed', 'cancelled'}:
            return False
        # An already requested cleanup must settle even if the opt-in flag
        # changes. Cancelled routes are excluded by the caller before here.
        self.assert_thread()
        identity = self._arrival_identity(handle, rid, job)
        matching = identity is not None and identity == job['arrival_identity']
        try:
            matching = matching and job['arrival_stop_id'] is not None and self._arrival_idle_matches(handle, obs, job['arrival_stop_id'])
        except Exception:
            matching = False
        window, settled = stationary_window(job.get('arrival_stop_window'), obs, self.now, identity) if matching else (None, False)
        job['arrival_stop_window'] = window
        if not settled:
            return True
        self.emit('traffic_wait_ended', route_id=rid, wait_sim_s=self.now-job['blocked_since'],
                  reason='native_arrival_shortfall', capacity_wait=False)
        if job['retries'] >= 3:
            self.complete(rid, job, 'failed', {'code': 'NATIVE_ARRIVAL_MISMATCH',
                'message': 'native success did not reach its submitted segment goal',
                'details': {'physical_stop_verified': True, 'native_retry_count': job['retries'],
                            'segment_goal_m': list(job['segment_goal'])}})
            return True
        before = set(self.grid.claims.get(handle, set()))
        # Never invent a fresh reservation during cleanup. Retain any already
        # owned body cells; other actors' actual roots remain clearance inputs.
        retained = before & self.grid.footprint(obs['position_m'])
        if retained:
            self.grid.claims[handle] = retained
        else:
            self.grid.release(handle)
        retired, stop_id = job['native_task_id'], job['arrival_stop_id']
        job.update(native_task_id=None, phase='travel', status='running', blocked_since=None,
                   corridor_candidate=None, continuous_active=False,
                   intent_points=None, arrival_segment_fallback=True,
                   retry_at=self.now+job.get('retry_delay_s', .2), arrival_confirmation=None)
        job.pop('blocked_details', None)
        self.emit('traffic_arrival_replan_ready', route_id=rid, agent=handle,
                  retired_native_task_id=retired, idle_native_task_id=stop_id,
                  stop_window=window, released_cells=sorted(before-retained), retained_cells=sorted(retained),
                  original_goals_m=job['goals'], original_requested_sim_time=job['requested_sim_time'],
                  retry=job['retries'], retry_at_sim_time=job['retry_at'], physical_stop_verified=True,
                  strategy='native_segmented_same_goal')
        return True
