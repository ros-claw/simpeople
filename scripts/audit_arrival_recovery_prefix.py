"""Independent actual-data checks of a45s prefix; never a600s workload grade."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess


def finite(v): return type(v) in (int, float) and math.isfinite(v)
def point(v): return isinstance(v, list) and len(v) == 3 and all(finite(x) for x in v)
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def lines(p): return [json.loads(s) for s in Path(p).open()]


def verify_candidate_snapshot(source_manifest, snapshot_manifest):
    # The original shared driver snapshots src/configs/schemas/capabilities.
    # These three frozen, nonexecuted entry scripts are not used by this probe.
    not_executed = {'scripts/audit_gesture_runtime.py', 'scripts/kit_main.py', 'scripts/probe_gesture_runtime.py'}
    for name, digest in source_manifest.items():
        if name in not_executed and name not in snapshot_manifest: continue
        if snapshot_manifest.get(name) != digest: raise ValueError('candidate execution source changed: '+name)


def check_actor(actor, aid, session, episode):
    b = actor['binding']; o = actor['observation']; t = actor['task']
    if (o.get('ready') is not True or o.get('position_source') != 'BehaviorAgent.get_world_translation'
            or not point(o.get('position_m')) or not finite(o.get('speed_mps')) or o['speed_mps'] < 0
            or b['read_errors']): raise ValueError('actual actor readback unavailable')
    if t and (t['actor_id'] != aid or t['session_id'] != session or t['episode_id'] != episode
              or any(t[k] != b[k] for k in ['task_id', 'actor_instance_id', 'control_epoch'])):
        raise ValueError('actor task/world/generation fence changed')
    route = actor['route']
    if route and route['handle'] != b['native_actor_prim_path']:
        raise ValueError('route belongs to another physical body')


def check_frame(row, stamp, enabled, actors):
    now = row['sim_time']; bindings = row['body_bindings']
    if (row['frame_identity'] != stamp['frame_identity'] or abs(now-stamp['sim_time']) > 1e-7
            or row['arrival_recovery_enabled'] is not enabled or row['timeline_playing'] is not True
            or set(bindings) != actors): raise ValueError('prefix clock/actor set/opt-in differs')
    for b in bindings.values():
        if (b['sdk_enabled'] is not True or b['read_errors'] or b['observation_ready'] is not True
                or not finite(b['observation_sim_time']) or abs(b['observation_sim_time']-now) > 1e-7
                or not point(b['actual_sdk_position_m']) or type(b['actual_sdk_task_id']) is not int
                or b['actual_sdk_task_id'] < 0 or type(b['control_epoch']) is not int or b['control_epoch'] < 0
                or not all(isinstance(b[k], str) and b[k] for k in ['actor_instance_id', 'native_actor_prim_path', 'traffic_body_instance_id'])):
            raise ValueError('body binding is not a fresh actual SDK sample')
    for key in ['actor_instance_id', 'native_actor_prim_path', 'traffic_body_instance_id']:
        if len({b[key] for b in bindings.values()}) != len(actors): raise ValueError('actors share a body or incarnation')
    if not {'person_020', 'person_001'} <= set(row['actors']): raise ValueError('operator/witness absent')
    for aid, a in row['actors'].items():
        if aid not in actors or a['binding'] != bindings[aid]: raise ValueError('selected actor borrowed a binding')
        check_actor(a, aid, row['session_id'], row['episode_id'])
    return {aid: {k: b[k] for k in ['actor_instance_id', 'native_actor_prim_path', 'traffic_body_instance_id']} for aid, b in bindings.items()}


def idle(actor, now, stop_id=None):
    b, o = actor['binding'], actor['observation']; hips = o.get('joints_m', {}).get('Hips')
    basic = (o.get('ready') is True and o.get('observation_sim_time') == now
             and o.get('position_source') == 'BehaviorAgent.get_world_translation' and point(o.get('position_m'))
             and point(b.get('actual_sdk_position_m')) and math.dist(o['position_m'], b['actual_sdk_position_m']) < 1e-5
             and o.get('action') == b.get('actual_sdk_task_name') == 'Idle'
             and o.get('native_task_id') == b.get('actual_sdk_task_id')
             and finite(o.get('speed_mps')) and 0 <= o['speed_mps'] < .15
             and point(hips) and hips[2]-o['position_m'][2] > .75)
    if not basic: return False
    if stop_id is None: return True
    elapsed = actor['native_elapsed_s'].get(str(stop_id))
    return (b['actual_sdk_task_id'] == stop_id and actor['native_status'].get(str(stop_id)) == 'running'
            and finite(elapsed) and elapsed >= 1/30-1e-5)


def verify_window(frames, event, window, aid, retired, stop_id=None):
    end = event['sim_time']; start = window['since']; actor = event['actor']; rid = actor['route_id']
    samples = [(r['sim_time'], r['actors'][aid]) for r in frames if start-1e-7 <= r['sim_time'] < end-1e-7]
    samples.append((end, actor))
    if (len(samples) < 16 or len(samples) != window['count'] or abs(samples[0][0]-start) > 1e-7
            or abs(window['last']-end) > 1e-7 or end-start < .5-1e-7
            or any(abs(b[0]-a[0]-1/30) > 1e-6 for a, b in zip(samples, samples[1:]))):
        raise ValueError('declared confirmation/stop window is not sixteen real30Hz samples')
    identity = [actor['binding']['native_actor_prim_path'], actor['binding']['traffic_body_instance_id'],
                rid, retired, window['identity'][-1]]
    if window['identity'] != identity: raise ValueError('window belongs to another native route/body')
    for now, sample in samples:
        if (not idle(sample, now, stop_id) or sample['route_id'] != rid
                or any(sample['binding'][k] != actor['binding'][k] for k in ['actor_instance_id', 'control_epoch', 'task_id', 'traffic_body_instance_id'])
                or any(sample['task'].get(k) != actor['task'].get(k) for k in
                       ['steps', 'step_index', 'step_requested_sim_time', 'step_deadline_sim_time'])
                or sample['native_status'].get(str(retired)) != 'succeeded'):
            raise ValueError('window borrowed stale, moving, unowned or different SDK state')
        if stop_id is None and math.dist(sample['observation']['position_m'][:2], identity[-1][:2]) <= .3:
            raise ValueError('reported shortfall was already at the submitted segment goal')
    for (ta, a), (tb, b) in zip(samples, samples[1:]):
        if math.dist(a['observation']['position_m'], b['observation']['position_m'])/(tb-ta) >= .15+1e-6:
            raise ValueError('declared stationary window has actual root motion')
    return samples


def footprint(p, cell=1.25, margin=.45):
    return {(x, y) for x in range(math.floor((p[0]-margin)/cell+.5), math.floor((p[0]+margin)/cell+.5)+1)
                   for y in range(math.floor((p[1]-margin)/cell+.5), math.floor((p[1]+margin)/cell+.5)+1)}


def movement(frames, aid, command_ids, rid=None, task_id=None, origin=None, required_name=None):
    rows = []
    for r in frames:
        a = r['actors'].get(aid)
        if not a: continue
        b, o = a['binding'], a['observation']; tid = b['actual_sdk_task_id']
        elapsed = a['native_elapsed_s'].get(str(tid))
        if (tid in command_ids and b['actual_sdk_task_name'] in {'MoveTo', 'MoveAlong'}
                and (required_name is None or b['actual_sdk_task_name'] == required_name)
                and o['native_task_id'] == tid and finite(elapsed) and elapsed >= 1/30-1e-5
                and math.dist(o['position_m'], b['actual_sdk_position_m']) < 1e-5
                and (rid is None or a['route_id'] == rid) and (task_id is None or b['task_id'] == task_id)):
            rows.append((r['sim_time'], a))
    if not rows: return {'actual_movement_samples': 0, 'max_displacement_m': 0, 'moving_streak_s': 0, 'foot_variation_proxy_m': 0}
    origin = origin or rows[0][1]['observation']['position_m']; longest = streak = 0.; feet = []
    for (t0, a), (t1, b) in zip(rows, rows[1:]):
        delta = t1-t0; distance = math.dist(a['observation']['position_m'][:2], b['observation']['position_m'][:2])
        streak = streak+delta if abs(delta-1/30) < 1e-6 and distance/delta >= .15 else 0.
        longest = max(longest, streak)
    for _, a in rows:
        o = a['observation']; f = o.get('facing_direction'); p = o['position_m']; j = o.get('joints_m', {})
        if not point(f) or not all(point(j.get(k)) for k in ['LeftFoot', 'RightFoot']): continue
        yaw = math.atan2(f[1], f[0]); c, s = math.cos(yaw), math.sin(yaw)
        feet.append([[c*(j[k][0]-p[0])+s*(j[k][1]-p[1]), -s*(j[k][0]-p[0])+c*(j[k][1]-p[1]), j[k][2]-p[2]] for k in ['LeftFoot', 'RightFoot']])
    variation = max((math.dist(v[i], feet[0][i]) for v in feet for i in [0, 1]), default=0.)
    return {'actual_movement_samples': len(rows), 'max_displacement_m': max(math.dist(a['observation']['position_m'][:2], origin[:2]) for _, a in rows),
            'moving_streak_s': longest, 'foot_variation_proxy_m': variation}


def resume_criteria(metrics):
    return metrics['max_displacement_m'] >= 1 and metrics['moving_streak_s'] >= .5-1e-7 and metrics['foot_variation_proxy_m'] >= .02


def audit(folder, source, case_path, probe_path, trace_path, shared):
    folder, source, case_path = Path(folder), Path(source), Path(case_path)
    errors = []; verified_frames = 0; repairs = []; counterexamples = []; result = {}
    try:
        read = lambda name: json.loads((folder/name).read_text())
        done = read('completed.json'); config = read('arrival_prefix_config.json'); case = json.loads(case_path.read_text())
        if (done['harness_completed'] is not True or not done['diagnostic_prefix'] or done['functional_expected_matched'] is not None
                or done['frames'] != 1350 or abs(done['duration_s']-45) > 1e-5 or config['duration_s'] != 45
                or config['original_case_duration_s'] != 600 or case['duration_s'] != 600): raise ValueError('not a closed45s1350frame diagnostic')
        if (read('workload.json') != case or read('source_snapshot/harness/case.json') != case
                or config['case_input_sha256'] != sha(case_path) or len(case['actors']) != 30 or len(case['requests']) != 60):
            raise ValueError('original600s fixture/workload changed')
        enabled = config['enabled']; bootstrap = read('bootstrap.json')
        if type(enabled) is not bool or (bootstrap['arrival_recovery'] == 'on') != enabled or done['arrival_recovery_enabled'] is not enabled:
            raise ValueError('opt-in differs from actual launch and recording')
        manifest = read('source_manifest.json'); snap = folder/'source_snapshot'
        if (manifest.get(Path(probe_path).name) != sha(probe_path)
                or manifest.get('harness/arrival_prefix_trace.py') != sha(trace_path)):
            raise ValueError('actual probe/observer differs from frozen launch inputs')
        for name, digest in manifest.items():
            if not (snap/name).resolve().is_relative_to(snap.resolve()) or sha(snap/name) != digest: raise ValueError('snapshot source changed')
        verify_candidate_snapshot(json.loads((source/'source_manifest.json').read_text()), manifest)
        shared = Path(shared); binding = json.loads((shared/'workspace_binding.json').read_text())
        if sha(shared/'workspace_binding.json') != 'e99bd9ee80dfce12338c3bbc951b868e913d2919809d27ed15778c8aed10ee40' or sha(shared/'source_manifest.json') != binding['source_manifest_sha256']:
            raise ValueError('shared workload driver source differs')
        shared_manifest = json.loads((shared/'source_manifest.json').read_text())
        for name in ['src/simpeople/core/workloads.py', 'src/simpeople/tools/runtime_contract.py',
                     'src/simpeople/backends/native/probe_scenes.py', 'src/simpeople/backends/native/idle_profile.py', 'src/simpeople/core/release_scene.py']:
            if manifest.get('harness/'+Path(name).name) != shared_manifest[name]: raise ValueError('borrowed helper changed')
        idle_settings = read('sdk_idle_settings.json')
        if (idle_settings['active_tags'] != ['Idle', 'IdleCautious', 'IdleGroove', 'IdleTaunt', 'IdleTilt', 'IdleTired', 'IdleTough']
                or abs(idle_settings['agent_response_time_s']-1/30) > 1e-8 or idle_settings['agent_response_max_random_offset_s'] != 0
                or idle_settings['nav_blocked_timeout_s'] != 3 or idle_settings['requested_api_seed'] != 17):
            raise ValueError('Native startup differs from frozen baseline settings')
        capture = lines(folder/'video_timestamps.jsonl'); frames = lines(folder/'arrival_recovery_frames.jsonl')
        recording = read('recording_metrics.json'); trace_metrics = read('arrival_trace_metrics.json')
        if (len(capture) != len(frames) or len(frames) != 1350 or recording['frames_written'] != 1350
                or recording['empty_rgb_frames'] or recording['dropped_frames'] or trace_metrics['frames'] != 1350 or trace_metrics['read_errors']):
            raise ValueError('RGB or direct SDK evidence incomplete')
        accepted = {}; cutoff = read('benchmark_done.json')['event_cursor']
        events = [e for e in lines(folder/'events.jsonl') if e['cursor'] <= cutoff]
        expected_requests = {'bench-'+hashlib.sha256((case['case_id']+':'+r['request_case_id']).encode()).hexdigest(): r for r in case['requests']}
        for e in events:
            if e['kind'] == 'task_accepted':
                t = e['task']; request = expected_requests[t['request_id']]
                if t['actor_id'] != request['actor_id'] or t['steps'] != request['steps']:
                    raise ValueError('accepted activity differs from the original frozen request')
                accepted[t['task_id']] = t
        expected = {a['actor_id'] for a in case['actors']}; bindings = None; world = None; journal = {}
        for i, (row, stamp) in enumerate(zip(frames, capture)):
            if (stamp['frame'] != i or stamp['frame_identity']['source_tick'] != i
                    or i and abs(row['sim_time']-frames[i-1]['sim_time']-1/30) > 1e-6): raise ValueError('frame clock changed')
            current = check_frame(row, stamp, enabled, expected)
            if bindings is None: bindings = current; world = (row['session_id'], row['episode_id'])
            if current != bindings or world != (row['session_id'], row['episode_id']): raise ValueError('world/body recreated')
            for aid, b in row['body_bindings'].items():
                if b['task_id']:
                    t = accepted[b['task_id']]
                    if any(t[k] != b[k] for k in ['actor_instance_id', 'control_epoch']) or t['actor_id'] != aid: raise ValueError('activity scope changed')
            journal[i] = row; verified_frames += 1
        seen = set()
        for row in lines(folder/'trajectories.jsonl'):
            if row['frame_identity']['source_tick'] >= 1350: continue
            frame = journal[row['frame_identity']['source_tick']]; aid = row['actor_id']; b = frame['body_bindings'][aid]
            key = (row['frame_identity']['source_tick'], aid)
            if key in seen: raise ValueError('duplicate actual journal sample')
            seen.add(key)
            if (abs(row['sim_time']-frame['sim_time']) > 1e-7 or any(row[k] != b[k] for k in ['actor_instance_id', 'control_epoch', 'task_id', 'native_actor_prim_path', 'traffic_body_instance_id'])):
                raise ValueError('independent Native journal does not match observer')
            a = frame['actors'].get(aid)
            if a and any(row[k] != v for k, v in a['observation'].items()): raise ValueError('observer borrowed another actual sample')
        if len(seen) != 1350*30: raise ValueError('actual journal actor/frame denominator incomplete')
        direct = lines(folder/'arrival_recovery_direct_events.jsonl'); by_cursor = {e['cursor']: e for e in events}
        for event in direct:
            if event.get('capture_error'): raise ValueError('critical SDK event read failed')
            logged = by_cursor[event['event_cursor_after']]; tick = event['source_tick']; row = frames[tick]
            if (logged['kind'] != event['kind'] or logged.get('route_id') != event['payload']['route_id']
                    or abs(logged['sim_time']-event['sim_time']) > 1e-7 or abs(row['sim_time']-event['sim_time']) > 1e-7
                    or (event['session_id'], event['episode_id']) != world): raise ValueError('direct event differs from original runtime event')
            check_actor(event['actor'], event['actor_id'], *world)
            actual_binding = event['actor']['binding']; expected_binding = row['body_bindings'][event['actor_id']]
            if any(actual_binding[k] != expected_binding[k] for k in ['actor_instance_id', 'native_actor_prim_path', 'traffic_body_instance_id']):
                raise ValueError('critical event borrowed another body')
            if any(logged.get(k) != v for k, v in event['payload'].items()): raise ValueError('observer changed the forwarded event')
        if not enabled and direct: raise ValueError('disabled profile issued recovery events')
        starts = [e for e in direct if e['actor_id'] == 'person_020' and e['kind'] == 'traffic_arrival_shortfall']
        for start in starts:
            p = start['payload']; rid = p['route_id']; retired = p['identity'][3]; handle = p['agent']
            verify_window(frames, start, p['confirmation_window'], 'person_020', retired)
            task = start['actor']['task']; step = task['steps'][task['step_index']]
            if step['action'] != 'move_to' or step['timeout_s'] != 240: raise ValueError('repair changed original step budget')
            if abs(task['step_deadline_sim_time']-task['step_requested_sim_time']-240) > 1e-6: raise ValueError('original deadline extended')
            later = [e for e in direct if e['payload'].get('route_id') == rid and e['sim_time'] >= start['sim_time']]
            ready = next((e for e in later if e['kind'] == 'traffic_arrival_replan_ready' and e['payload']['retired_native_task_id'] == retired), None)
            if not ready: continue
            stop_id = ready['payload']['idle_native_task_id']; stop = next(e for e in later if e['kind'] == 'traffic_arrival_stop_requested' and e['payload']['idle_native_task_id'] == stop_id)
            if stop_id <= 0 or stop_id == retired or stop['sim_time'] < start['sim_time']: raise ValueError('owned stop receipt invalid')
            verify_window(frames, ready, ready['payload']['stop_window'], 'person_020', retired, stop_id)
            before = {tuple(c) for c in start['claims'].get(handle, [])}
            for row in frames:
                if start['sim_time']-1e-7 <= row['sim_time'] < ready['sim_time']-1e-7:
                    if {tuple(c) for c in row['claims'].get(handle, [])} != before: raise ValueError('claim released before actual stop')
            after = {tuple(c) for c in ready['claims'].get(handle, [])}; retained = before & footprint(ready['actor']['observation']['position_m'])
            if after != retained or {tuple(c) for c in ready['payload']['released_cells']} != before-after: raise ValueError('future/body claim trim differs')
            if (ready['actor']['task']['task_id'] != task['task_id'] or ready['actor']['task']['step_deadline_sim_time'] != task['step_deadline_sim_time']
                    or ready['payload']['original_goals_m'] != p['original_goals_m']): raise ValueError('recovery replaced task/goal/deadline')
            cmds = [e for e in events if e['kind'] == 'traffic_native_started' and e.get('route_id') == rid and e['sim_time'] > ready['sim_time']]
            if any(e['action'] != 'move_to' for e in cmds): raise ValueError('failed multi-waypoint mode repeated')
            metrics = movement(frames, 'person_020', {e['native_task_id'] for e in cmds}, rid, task['task_id'], ready['actor']['observation']['position_m'], 'MoveTo')
            repairs.append({'route_id': rid, 'task_id': task['task_id'], 'retired_native_task_id': retired, 'idle_native_task_id': stop_id,
                            'stop_window_verified': True, 'original_deadline_preserved': True, **metrics})
        if not enabled:
            for row in frames:
                a = row['actors']['person_020']; job = a['route']
                if (job and type(job['native_task_id']) is int and a['native_status'].get(str(job['native_task_id'])) == 'succeeded'
                        and point(job['segment_goal']) and math.dist(a['observation']['position_m'][:2], job['segment_goal'][:2]) > .3 and idle(a, row['sim_time'])):
                    counterexamples.append({'sim_time': row['sim_time'], 'route_id': a['route_id'], 'native_task_id': job['native_task_id']})
        off_span = span = 0.
        for a, b in zip(counterexamples, counterexamples[1:]):
            delta = b['sim_time']-a['sim_time']
            span = span+delta if abs(delta-1/30) < 1e-6 and a['route_id'] == b['route_id'] and a['native_task_id'] == b['native_task_id'] else 0.
            off_span = max(off_span, span)
        witness_prim = frames[0]['body_bindings']['person_001']['native_actor_prim_path']
        witness_routes = {e['route_id'] for e in events if e['kind'] == 'traffic_route_started' and e['agent'] == witness_prim}
        witness_cmds = {e['native_task_id'] for e in events if e['kind'] == 'traffic_native_started' and e['route_id'] in witness_routes}
        witness = movement(frames, 'person_001', witness_cmds)
        final = frames[-1]['actors']; healthy = lambda aid: final[aid]['task'] and final[aid]['task']['status'] in {'running', 'blocked', 'succeeded'}
        resumed = any(resume_criteria(r) for r in repairs)
        video = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_frames',
            '-show_entries', 'frame=best_effort_timestamp_time:stream=width,height,nb_read_frames,avg_frame_rate,duration',
            '-of', 'json', str(folder/'raw_video.mp4')], capture_output=True, text=True, check=True, timeout=120)
        decoded = json.loads(video.stdout); stream = decoded['streams'][0]; pts = [float(f['best_effort_timestamp_time']) for f in decoded['frames']]
        if (int(stream['nb_read_frames']) != 1350 or len(pts) != 1350 or stream['width'] != 1920 or stream['height'] != 1080
                or stream['avg_frame_rate'] != '30/1' or abs(float(stream['duration'])-45) > 1e-6
                or abs(pts[0]) > 1e-7 or any(abs(b-a-1/30) > 1e-6 for a, b in zip(pts, pts[1:]))):
            raise ValueError('decoded video frame/PTS contract changed')
        result = {'enabled': enabled, 'actual_shortfall_confirmations': len(starts), 'off_shortfall_samples': len(counterexamples),
                  'off_shortfall_continuous_s': off_span, 'off_counterexample_verified': not enabled and off_span >= .5-1e-7,
                  'repairs': repairs, 'witness': witness, 'original_operator_activity_status': final['person_020']['task']['status'],
                  'local_resume_verified': bool(enabled and resumed and witness['max_displacement_m'] >= 1 and healthy('person_020') and healthy('person_001')),
                  'decoded_frames': len(pts), 'inputs_sha256': {name: sha(folder/name) for name in
                    ['source_manifest.json', 'arrival_recovery_frames.jsonl', 'arrival_recovery_direct_events.jsonl',
                     'video_timestamps.jsonl', 'recording_metrics.json', 'raw_video.mp4', 'events.jsonl', 'trajectories.jsonl']}}
    except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration, ZeroDivisionError, subprocess.SubprocessError) as error:
        errors.append(type(error).__name__+': '+str(error))
    return {'run_id': folder.name, 'measurement_verified': not errors and verified_frames == 1350,
            'verified_frames': verified_frames, 'errors': errors,
            'native_local_resume_verified': bool(not errors and result.get('local_resume_verified')), 'result': result,
            'full_project_release_verified': False, 'qualified_generated_native_rigs': [],
            'scope': 'Actual45s1350RGB local Native stop/replan/resume with body/task/SDK/claim fences. Original600s workload unchanged and NOTgraded. No namedMoveWalk/contact/wholeT2/gesture/generatedrig qualification.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('run'); p.add_argument('--source', required=True); p.add_argument('--case', required=True); p.add_argument('--output', required=True)
    p.add_argument('--probe', required=True); p.add_argument('--trace', required=True); p.add_argument('--shared', required=True)
    args = p.parse_args(); result = audit(args.run, args.source, args.case, args.probe, args.trace, args.shared)
    Path(args.output).write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: result[k] for k in ['run_id', 'measurement_verified', 'native_local_resume_verified', 'errors']}))
    raise SystemExit(0 if result['measurement_verified'] else 2)
