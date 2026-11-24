"""Bind actual planner telemetry to instant inputs; never invent NavMesh truth."""
import argparse
import importlib.util
import json
import math
from pathlib import Path

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


arrival=load(Path(__file__).with_name('audit_arrival_recovery_prefix.py'),'arrival_diagnostic_dependency')


def check_checks(grid,handle,positions,candidates,checks,selected,goal,origin,blocked,*,goal_mode,dynamic):
    if not isinstance(candidates,list) or not isinstance(checks,list) or len(candidates)>12 or not 0<len(checks)<=len(candidates):
        raise ValueError('candidate/check denominator missing')
    if len({tuple(c['node']) for c in candidates})!=len(candidates):raise ValueError('duplicate candidate')
    anchor=goal if goal_mode else origin;distances=[]
    for candidate in candidates:
        n=tuple(candidate['node']);point=grid.point(n);distances.append(math.dist(point[:2],anchor[:2]))
        if candidate['point_m']!=point or candidate['in_blocked_set'] is not (n in blocked):raise ValueError('candidate geometry or blocked membership differs')
    if any(b<a-1e-7 for a,b in zip(distances,distances[1:])):raise ValueError('candidate distance order changed')
    accepted=None
    for i,check in enumerate(checks):
        n=tuple(check['node']);point=grid.point(n);in_blocked=n in blocked
        if list(n)!=candidates[i]['node'] or check['in_blocked_set'] is not in_blocked:raise ValueError('selection used another candidate')
        required=dynamic if goal_mode else True
        if check['clearance_required'] is not required:raise ValueError('clearance policy changed')
        clearance,connector=check['swept_clearance'],check['connector']
        if in_blocked:
            if clearance is not None or connector is not None:raise ValueError('blocked candidate re-queried')
            expected=False
        else:
            if goal_mode:
                if type(connector) is not bool:raise ValueError('connector result missing')
                clearance_evaluated=connector and dynamic
            else:clearance_evaluated=True
            if clearance_evaluated:
                a,b=(point,goal) if goal_mode else (origin,point)
                actual=grid.can_reserve(handle,grid.sweep(a,b),positions,a,b)
                if type(clearance) is not bool or clearance is not actual:raise ValueError('recorded clearance differs from instant actual inputs')
            elif clearance is not None:raise ValueError('unevaluated clearance disguised as a result')
            if not goal_mode:
                if clearance:
                    if type(connector) is not bool:raise ValueError('required connector result missing')
                elif connector is not None:raise ValueError('connector executed after failed clearance')
            expected=bool(connector and (clearance if required else True))
        if check['accepted'] is not expected:raise ValueError('acceptance does not follow recorded predicates')
        if expected:
            if i!=len(checks)-1:raise ValueError('selection continued after success')
            accepted=list(n)
    if accepted!=selected or accepted is None and len(checks)!=len(candidates):raise ValueError('selection receipt or failed search denominator differs')


def verify_event(event,traffic,dynamic):
    if event.get('capture_error'):raise ValueError('instant planner snapshot unavailable')
    p=event['payload'];a=event['actor'];binding=a['binding'];obs=a['observation'];route=a['route'];inputs=event['planner_inputs']
    if (event['kind']!='traffic_path_search_wait' or p['sample_sim_time']!=event['sim_time']
            or p['body_instance_id']!=binding['traffic_body_instance_id'] or p['agent']!=binding['native_actor_prim_path']
            or p['route_id']!=a['route_id'] or p['route_native_task_id'] is not None
            or p['observed_native_task_id']!=obs['native_task_id'] or p['observed_native_action']!=obs['action']
            or p['observation_sim_time']!=event['sim_time'] or p['origin_m']!=obs['position_m']
            or p['position_source']!='BehaviorAgent.get_world_translation'
            or p['target_m']!=route['goals'][p['goal_index']] or p['goal_index']!=route['goal_index']
            or p['route_requested_sim_time']!=route['requested_sim_time']
            or p['route_status_before_wait']!=route['status']):raise ValueError('planner snapshot scope differs')
    if (p['blocker_ids'] is not None or p['causal_blocker_verified'] is not False
            or p['physical_feasibility_verified'] is not False or p['connection_results_recorded'] is not True):
        raise ValueError('planner telemetry overstates its evidence')
    cell,margin=inputs['cell_m'],inputs['margin_m']
    if not arrival.finite(cell) or cell<=0 or not arrival.finite(margin) or margin<=0:raise ValueError('grid units invalid')
    positions=inputs['positions_m']
    if not positions or any(not arrival.point(pos) for pos in positions.values()) or positions[p['agent']]!=p['origin_m']:
        raise ValueError('instant body inputs missing')
    grid=traffic.ReservationGrid(set(),{},cell_m=cell,margin_m=margin)
    grid.claims={h:{tuple(c) for c in cells} for h,cells in event['claims'].items()}
    blocked=grid.blocked(p['agent'],positions)
    if len(blocked)!=p['blocked_cell_count']:raise ValueError('instant blocked set differs')
    candidate_nodes={tuple(c['node']) for c in [*p['start_candidates'],*(p['goal_candidates'] or [])]}
    if type(p['node_count']) is not int or p['node_count']<len(candidate_nodes):raise ValueError('grid node denominator invalid')
    check_checks(grid,p['agent'],positions,p['start_candidates'],p['start_checks'],p['selected_start'],
                 p['target_m'],p['origin_m'],blocked,goal_mode=False,dynamic=dynamic)
    phase=p['planner_phase']
    if phase=='start_candidate_unavailable':
        if p['selected_start'] is not None or p['goal_candidates'] is not None or p['goal_checks'] is not None or p['selected_goal'] is not None:
            raise ValueError('start failure falsely evaluated the goal')
    else:
        if p['selected_start'] is None:raise ValueError('later phase lacks start')
        check_checks(grid,p['agent'],positions,p['goal_candidates'],p['goal_checks'],p['selected_goal'],
                     p['target_m'],p['origin_m'],blocked,goal_mode=True,dynamic=dynamic)
        if phase=='goal_candidate_unavailable':
            if p['selected_goal'] is not None:raise ValueError('goal failure had a selected goal')
        elif phase in {'grid_path_unavailable','goal_footprint_blocked'}:
            if p['selected_goal'] is None:raise ValueError('grid phase lacks goal')
            if phase=='goal_footprint_blocked':
                overlap=grid.footprint(p['target_m']) & blocked
                if (not overlap or {tuple(c) for c in p['goal_blocked_cells']}!=overlap
                        or p['selected_start']!=p['selected_goal']
                        or math.dist(p['origin_m'][:2],grid.point(tuple(p['selected_start']))[:2])>.35):
                    raise ValueError('same-cell blocked goal condition differs')
        else:raise ValueError('unknown planner phase')
    return {'actor_id':event['actor_id'],'source_tick':event['source_tick'],'sim_time':event['sim_time'],
            'phase':phase,'start_attempts':len(p['start_checks']),
            'goal_attempts':None if p['goal_checks'] is None else len(p['goal_checks']),
            'connector_requery_performed':False,'causal_blocker_verified':False}


def audit(run,source,case,probe,trace,shared):
    result=arrival.audit(run,source,case,probe,trace,shared);folder=Path(run);checked=[];errors=[]
    if result['measurement_verified']:
        try:
            snap=folder/'source_snapshot';traffic=load(snap/'src/simpeople/core/traffic.py','frozen_diag_traffic')
            policy=load(snap/'src/simpeople/core/runtime_policy.py','frozen_diag_policy').DEFAULT_POLICY
            supplied=json.loads((snap/'configs/runtime_policy.json').read_text()) if (snap/'configs/runtime_policy.json').exists() else {}
            dynamic=supplied.get('dynamic_edges_enabled',policy['dynamic_edges_enabled'])
            handles={row['frame_identity']['source_tick']:{b['native_actor_prim_path'] for b in row['body_bindings'].values()}
                     for row in arrival.lines(folder/'arrival_recovery_frames.jsonl')}
            for event in arrival.lines(folder/'arrival_recovery_direct_events.jsonl'):
                if event['kind'].startswith('traffic_path_search_'):
                    if set(event['planner_inputs']['positions_m'])!=handles[event['source_tick']]:raise ValueError('planner inputs belong to another actor set')
                    checked.append(verify_event(event,traffic,dynamic))
        except (ValueError,KeyError,TypeError,IndexError,OSError,AttributeError) as error:errors.append(type(error).__name__+': '+str(error))
    target=[x for x in checked if x['actor_id']=='person_020']
    result.update(planner_diagnostic_errors=errors,planner_events_checked=checked,
                  planner_diagnostics_verified=bool(result['measurement_verified'] and not errors and target),
                  connector_requery_performed=False,causal_blocker_verified=False)
    result['measurement_verified']=bool(result['measurement_verified'] and not errors)
    result['native_local_resume_verified']=bool(result['native_local_resume_verified'] and result['measurement_verified'])
    result['scope']='New-source45s Native resume plus instant-input candidate telemetry. Clearance independently recomputed; NavMesh connector outcomes are source-bound actual telemetry, not independent requery/contact/wholeT2 proof.'
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--source',required=True);p.add_argument('--case',required=True);p.add_argument('--probe',required=True);p.add_argument('--trace',required=True);p.add_argument('--shared',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=audit(a.run,a.source,a.case,a.probe,a.trace,a.shared);Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['measurement_verified','native_local_resume_verified','planner_diagnostics_verified','planner_diagnostic_errors']}))
    raise SystemExit(0 if result['measurement_verified'] and result['planner_diagnostics_verified'] else 2)
