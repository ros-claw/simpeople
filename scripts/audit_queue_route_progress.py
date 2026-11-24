"""Read-only root-motion diagnostics for a closed queue timeout.

Moving away from a goal can be necessary to avoid obstacles. These measurements
do not establish that a detour was unnecessary or that an arbiter was unfair.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def point(value):
    return isinstance(value, list) and len(value) == 3 and all(number(v) for v in value)


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def motion(rows, goal):
    if (goal is not None and not point(goal)) or len(rows) < 2:
        raise ValueError('finite optional goal and at least two actual rows required')
    if any(not point(r.get('position_m')) or not number(r.get('sim_time')) for r in rows):
        raise ValueError('invalid actual root/time')
    path = moving = stationary = toward = away = longest = current_stop = 0.
    for a, b in zip(rows, rows[1:]):
        delta = b['sim_time'] - a['sim_time']
        if abs(delta - 1/30) > 1e-6:
            raise ValueError('actual body samples are not continuous30Hz')
        distance = math.dist(a['position_m'][:2], b['position_m'][:2])
        path += distance
        if distance / delta >= .15:
            moving += delta; current_stop = 0
        else:
            stationary += delta; current_stop += delta; longest = max(longest, current_stop)
        if goal is not None:
            progress = math.dist(a['position_m'][:2], goal[:2]) - math.dist(b['position_m'][:2], goal[:2])
            toward += max(0., progress); away += max(0., -progress)
    return {'duration_s': rows[-1]['sim_time'] - rows[0]['sim_time'],
            'actual_samples': len(rows), 'horizontal_path_m': path,
            'horizontal_moving_s': moving, 'horizontal_stationary_s': stationary,
            'longest_horizontal_stationary_s': longest,
            'straight_displacement_m': math.dist(rows[0]['position_m'][:2], rows[-1]['position_m'][:2]),
            'initial_distance_to_goal_m': math.dist(rows[0]['position_m'][:2], goal[:2]) if goal is not None else None,
            'final_distance_to_goal_m': math.dist(rows[-1]['position_m'][:2], goal[:2]) if goal is not None else None,
            'euclidean_toward_goal_m': toward if goal is not None else None,
            'euclidean_away_from_goal_m': away if goal is not None else None}


def review(task, events, rows):
    actor, episode = task['actor_id'], task['episode_id']
    start, end = task['step_started'], task['finished_sim_time']
    step = task['steps'][task['step_index']]
    if (task['status'] != 'failed' or not isinstance(task.get('error'), dict) or task['error'].get('code') != 'TIMEOUT'
            or step['action'] != 'queue' or not number(start) or not number(end) or end <= start):
        raise ValueError('a closed failed queue TIMEOUT is required')
    events = [e for e in events if e.get('episode_id') == episode and (
        start-1e-7 <= e['sim_time'] <= end+1e-7 or e.get('kind') == 'tool_result' and e.get('method') == 'spawn')]
    bindings = [e['result'] for e in events if e.get('kind') == 'tool_result' and e.get('method') == 'spawn'
                and e.get('result', {}).get('actor_id') == actor]
    if len(bindings) != 1:
        raise ValueError('single actual spawn binding required; recreation is not inferred')
    if bindings[0].get('backend') != 'native' or bindings[0].get('episode_id') != episode:
        raise ValueError('spawn is not from the same Native episode')
    agent = bindings[0]['prim_path']
    ended = [e for e in events if e['kind'] == 'task_ended' and e['task']['task_id'] == task['task_id']]
    if (len(ended) != 1 or ended[0]['task']['status'] != 'failed'
            or ended[0]['task']['error'] != task['error'] or abs(ended[0]['sim_time']-end) > 1e-7):
        raise ValueError('stored timeout differs from actual terminal event')
    if any(ended[0]['task'].get(k)!=task.get(k) for k in ['actor_id','episode_id','task_id','control_epoch','steps',
            'step_started','finished_sim_time','step_index','step_phase','service_started','queue_egress_target']):
        raise ValueError('terminal phase/owner/budget differs from stored task')
    if 'duration_s' in step and (not number(step['duration_s']) or step['duration_s']<=0):
        raise ValueError('invalid requested service duration')
    samples = sorted([r for r in rows if r['actor_id'] == actor and start-1e-7 <= r['sim_time'] <= end+1e-7], key=lambda r:r['sim_time'])
    for row in samples:
        if (not point(row.get('position_m')) or not number(row.get('sim_time'))
                or not number(row.get('observation_sim_time')) or abs(row['observation_sim_time']-row['sim_time']) > 1e-7
                or row.get('ready') is not True
                or row.get('position_source') != 'BehaviorAgent.get_world_translation'
                or any(row.get(k) != task[k] for k in ['actor_id', 'episode_id', 'task_id', 'control_epoch'])):
            raise ValueError('root sample is stale, nonfinite or from another logical owner')
    if not samples or abs(samples[0]['sim_time']-start) > 1e-7 or abs(samples[-1]['sim_time']-end) > 1e-7:
        raise ValueError('queue step boundary body samples missing')
    slots = [e for e in events if e['kind'] == 'queue_slot_assigned' and e['actor_id'] == actor and e['queue'] == step['target']]
    slots.sort(key=lambda e:e['sim_time'])
    if any(not point(e['target']) for e in slots):
        raise ValueError('invalid actual queue slot targets')
    routes = [e for e in events if e['kind'] == 'traffic_route_started' and e['agent'] == agent]
    ids = {e['route_id'] for e in routes}
    if len(ids) != len(routes):
        raise ValueError('distinct actual actor routes required')
    if routes and not slots:
        raise ValueError('actor routes lack their actual queue slot assignment')
    commands = [e for e in events if e['kind'] == 'traffic_native_started' and e['route_id'] in ids]
    open_waits, waits, censored = {}, [], []
    for event in sorted(events, key=lambda e:e['cursor']):
        route_id = event.get('route_id')
        if route_id not in ids:continue
        if event['kind'] == 'traffic_wait_started':
            if route_id in open_waits:raise ValueError('duplicate traffic wait start')
            open_waits[route_id] = event['sim_time']
        elif event['kind'] == 'traffic_wait_ended':
            began = open_waits.pop(route_id, None)
            declared = event.get('wait_sim_s')
            if (began is None or not number(declared) or declared < 0
                    or abs(event['sim_time']-began-declared) > 1e-6):
                raise ValueError('logged traffic wait lacks matching start/clock duration')
            waits.append({'route_id':route_id,'start_sim_time':began,'end_sim_time':event['sim_time'],
                          'wait_s':event['sim_time']-began})
        elif event['kind'] in {'traffic_route_ended','traffic_route_cancelled'} and route_id in open_waits:
            began = open_waits.pop(route_id)
            censored.append({'route_id':route_id,'start_sim_time':began,'end_sim_time':event['sim_time'],
                             'wait_lower_bound_s':event['sim_time']-began,'reason':event['kind']})
    censored.extend({'route_id':key,'start_sim_time':began,'end_sim_time':end,
                     'wait_lower_bound_s':end-began,'reason':'task_timeout'} for key,began in open_waits.items())
    service = task.get('service_started')
    egress = task.get('queue_egress_target')
    phase = task.get('step_phase')
    if service is not None and (not number(service) or not start <= service <= end):
        raise ValueError('invalid last service boundary')
    if phase in {'queue_waiting','queue_admission'} and service is not None:
        raise ValueError('earlier service history is ambiguous after a return to waiting')
    if phase == 'serving' and service is None:
        raise ValueError('serving phase lacks actual service start')
    if service is not None and not slots:
        raise ValueError('service has no actual queue slot')
    exits = [e for e in routes if e.get('goals_m') == [egress]] if point(egress) else []
    if egress is not None and (not point(egress) or service is None or len(exits)!=1 or exits[0]['sim_time']<service):
        raise ValueError('actual service and egress boundaries required')
    if phase == 'queue_egress' and egress is None:
        raise ValueError('egress phase lacks actual exit target')
    exit_time = exits[0]['sim_time'] if exits else None
    boundaries = []
    if not slots:
        boundaries.append(('admission_or_unassigned',start,end,None))
    elif slots[0]['sim_time'] > start+1e-7:
        boundaries.append(('admission', start, slots[0]['sim_time'], slots[0]['target']))
    for i, slot in enumerate(slots):
        finish = slots[i+1]['sim_time'] if i+1 < len(slots) else service if service is not None else end
        if finish < slot['sim_time']:
            raise ValueError('queue slot order disagrees with service')
        if finish > slot['sim_time']:
            boundaries.append((f'slot_{slot["index"]}_approach', slot['sim_time'], finish, slot['target']))
    if service is not None:
        boundaries.append(('service',service,exit_time if exit_time is not None else end,slots[-1]['target']))
    if exit_time is not None:
        boundaries.append(('egress',exit_time,end,egress))
    phases = []
    for name, begin, finish, goal in boundaries:
        selected = [r for r in samples if begin-1e-7 <= r['sim_time'] <= finish+1e-7]
        if not selected or abs(selected[0]['sim_time']-begin) > 1e-7 or abs(selected[-1]['sim_time']-finish) > 1e-7:
            raise ValueError('phase boundary actual sample missing')
        if finish == begin:
            continue
        phases.append({'phase': name, 'start_sim_time': begin, 'end_sim_time': finish,
                       'goal_m': goal, **motion(selected, goal)})
    metric_goal = egress if egress is not None else slots[-1]['target'] if slots else None
    total = motion(samples, metric_goal)
    if abs(sum(p['duration_s'] for p in phases)-total['duration_s']) > 1e-6:
        raise ValueError('phase time conservation failed')
    command_rows = []
    for command in commands:
        row = next((r for r in samples if abs(r['sim_time']-command['sim_time']) < 1e-7), None)
        route = next(r for r in routes if r['route_id'] == command['route_id'])
        goal = route['goals_m'][-1]
        destination = command.get('target_m') or command.get('points_m', [None])[-1]
        if row is None or not point(goal) or not point(destination) or type(command.get('native_task_id')) is not int:
            raise ValueError('SDK movement command lacks its actual same-tick body or finite target')
        before = math.dist(row['position_m'][:2], goal[:2])
        after = math.dist(destination[:2], goal[:2])
        command_rows.append({'cursor': command['cursor'], 'sim_time': command['sim_time'], 'route_id': command['route_id'],
            'native_task_id': command['native_task_id'], 'actual_position_m': row['position_m'], 'goal_m': goal,
            'destination_m': destination, 'euclidean_goal_distance_change_m': after-before,
            'destination_farther_from_goal': after > before+.01})
    pre_service = [p for p in phases if p['end_sim_time'] <= (service if service is not None else end)+1e-7]
    budget = step.get('timeout_s', 120)
    if not number(budget) or budget <= 0 or not -1e-7 <= end-start-budget <= 1/30+1e-7:
        raise ValueError('timeout is not at the original queue step deadline')
    return {'task_id': task['task_id'], 'actor_id': actor, 'native_agent': agent,
            'original_step_timeout_s': budget, 'original_step_deadline_sim_time': start+budget,
            'terminal_queue_phase':phase,'phases': phases, 'total': total,'metric_goal_m':metric_goal,
            'service_started':service,'unserved_at_timeout':service is None,
            'unserved_request_age_lower_bound_s':end-start if service is None else None,
            'service_elapsed_before_egress_or_timeout_s':(exit_time if exit_time is not None else end)-service if service is not None else None,
            'requested_service_s':step.get('duration_s'),
            'pre_service': {k:sum(p[k] for p in pre_service) for k in ['duration_s', 'horizontal_path_m', 'horizontal_moving_s', 'horizontal_stationary_s']},
            'logged_completed_traffic_wait_s': sum(e['wait_s'] for e in waits),
            'logged_completed_traffic_waits': waits, 'logged_unserved_traffic_waits': censored,
            'native_movement_commands': command_rows,
            'native_command_lineage_exercised':bool(command_rows),
            'commands_farther_from_goal': sum(c['destination_farther_from_goal'] for c in command_rows),
            'scope': 'Actual horizontal roots and logged SDK commands only. Stationary time is not automatically blocked time; '
                     'Euclidean retreat is not proof of an avoidable detour. Legacy actor/task/episode/control bindings '
                     'do not qualify body generation, current reservations, fairness or physical stop. '
                     'Unserved request age includes travel; no assigned target is represented as null, not a guessed goal.'}


def audit_many(folder, task_ids=None):
    """Read a large run once; keep every requested timeout in the denominator."""
    folder = Path(folder); errors=[]; results=[]; hashes={};nominal=None;tasks=[]
    try:
        read=lambda n:json.loads((folder/n).read_text())
        if read('completed.json').get('harness_completed') is not True:
            raise ValueError('Native harness not closed')
        all_tasks=read('tasks.json')
        if task_ids is None:
            tasks=[t for t in all_tasks if t['status']=='failed' and (t.get('error') or {}).get('code')=='TIMEOUT'
                   and t['step_index']<len(t['steps']) and t['steps'][t['step_index']]['action']=='queue']
        else:
            if not task_ids or len(set(task_ids))!=len(task_ids):raise ValueError('distinct requested task IDs required')
            tasks=[next(t for t in all_tasks if t['task_id']==task_id) for task_id in task_ids]
        if not tasks:raise ValueError('no failed queue timeouts exercised')
        cutoff=read('benchmark_done.json')['event_cursor']; events=[]
        wanted={'tool_result','task_ended','queue_slot_assigned','traffic_route_started','traffic_native_started',
                'traffic_wait_started','traffic_wait_ended','traffic_route_ended','traffic_route_cancelled'}
        for line in (folder/'events.jsonl').open():
            event=json.loads(line)
            if event['cursor']<=cutoff and event['kind'] in wanted:
                if event['kind']!='tool_result' or event.get('method')=='spawn':events.append(event)
        rows={t['actor_id']:[] for t in tasks}
        for line in (folder/'trajectories.jsonl').open():
            row=json.loads(line)
            if row['actor_id'] in rows and any(t['actor_id']==row['actor_id'] and t['step_started']-1e-7<=row['sim_time']<=t['finished_sim_time']+1e-7 for t in tasks):
                rows[row['actor_id']].append(row)
        for task in tasks:
            try:
                result=review(task,events,rows[task['actor_id']])
                results.append({'task_id':task['task_id'],'verified':True,'errors':[],'measurement':result})
            except (ValueError,KeyError,TypeError,IndexError) as error:
                results.append({'task_id':task['task_id'],'verified':False,'errors':[str(error)],'measurement':{}})
        for name in ['completed.json','tasks.json','events.jsonl','trajectories.jsonl','benchmark_done.json','source_manifest.json']:
            hashes[name]=sha_file(folder/name)
        if (folder/'outcomes.json').is_file():
            nominal=read('outcomes.json')['denominator'];hashes['outcomes.json']=sha_file(folder/'outcomes.json')
    except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration) as error:
        errors.append(str(error))
    return {'run_id':folder.name,'method_version':'simpeople.failed-queue-root-progress-batch.v2',
            'verified':not errors and bool(results) and all(r['verified'] for r in results),
            'errors':errors,'requested_timeout_tasks':len(tasks),
            'verified_timeout_tasks':sum(r['verified'] for r in results),'results':results,
            'original_nominal_request_denominator':nominal,'inputs_sha256':hashes,'full_release_verified':False,
            'production_source_installed':False,'scope':'Failed queue diagnostic subset only. Neither the subset nor successful measurements establish whole-workload completion or fairness.'}


def audit(folder, task_id):
    batch=audit_many(folder,[task_id]);row=batch['results'][0] if batch['results'] else {}
    return {'run_id':batch['run_id'],'method_version':'simpeople.failed-queue-root-progress.v2',
            'verified':batch['verified'],'errors':batch['errors']+row.get('errors',[]),
            'measurement':row.get('measurement',{}),'inputs_sha256':batch['inputs_sha256'],
            'full_release_verified':False,'production_source_installed':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('run');group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--task-id');group.add_argument('--all-queue-timeouts',action='store_true');p.add_argument('--output',required=True)
    args=p.parse_args();result=audit_many(args.run) if args.all_queue_timeouts else audit(args.run,args.task_id)
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['run_id','verified','errors']}))
    return 0 if result['verified'] else 2


if __name__=='__main__':raise SystemExit(main())
