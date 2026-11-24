"""Review the deliberately failed, single-agent explicit Idle return experiment.

Never converts diagnostic preemption into successful task or rig acceptance.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]/'src'))
import numpy as np
from simpeople.motion.executed_quality import angles, continuous_world_goal, world_goal
from simpeople.motion.rig import validate_poses

FENCES = ('session_id', 'episode_id', 'actor_id', 'actor_instance_id', 'control_epoch', 'task_id')


def readback(rows, anchor, reference, receipt):
    proof = receipt['proof']; errors = []; actor = anchor['actor_id']; clip = proof['clip']
    samples = [r for r in rows if r['actor_id'] == actor]
    active = [r for r in samples if r['actual_observation']['action'] == clip
              and r['actual_observation']['native_task_id'] == proof['native_task_id']
              and r['task']['status'] == 'running' and r['sim_time'] <= proof['ready_sim_time']+1e-7]
    after_command = [r for r in samples if r['phase'] == 'canonical_explicit_idle']
    idle = [r for r in after_command if r['actual_observation']['action'] == 'Idle'
            and r['actual_observation']['native_task_id'] == receipt['idle_native_task_id']]
    if not active or len(after_command) < 75: raise ValueError('actual clip or post-command readback absent')
    if len(idle) < 75: errors.append('fewer than 75 actual explicit Idle samples after SDK command latency')
    before = [r for r in samples if r['source_tick'] == active[0]['source_tick']-1]
    if len(before) != 1: raise ValueError('actual entry seam absent or ambiguous')
    window = [before[0], *active, *after_command]
    for a, b in zip(window, window[1:]):
        if b['source_tick'] != a['source_tick']+1 or abs(b['sim_time']-a['sim_time']-1/30) > 1e-7:
            errors.append('readback not continuous 30Hz'); break
    for row in window:
        if (row['joint_paths'] != anchor['joint_paths'] or row['actor_instance_id'] != anchor['actor_instance_id']
                or any(row['task'].get(k) != anchor['task'].get(k) for k in ['session_id', 'episode_id'])
                or row['actual_observation'].get('ready') is not True
                or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in
                       [row['sim_time'], row['actual_observation']['observation_sim_time'], row['actual_observation']['speed_mps']])
                or abs(row['actual_observation']['observation_sim_time']-row['sim_time']) > 1e-7):
            errors.append('world, layout, actor or observed time changed')
    for row in active:
        if any(row['task'].get(k) != proof['task'].get(k) for k in FENCES) or row['task']['status'] != 'running':
            errors.append('active clip not same owned running task'); break
    for row in after_command:
        pair = row['actual_observation']['action'], row['actual_observation']['native_task_id']
        if (pair not in {(clip, proof['native_task_id']), ('Idle', receipt['idle_native_task_id'])}
                or (idle and row['sim_time'] >= idle[0]['sim_time'] and pair != ('Idle', receipt['idle_native_task_id']))
                or row['task']['status'] != 'failed'
                or any(row['task'].get(k) != proof['task'].get(k) for k in FENCES)):
            errors.append('explicit Idle replaced or logical diagnostic failure lost'); break
    if (active[-1]['source_tick'] != proof['pose_stream_source_tick']
            or abs(active[-1]['sim_time']-proof['ready_sim_time']) > 1e-7
            or active[-1]['world_pose'] != receipt['before']['world_pose']):
        errors.append('handoff not bound to last actual clip sample')
    wanted = world_goal(reference['entry'], reference['goal'], anchor)
    goal = continuous_world_goal(active, wanted)
    if not goal['passed']: errors.append('actual fixed-world goal held for less than 2 seconds')
    pose = validate_poses([r['world_pose'] for r in window], len(anchor['joint_paths']))
    steps_p = np.linalg.norm(pose[1:, :, :3]-pose[:-1, :, :3], axis=-1)
    steps_q = angles(pose[1:, :, 3:], pose[:-1, :, 3:])
    max_p = float(steps_p.max()); max_q = float(steps_q.max())
    if max_p > .02 or max_q > 2: errors.append('actual entry/clip/Idle world continuity exceeds unchanged 2cm/2deg')
    # Independent return recomputation, using the fixed entry, not the observer receipt's error.
    tail = [r for r in active if r['sim_time'] >= active[-1]['sim_time']-.3-1e-7]
    actual = validate_poses([r['world_pose'] for r in tail], len(anchor['joint_paths']))
    entry = validate_poses([anchor['world_pose']], len(anchor['joint_paths']))[0]
    return_p = float(np.linalg.norm(actual[:, :, :3]-entry[:, :3], axis=-1).max())
    return_q = float(angles(actual[:, :, 3:], entry[:, 3:]).max())
    if (len(tail) < 10 or tail[-1]['sim_time']-tail[0]['sim_time'] < .3-1e-7
            or return_p > .02 or return_q > 2 or any(r['actual_observation']['speed_mps'] >= .15 for r in tail)
            or not any(i['passed'] and i['start_sim_time']+i['duration_s'] < tail[0]['sim_time'] for i in goal['matching_intervals'])):
        errors.append('actual return not settled after actual goal')
    return {'errors': errors, 'readback_passed': not errors, 'active_samples': len(active), 'explicit_idle_samples': len(idle),
        'all_actual_joints': len(anchor['joint_paths']), 'max_entry_clip_idle_position_step_m': max_p,
        'max_entry_clip_idle_angle_step_deg': max_q, 'world_goal_hold': goal,
        'return_max_position_error_m': return_p, 'return_max_angle_error_deg': return_q,
        'post_command_samples': len(after_command),
        'command_sim_time': proof['ready_sim_time'],
        'native_Idle_start_sim_time': idle[0]['sim_time'] if idle else None,
        'SDK_command_to_Idle_latency_s': idle[0]['sim_time']-proof['ready_sim_time'] if idle else None,
        'handoff_pair_sim_time': [window[window.index(idle[0])-1]['sim_time'], idle[0]['sim_time']] if idle else [],
        'handoff_pair_pose_stream_ticks': [window[window.index(idle[0])-1]['source_tick'], idle[0]['source_tick']] if idle else []}


def audit(folder):
    folder = Path(folder); read = lambda n: json.loads((folder/n).read_text()); errors = []
    completed = read('completed.json'); receipt = read('return_handoff_receipt.json'); anchor = read('return_anchor.json')
    for name, digest in read('source_manifest.json').items():
        rel = Path(name); p = folder/'source_snapshot'/rel
        if (rel.is_absolute() or '..' in rel.parts or not p.is_file()
                or not p.resolve().is_relative_to((folder/'source_snapshot').resolve())
                or hashlib.sha256(p.read_bytes()).hexdigest() != digest): errors.append('frozen source mismatch: '+name)
    if (not completed.get('harness_completed') or completed.get('functional_expected_matched') is not False
            or completed.get('intentional_diagnostic_preemption') is not True
            or receipt['old_logical_task']['status'] != 'failed'
            or receipt['old_logical_task']['error']['code'] != 'DIAGNOSTIC_PREEMPTED'):
        errors.append('diagnostic incorrectly labelled as successful native task')
    registry = read('source_snapshot/inputs/actions.json'); clip = receipt['proof']['clip']
    reference = registry['canonical_sources'][clip.removeprefix('canonical_')]
    rows = [json.loads(line) for line in (folder/'native_pose_history.jsonl').open()]
    review = readback(rows, anchor, reference, receipt); errors.extend(review['errors'])
    if receipt['old_native_state_after'] not in {'succeeded', 'cancelled', 'failed'}:
        errors.append('preempted native task not actually terminated')
    old = receipt['old_logical_task']; tasks = {t['task_id']: t for t in read('tasks.json')}
    if tasks[old['task_id']]['status'] != 'failed': errors.append('old diagnostic task outcome overwritten')
    walk = receipt['walk_task']; witness = receipt['witness_before']; witness_end = receipt['witness_final']
    if walk['status'] != 'succeeded' or witness_end['status'] != 'succeeded' or witness['status'] not in {'running', 'blocked'}:
        errors.append('walk resume or active witness failed')
    if any(witness.get(k) != witness_end.get(k) for k in FENCES): errors.append('witness replaced')
    roots = []; now = receipt['proof']['ready_sim_time']; idle_end = now+75/30
    for line in (folder/'trajectories.jsonl').open():
        r = json.loads(line)
        if now-1e-7 <= r['sim_time'] <= idle_end+1e-7 and all(r.get(k) == witness.get(k) for k in FENCES):
            roots.append(r)
    if len(roots) < 76 or not all(r.get('ready') for r in roots) or max(
            (math.dist(roots[0]['position_m'], r['position_m']) for r in roots), default=0) <= .3:
        errors.append('same witness actual motion during handoff unverified')
    clock = {}
    for line in (folder/'video_timestamps.jsonl').open():
        r = json.loads(line)
        if any(abs(r['sim_time']-t) < 1e-7 for t in review['handoff_pair_sim_time']):
            clock[r['sim_time']] = {'video_frame_zero_based': r['frame'], 'frame_identity': r['frame_identity']}
    if len(clock) != 2: errors.append('SDK seam lacks exact sim-time RGB frame mapping')
    return {'run_id': folder.name, 'method_version': 'simpeople.native-return-handoff-audit.v2', 'isolated_return_handoff_verified': not errors, 'errors': errors,
        'readback': review, 'actual_sim_time_to_rgb_frame': clock,
        'production_completion_verified': False, 'qualified_generated_native_rigs': [],
        'scope': 'Single Default generated left-low44s preload experiment. Explicit native Idle after measured goal+return. Deliberate logical failure retained; no production custom-action success, natural-tempo, other-goal, female-generated-rig or arbitrary-heading qualification.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('run'); p.add_argument('--output', required=True); a = p.parse_args()
    target = Path(a.output)
    if target.exists(): raise FileExistsError('preserve previous grade')
    result = audit(a.run); target.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: result[k] for k in ['run_id', 'isolated_return_handoff_verified', 'errors', 'production_completion_verified']}))
    raise SystemExit(0 if result['isolated_return_handoff_verified'] else 1)
