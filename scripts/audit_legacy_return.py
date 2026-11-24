"""Supplement an existing legacy-clip regression with actual locomotion readback.

MoveTo/MoveAlong are SDK task names, not an assertion about a named animation
clip. Foot motion is a nonstatic-pose proxy; it does not measure contact forces.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def finite(value):
    return type(value) in (float, int) and math.isfinite(value)


def point(value):
    return isinstance(value, list) and len(value) == 3 and all(finite(x) for x in value)


def startup(settings, expected_tags):
    profile = settings['startup_profile']
    if (profile['mode'] != 'default' or profile['original_tags'] != expected_tags
            or profile['active_tags'] != expected_tags or settings['requested_api_seed'] != 42):
        raise ValueError('default Idle menu or requested seed changed')
    prefix = '/exts/omni.anim.behavior.core/'
    for name, expected in [('agentResponseTime', 1/30), ('agentResponseTimeMaxRandomOffset', 0), ('navBlockedTimeout', 3)]:
        value = settings['active_response'][prefix+name]
        if not finite(value) or abs(value-expected) > 1e-8:
            raise ValueError('startup response setting changed')


def measure_return(task, actor, rows, events):
    """Require the same actual body throughout the original post-clip move."""
    aid = actor['actor_id']
    if task['actor_id'] != aid or task['status'] != 'succeeded':
        raise ValueError('successful original actor task required')
    if (any(not isinstance(task.get(k), str) or not task[k]
            for k in ['session_id', 'episode_id', 'actor_instance_id', 'task_id'])
            or type(task.get('control_epoch')) is not int or task['control_epoch'] < 1):
        raise ValueError('original logical owner identity missing')
    if not point(actor.get('move_target_m')):
        raise ValueError('finite original move target required')
    step = task['steps'][1]
    if step != {'action': 'move_to', 'target': actor['move_target_m'], 'gait': 'walk', 'timeout_s': 15}:
        raise ValueError('original return goal or budget changed')
    relevant = [e for e in events if e.get('actor_id') == aid and e.get('task_id') == task['task_id']]
    starts = [e for e in relevant if e['kind'] == 'step_started' and e['index'] == 1]
    ends = [e for e in relevant if e['kind'] == 'step_ended' and e['index'] == 1]
    if len(starts) != 1 or len(ends) != 1 or starts[0]['step'] != step:
        raise ValueError('one original started/ended move required')
    if any(e.get(k) != task[k] for e in starts+ends for k in ['session_id', 'episode_id']):
        raise ValueError('return event belongs to another session/episode')
    begin, end = starts[0]['sim_time'], ends[0]['sim_time']
    if not finite(begin) or not finite(end) or not 0 < end-begin <= 15+1e-7:
        raise ValueError('return did not finish inside its original deadline')
    samples = [r for r in rows if r['actor_id'] == aid and begin-1e-7 <= r['sim_time'] <= end+1e-7]
    # The engine starts the next step one tick after finishing the custom action;
    # sampling occurs after tick, including the exact move completion tick.
    if not samples or abs(samples[0]['sim_time']-begin) > 1e-7 or abs(samples[-1]['sim_time']-end) > 1e-7:
        raise ValueError('return boundary samples missing')
    bodies, prims = set(), set()
    for i, row in enumerate(samples):
        if (row.get('ready') is not True or row.get('position_source') != 'BehaviorAgent.get_world_translation'
                or not point(row.get('position_m')) or not finite(row.get('observation_sim_time'))
                or abs(row['observation_sim_time']-row['sim_time']) > 1e-7
                or any(row.get(k) != task[k] for k in ['session_id', 'episode_id', 'actor_instance_id', 'control_epoch', 'task_id'])):
            raise ValueError('return body observation is stale or has another owner')
        if i and abs(row['sim_time']-samples[i-1]['sim_time']-1/30) > 1e-6:
            raise ValueError('return body stream is not continuous30Hz')
        for name in ['traffic_body_instance_id', 'native_actor_prim_path']:
            if not isinstance(row.get(name), str) or not row[name]:
                raise ValueError('return Native body identity missing')
        bodies.add(row['traffic_body_instance_id']); prims.add(row['native_actor_prim_path'])
    if len(bodies) != 1 or len(prims) != 1:
        raise ValueError('return body recreated')
    routes = {e['route_id'] for e in events if e['kind'] == 'traffic_route_started'
              and e.get('agent') in prims and e.get('session_id') == task['session_id']
              and e.get('episode_id') == task['episode_id'] and begin-1e-7 <= e['sim_time'] <= end+1e-7}
    commands = [e for e in events if e['kind'] == 'traffic_native_started' and e.get('route_id') in routes
                and e.get('session_id') == task['session_id'] and e.get('episode_id') == task['episode_id']
                and begin-1e-7 <= e['sim_time'] <= end+1e-7
                and e.get('action') in {'move_to', 'move_along', 'continuous_corridor'}]
    if any(e['action']=='continuous_corridor' and
           (not isinstance(e.get('points_m'),list) or len(e['points_m'])<2
            or not all(point(p) for p in e['points_m'])) for e in commands):
        raise ValueError('continuous corridor command lacks actual finite route points')
    ids = {e['native_task_id'] for e in commands if type(e.get('native_task_id')) is int}
    clip_ids = {e['native_task_id'] for e in relevant if e['kind'] == 'native_task_bound'
                and type(e.get('native_task_id')) is int and e['sim_time'] < begin-1e-7}
    if not ids or ids & clip_ids:
        raise ValueError('new actual locomotion SDK command required')
    moving, longest, streak, gait_rows = 0., 0., 0., []
    for a, b in zip(samples, samples[1:]):
        dt = b['sim_time']-a['sim_time']
        speed = math.dist(a['position_m'][:2], b['position_m'][:2])/dt
        active = (speed >= .15 and b.get('action') in {'MoveTo', 'MoveAlong'}
                  and type(b.get('native_task_id')) is int and b['native_task_id'] in ids)
        if active:
            moving += dt; streak += dt; gait_rows.append(b)
        else:
            streak = 0.
        longest = max(longest, streak)
    displacement = max(math.dist(samples[0]['position_m'][:2], r['position_m'][:2]) for r in samples)
    if displacement <= 1 or longest < .5-1e-7:
        raise ValueError('measured SDK locomotion participation missing')
    feet = {}
    for foot in ['LeftFoot', 'RightFoot']:
        relative = []
        for row in gait_rows:
            p = row.get('joints_m', {}).get(foot)
            facing = row.get('facing_direction')
            if not point(p) or not point(facing) or math.hypot(*facing[:2]) < .9:
                raise ValueError('actual foot readback missing')
            x, y, z = [p[i]-row['position_m'][i] for i in range(3)]
            length = math.hypot(*facing[:2]); fx, fy = [v/length for v in facing[:2]]
            relative.append([x*fx+y*fy, -x*fy+y*fx, z])
        feet[foot] = max(math.dist(relative[0], p) for p in relative)
    if max(feet.values()) < .04:
        raise ValueError('locomotion body remained a static pose relative to its root')
    settled = []
    for a, b in zip(samples, samples[1:]):
        dt = b['sim_time']-a['sim_time']
        speed = math.dist(a['position_m'][:2], b['position_m'][:2])/dt
        okay = math.dist(b['position_m'][:2], actor['move_target_m'][:2]) <= .3 and speed < .15
        settled.append((dt, okay))
    stopped = 0.
    for dt, okay in reversed(settled):
        if not okay:
            break
        stopped += dt
    if stopped < .5-1e-7:
        raise ValueError('actual arrival not stable for original half-second window')
    return {'actor_id': aid, 'start_sim_time': begin, 'end_sim_time': end,
            'actual_samples': len(samples), 'native_movement_task_ids': sorted(ids),
            'max_displacement_from_move_start_m': displacement, 'moving_sdk_sim_s': moving,
            'longest_continuous_moving_sdk_sim_s': longest, 'final_stationary_window_s': stopped,
            'root_relative_foot_excursion_proxy_m': feet}


def audit(folder, expected_tags, legacy_review_path=None):
    folder = Path(folder); errors = []; results = []; hashes = {}
    try:
        read = lambda name: json.loads((folder/name).read_text())
        prior_path = Path(legacy_review_path) if legacy_review_path else folder/'legacy_regression_independent_review.json'
        prior = json.loads(prior_path.read_text())
        if prior.get('run_id') != folder.name or (prior.get('verified') is not True and not prior.get('coherence')):
            raise ValueError('original independent legacy review must pass first')
        startup(read('sdk_idle_settings.json'), expected_tags)
        tasks = read('legacy_regression_tasks.json'); cast = read('cinematic_cast.json')
        if len(cast) != 8 or len({a['actor_id'] for a in cast}) != 8:
            raise ValueError('eight original actor/clip pairs required')
        events = [json.loads(line) for line in (folder/'events.jsonl').open()]
        rows = [json.loads(line) for line in (folder/'trajectories.jsonl').open()]
        for actor in cast:
            try:
                result = measure_return(tasks[actor['actor_id']], actor, rows, events)
                results.append({'actor_id': actor['actor_id'], 'verified': True, 'measurement': result, 'errors': []})
            except (ValueError, KeyError, TypeError, IndexError) as error:
                results.append({'actor_id': actor['actor_id'], 'verified': False, 'measurement': {}, 'errors': [str(error)]})
        hashes[str(prior_path)] = hashlib.sha256(prior_path.read_bytes()).hexdigest()
        if prior.get('verified') is not True:
            errors.append('legacy clip quality gate remains failed; return measurements cannot qualify it')
        for name in ['sdk_idle_settings.json', 'legacy_regression_tasks.json',
                     'cinematic_cast.json', 'events.jsonl', 'trajectories.jsonl', 'source_manifest.json']:
            digest = hashlib.sha256()
            with (folder/name).open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(block)
            hashes[name] = digest.hexdigest()
    except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
        errors.append(str(error))
    return {'run_id': folder.name, 'verified': not errors and len(results) == 8 and all(r['verified'] for r in results),
            'errors': errors, 'results': results, 'inputs_sha256': hashes, 'production_source_installed': False,
            'scope': 'Supplement original eight-clip review: actual Native locomotion task, new SDK IDs, root travel, '
                     'nonstatic leg proxy and original arrival window. No named MoveWalk animation, force/contact, '
                     'whole-body visual quality, generated rig or gesture catalog qualification.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('run'); p.add_argument('--expected-tags-json', required=True); p.add_argument('--output', required=True); p.add_argument('--legacy-review')
    args = p.parse_args(); result = audit(args.run, json.loads(Path(args.expected_tags_json).read_text()), args.legacy_review)
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'run_id': result['run_id'], 'verified': result['verified'], 'errors': result['errors']}))
    raise SystemExit(0 if result['verified'] else 2)
