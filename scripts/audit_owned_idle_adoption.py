"""Check observed SDK Idle reuse across two logical owners, without importing Kit.

This grades only the precision entry handoff. A passed handoff does not certify
canonical body entry, generated animation, cancellation, or a supported rig.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

FENCE = ('actor_id', 'actor_instance_id', 'session_id', 'episode_id', 'control_epoch', 'task_id')


def require(value, message):
    if not value:
        raise ValueError(message)


def same_owner(row, task):
    return (row.get('actor_id') == task['actor_id']
            and row.get('actor_instance_id') == task['actor_instance_id']
            and row.get('activity_task_id') == task['task_id']
            and all(row.get('task', {}).get(k) == task.get(k) for k in FENCE))


def actual_idle(row, native):
    observation = row['actual_observation']
    speed, stamp = observation.get('speed_mps'), observation.get('observation_sim_time')
    return (observation.get('ready') is True and observation.get('action') == 'Idle'
            and type(observation.get('native_task_id')) is int and observation['native_task_id'] == native
            and type(speed) in (float, int) and math.isfinite(speed) and 0 <= speed < .15
            and type(stamp) in (float, int) and math.isfinite(stamp) and abs(stamp - row['sim_time']) <= 1e-7)


def review(events, rows, preparation, trajectory):
    result = {'method_version': 'simpeople.observed-owned-idle-reuse.v1', 'verified': False,
              'errors': [], 'generated_motion_verified': False, 'qualified_generated_native_rigs': [],
              'scope': 'Observed reuse of a previously Engine-bound SDK Idle by one new precise-facing task only. No body-entry, generated playback, cancellation or rig qualification.'}
    try:
        task = preparation['task']
        require(task['status'] == 'succeeded', 'precision preparation did not succeed')
        require(task['steps'][0]['action'] == 'look_at' and 'max_angle_deg' in task['steps'][0], 'not an explicit precision task')
        require(task['finished_sim_time'] - task['started_sim_time'] <= min(8, task['steps'][0]['timeout_s']) + 1e-7, 'precision deadline exceeded')
        bindings = [e for e in events if e['kind'] == 'native_task_bound' and e.get('task_id') == task['task_id']]
        require(bool(bindings), 'new logical owner has no SDK binding')
        first = min(bindings, key=lambda e: e['cursor'])
        require(all(first.get(k) == task[k] for k in FENCE), 'new SDK binding has wrong owner')
        native = first['native_task_id']
        require(type(native) is int and native > 0, 'default or invalid SDK ID adopted')
        adopted = [e for e in events if e['kind'] == 'native_idle_adopted_for_precision'
                   and e.get('native_task_id') == native and e['cursor'] < first['cursor']
                   and abs(e['sim_time'] - first['sim_time']) <= 1e-7]
        require(len(adopted) == 1, 'actual adoption trigger missing or ambiguous')
        adopted = adopted[0]
        require(adopted.get('issued_new_sdk_command') is False, 'adoption reported a new SDK command')
        handles = {r.get('native_actor_prim_path') for r in trajectory if r.get('actor_id') == task['actor_id']
                   and r.get('actor_instance_id') == task['actor_instance_id'] and r.get('episode_id') == task['episode_id']
                   and r.get('session_id') == task['session_id'] and abs(r['sim_time'] - adopted['sim_time']) <= 1/30 + 1e-7}
        require(handles == {adopted.get('agent')} and None not in handles, 'adoption event does not name this actual body')
        require(abs(adopted['observation_sim_time'] - adopted['sim_time']) <= 1e-7, 'adoption observation stale')
        prior = [e for e in events if e['kind'] == 'native_task_bound' and e.get('native_task_id') == native
                 and e['cursor'] < adopted['cursor'] and e.get('actor_id') == task['actor_id']
                 and e.get('actor_instance_id') == task['actor_instance_id']
                 and e.get('session_id') == task['session_id'] and e.get('episode_id') == task['episode_id']]
        require(bool(prior), 'adopted SDK task was not previously bound by this body')
        prior = max(prior, key=lambda e: e['cursor'])
        require(prior['task_id'] != task['task_id'] and prior['control_epoch'] < task['control_epoch'], 'logical ownership did not advance')
        ended = [e['task'] for e in events if e['kind'] == 'task_ended' and e['cursor'] < adopted['cursor']
                 and e.get('task', {}).get('task_id') == prior['task_id']]
        require(len(ended) == 1 and ended[0]['status'] in {'succeeded', 'failed', 'cancelled'}, 'old logical owner was not terminal before reuse')
        previous_task = ended[0]
        require(all(prior.get(k) == previous_task.get(k) for k in FENCE), 'old binding and terminal identity differ')
        before = [r for r in rows if same_owner(r, previous_task)
                  and adopted['sim_time'] - 2/30 - 1e-7 <= r['sim_time'] <= adopted['sim_time'] + 1e-7]
        require(bool(before) and actual_idle(max(before, key=lambda r: r['sim_time']), native), 'no recent actual Idle readback for previous owner')
        reuse = sorted([r for r in rows if same_owner(r, task) and r['sim_time'] >= adopted['sim_time'] - 1e-7
                        and r['actual_observation'].get('native_task_id') == native], key=lambda r: r['source_tick'])
        require(len(reuse) >= 2, 'fewer than two actual reused SDK observations')
        a, b = reuse[:2]
        require(abs(a['sim_time'] - adopted['sim_time']) <= 1/30 + 1e-7, 'new owner did not observe adoption promptly')
        require(actual_idle(a, native) and actual_idle(b, native), 'reused SDK readback was not fresh stationary Idle')
        require(b['source_tick'] == a['source_tick'] + 1 and abs(b['sim_time'] - a['sim_time'] - 1/30) <= 1e-7,
                'SDK reuse was not observed on consecutive real frames')
        require(preparation['second_before'] == preparation['second_after'], 'unrelated actor owner changed')
        result.update(verified=True, adopted_native_task_id=native, previous_task_id=prior['task_id'],
                      new_task_id=task['task_id'], first_source_tick=a['source_tick'], second_source_tick=b['source_tick'],
                      observed_reuse_samples=len(reuse), precision_elapsed_sim_s=task['finished_sim_time']-task['started_sim_time'])
    except (ValueError, KeyError, TypeError, IndexError) as error:
        result['errors'].append(str(error))
    return result


def audit(folder):
    folder = Path(folder)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    names = ['source_manifest.json', 'events.jsonl', 'native_pose_history.jsonl', 'public_motion_preparation.json', 'trajectories.jsonl']
    try:
        manifest = json.loads((folder / names[0]).read_text())
        require(isinstance(manifest, dict) and manifest, 'empty snapshot manifest')
        snap = (folder / 'source_snapshot').resolve()
        for name, expected in manifest.items():
            path = (snap / name).resolve()
            require(path.is_relative_to(snap) and path.is_file() and sha(path) == expected, 'frozen source changed: ' + name)
        events = [json.loads(line) for line in (folder / 'events.jsonl').open()]
        rows = [json.loads(line) for line in (folder / 'native_pose_history.jsonl').open()]
        trajectory = [json.loads(line) for line in (folder / 'trajectories.jsonl').open()]
        result = review(events, rows, json.loads((folder / 'public_motion_preparation.json').read_text()), trajectory)
        result.update(run_id=folder.name, inputs_sha256={n: sha(folder/n) for n in names})
        return result
    except (ValueError, OSError, KeyError, TypeError) as error:
        return {'method_version': 'simpeople.observed-owned-idle-reuse.v1', 'verified': False,
                'errors': [str(error)], 'generated_motion_verified': False, 'qualified_generated_native_rigs': []}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    require(not args.output.exists(), 'refusing to replace a previous audit')
    result = audit(args.folder)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['verified'] else 2)
