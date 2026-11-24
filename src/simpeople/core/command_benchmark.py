"""CommandBench judges native evidence, independently of a host's claims."""
import copy
import json
import math
import random
from collections import Counter


def load_suite(path, schema_path):
    from jsonschema import Draft202012Validator
    suite=json.loads(path.read_text());validator=Draft202012Validator(json.loads(schema_path.read_text()))
    if suite.get('schema_version')!='simpeople.commandbench.v1' or len(suite.get('cases',[]))!=20 or suite.get('repetitions')!=3:
        raise ValueError('the frozen suite requires 20 cases and three independent repetitions')
    ids=[]
    for case in suite['cases']:
        validator.validate(case);ids.append(case['case_id'])
        actors={a['actor_id'] for a in case['fixture']['actors']}
        if actors!={'a','b','c'} or len(actors)!=len(case['fixture']['actors']):raise ValueError('fixture actor IDs must be unique')
        if set(case['targets']) & set(case['preserve']) or set(case['targets']) | set(case['preserve'])!=actors|set(case.get('created_actors',[])):raise ValueError('targets and preserved actors must partition the declared actors')
    if len(set(ids))!=20:raise ValueError('case IDs must be unique')
    if Counter(c['split'] for c in suite['cases'])!={'development':15,'holdout':5}:raise ValueError('15 development and five holdout cases required')
    return suite


def tool_body(item):
    result=item.get('result') or {}
    body=result.get('structured_content') or result.get('structuredContent')
    if isinstance(body,dict):return body
    for block in result.get('content',[]):
        if block.get('type')=='text':
            try:
                body=json.loads(block['text'])
                if isinstance(body,dict):return body
            except (ValueError,KeyError):pass
    return {}


def fixture_errors(case,state,phase='spawned'):
    """Read actual roots; ready metadata alone cannot certify a fresh spawn."""
    actors={a['actor_id']:a for a in state['actors']};expected=case['fixture']['actors']
    errors=[]
    if set(actors)!={a['actor_id'] for a in expected}|{'witness'}:errors.append({'kind':'actor_set_mismatch','actual':sorted(actors)})
    for spec in [*expected,{'actor_id':'witness','position_m':[18,16,0]}]:
        aid=spec['actor_id'];row=actors.get(aid,{});obs=row.get('observation',{});point=obs.get('position_m')
        if not obs.get('ready') or not isinstance(point,list) or len(point)!=3 or not all(isinstance(x,(int,float)) and math.isfinite(x) for x in point):
            errors.append({'actor_id':aid,'kind':'no_finite_native_root','actual':repr(point)});continue
        if phase=='prepared' and aid=='witness':continue
        if phase=='prepared' and case['fixture'].get('seated_actor')==aid:
            if row.get('seat')!='seat_00' or row.get('task',{}).get('step_phase')!='holding' or obs.get('speed_mps',99)>=.15:errors.append({'actor_id':aid,'kind':'not_seated'})
            continue
        delta=math.dist(point[:2],spec['position_m'][:2])
        if delta>.3:errors.append({'actor_id':aid,'kind':'spawn_position_mismatch','expected_m':spec['position_m'],'actual_m':point,'error_m':delta})
    return errors


def completed_calls(trace):
    return [x['item'] for x in trace if x.get('type')=='item.completed' and x.get('item',{}).get('type')=='mcp_tool_call']


def tool_name(item):
    return item.get('tool','').rsplit('__',1)[-1]


def call_errors(item):
    body=tool_body(item);errors=error_codes(body.get('error',{}))
    for row in body.get('results',[]):errors.extend(error_codes(row.get('error',{})))
    if body.get('valid') is False:errors.extend(error_codes(body.get('errors',[])))
    # CLI status=failed also represents a valid MCP isError result. A native
    # semantic refusal is not a broken stdio connection. Preserve its code.
    if not errors and (item.get('error') or item.get('status')=='failed'):
        errors.extend(error_codes(item.get('error',{})) or ['MCP_TRANSPORT_ERROR'])
    return errors


def error_codes(value):
    if isinstance(value,dict):
        own=[value['code']] if isinstance(value.get('code'),str) else []
        return own+[c for v in value.values() for c in error_codes(v)]
    if isinstance(value,list):return [c for v in value for c in error_codes(v)]
    return []


def grade(case, before, after, events, trajectory, trace, final, execution):
    old={a['actor_id']:a for a in before['actors']};current={a['actor_id']:a for a in after['actors']}
    accepted={e['task']['task_id']:copy.deepcopy(e['task']) for e in events if e['kind']=='task_accepted'}
    for e in events:
        if e['kind']=='task_ended' and e['task']['task_id'] in accepted:accepted[e['task']['task_id']]=e['task']
    for a in current.values():
        if a.get('task',{} ) and a['task']['task_id'] in accepted:accepted[a['task']['task_id']]=a['task']
    tasks=list(accepted.values());calls=completed_calls(trace)
    usage=Counter()
    for e in trace:
        if e.get('type')=='turn.completed':usage.update(e.get('usage',{}))
    actual_errors=[c for item in calls for c in call_errors(item)]
    checks={'host_exit_zero':execution.get('returncode')==0,'budget_not_interrupted':execution.get('interrupted') is None,
            'mcp_used':bool(calls),'only_local_simpeople_tools':all('simpeople' in c.get('server','') for c in calls),
            'no_shell_or_file_execution':not any(x.get('item',{}).get('type') in {'command_execution','file_change','web_search'} for x in trace),
            'exact_declared_actor_set':set(old)|set(case.get('created_actors',[]))==set(current),'same_episode':before['episode_id']==after['episode_id'],
            'finite_budget':execution['wall_s']<=case['budget']['wall_s'] and after['sim_time']-before['sim_time']<=case['budget']['sim_s']+1e-7,
            'tool_budget':len(calls)<=case['budget']['tool_calls'],
            'usage_reported':bool(usage),'input_token_budget':usage['input_tokens']<=case['budget']['input_tokens'],
            'output_token_budget':usage['output_tokens']<=case['budget']['output_tokens']}
    checks['session_and_preflight_read']=any(tool_name(c)=='people_session' and c.get('arguments',{}).get('action','info')=='info' and tool_body(c).get('session_id') and tool_body(c).get('episode_id')==before['episode_id'] for c in calls) and any(tool_name(c)=='people_session' and c.get('arguments',{}).get('action')=='preflight' and tool_body(c).get('ready') is True for c in calls)
    checks['target_capabilities_read']=all(any(tool_name(c)=='people_list_actions' and tool_body(c).get('actor_id')==aid and bool(tool_body(c).get('actions')) for c in calls) for aid in case['targets'])
    validations=[];validated_tasks=[];scope_checks=[];pending=None
    write_methods={'control_session','spawn','despawn','move_to','perform','run_activity','cancel','batch','populate','reset','pause','resume','record','signal_event','move_prop'}
    session_ids={tool_body(c)['session_id'] for c in calls if tool_name(c)=='people_session' and tool_body(c).get('session_id')}
    for e in events:
        if e['kind']=='tool_call':
            if e.get('method')=='validate_activity':pending=e['params']['actor_id']
            if e.get('method') in write_methods:scope_checks.append(e['params'].get('session_id') in session_ids and e['params'].get('episode_id')==before['episode_id'])
        if e['kind']=='tool_result' and e.get('method')=='validate_activity' and e.get('result',{}).get('valid') is True:
            validations.append((pending,e['result']['steps']))
        if e['kind']=='task_accepted':
            task=e['task'];validated_tasks.append(any(a==task['actor_id'] and steps==task['steps'] for a,steps in validations))
    checks['accepted_plans_prevalidated']=all(validated_tasks)
    checks['writes_bind_observed_scope']=all(scope_checks)
    known_ids=set(accepted)|{a['task']['task_id'] for a in old.values() if a.get('task')}|{e['task']['task_id'] for e in events if e.get('task')}
    checks['reported_task_ids_known']=set(final.get('task_ids',[]))<=known_ids
    for aid in ['witness',*case['preserve']]:
        a=current.get(aid,{});b=old.get(aid,{})
        checks['preserved_'+aid]=bool(a and b and a['actor_instance_id']==b['actor_instance_id'] and a['control_epoch']==b['control_epoch'] and a.get('task',{}).get('task_id')==b.get('task',{}).get('task_id'))
    witness=[r for r in trajectory if r.get('actor_id')=='witness' and r.get('ready')]
    checks['witness_kept_moving']=bool(witness) and max((math.dist(r['position_m'][:2],witness[0]['position_m'][:2]) for r in witness),default=0)>.25
    checks['witness_task_healthy']=current.get('witness',{}).get('task',{}).get('status') in {'running','blocked','succeeded'}
    def successes(aid):return [t for t in tasks if t['actor_id']==aid and t['status']=='succeeded']
    def actions(t):return [s['action'] for s in t['steps']]
    def covers(t,wanted):
        values=actions(t)
        if set(values)-set(wanted)-{'move_to','wait','look_at'}:return False
        sequence=iter(values)
        return all(any(a==expected for a in sequence) for expected in wanted)
    def cancelled(aid,wanted):
        candidates=[e['task'] for e in events if e['kind']=='task_ended' and e['task']['actor_id']==aid and e['task']['status']=='cancelled' and e['task'].get('physical_stop_verified') and all(a in actions(e['task']) for a in wanted)]
        return candidates
    def leases_clear(aid):
        snapshot=after.get('resource_snapshot')
        if snapshot is None:return False
        resources=snapshot['resources'];groups=[*resources.get('admission',{}).values(),*snapshot['queues'].values()]
        return aid not in resources.get('owners',{}).values() and not any(t['actor_id']==aid and t['status'] in {'waiting','admitted','serving','exiting'} for g in groups for t in g.get('tickets',[]))
    for i,p in enumerate(case['predicates']):
        k=p['kind'];aid=p.get('actor_id');ok=False
        if k=='succeeded':ok=any(covers(t,p['actions']) for t in successes(aid))
        elif k=='goal':
            obs=current.get(aid,{}).get('observation',{});point=obs.get('position_m');ok=bool(point and obs.get('ready') and math.dist(point[:2],p['target'][:2])<=.3 and obs.get('speed_mps',99)<.15)
        elif k=='seat_clear':
            a=current.get(aid,{});ok=bool(a and not a.get('seat') and not a.get('seat_cleanup_pending') and not a.get('queue_cleanup_pending') and leases_clear(aid))
        elif k=='cancelled_then_wait':
            stopped=cancelled(aid,p['actions']);restored=[t for t in successes(aid) if actions(t)==['wait']]
            ok=any(r.get('started_sim_time',-1)>=c['finished_sim_time'] for c in stopped for r in restored)
            if 'move_to' in p['actions']:
                candidate_ids={t['task_id'] for t in stopped};samples=[r for r in trajectory if r.get('actor_id')==aid and r.get('task_id') in candidate_ids and r.get('ready')]
                ok=ok and bool(samples) and max((math.dist(r['position_m'][:2],samples[0]['position_m'][:2]) for r in samples),default=0)>.3
        elif k=='negative':
            required=[c for c in calls if tool_name(c)==p['required_tool']]
            established=any(set(call_errors(c)) & set(p['codes']) or tool_body(c).get('actions') or tool_name(c)=='people_session' and tool_body(c).get('session_id') for c in required)
            ok=final.get('status') in {'rejected','failed'} and bool(set(final.get('reason_codes',[])) & set(p['codes'])) and established
            # A rejection cannot silently schedule an unrelated successful plan.
            if not case['targets']:ok=ok and not tasks
        elif k in {'unreachable','failed_then_recovered'}:
            failed=[t for t in tasks if t['actor_id']==aid and t['status']=='failed' and t.get('error',{}).get('code')=='TARGET_UNREACHABLE' and any(s.get('target')==p['target'] for s in t['steps'])]
            if k=='unreachable':ok=bool(failed) and not successes(aid) and math.dist(current[aid]['observation']['position_m'][:2],old[aid]['observation']['position_m'][:2])<.15
            else:ok=any(t.get('started_sim_time',-1)>=f['finished_sim_time'] for f in failed for t in successes(aid))
        elif k=='batch':
            ok=False
            for c in calls:
                a=c.get('arguments',{})
                if tool_name(c)!='people_crowd' or a.get('operation')!=p['operation']:continue
                selected=[x['actor_id'] for x in tool_body(c).get('results',[])]
                fixed=a.get('items') is not None or set((a.get('selector') or {}).get('actor_ids',[]))==set(p['actors'])
                if set(selected)==set(p['actors']) and fixed:ok=True
        elif k=='fifo':
            order=[e['actor_id'] for e in events if e['kind']=='queue_service_started' and e.get('resource_id')==p['target']]
            ok=order==p['actors'] and all(not current[a].get('queue_cleanup_pending') and leases_clear(a) for a in p['actors'])
        checks[f'predicate_{i}_{k}']=bool(ok)
    # Budget the number of accepted re-plans; explicit cancel/restore and failed
    # target recovery require two tasks rather than counting their purpose as a repair.
    expected={a:1 for a in case['targets']}
    for p in case['predicates']:
        if p['kind'] in {'cancelled_then_wait','failed_then_recovered'}:expected[p['actor_id']]=2
    if case['fixture'].get('seated_actor') in expected:expected[case['fixture']['seated_actor']]=1
    seen=Counter();accepted_repairs=set()
    for t in tasks:
        aid=t['actor_id'];seen[aid]+=1
        if aid in expected and seen[aid]>expected[aid]:accepted_repairs.add(t.get('request_id') or t['task_id'])
    rejected_variants=set()
    for c in calls:
        name=tool_name(c);args=c.get('arguments',{});body=tool_body(c)
        is_plan=name in {'people_validate_activity','people_run_activity','people_move_to','people_perform'} or name=='people_crowd' and args.get('operation')=='run_activity'
        rejected=bool(body.get('error')) or body.get('valid') is False
        expected_bad=case['category']=='partial_batch' and args.get('actor_id')=='b' and set(call_errors(c))=={'TARGET_INVALID'}
        if case['polarity']=='positive' and is_plan and rejected and not expected_bad:
            proposal={k:v for k,v in args.items() if k not in {'request_id','session_id','episode_id','controller_epoch','command_id','attempt_id'}}
            rejected_variants.add(json.dumps({'tool':name,'arguments':proposal},sort_keys=True))
    repairs=len(accepted_repairs)+len(rejected_variants)
    checks['bounded_repairs']=repairs<=case['budget']['max_repairs']
    if case['polarity']=='positive':
        checks['truthful_completed_report']=final.get('status')=='completed'
        reported=set(final.get('task_ids',[]));known=set(accepted)|{a['task']['task_id'] for a in old.values() if a.get('task')}|{e['task']['task_id'] for e in events if e.get('task')}
        checks['reported_actual_task_ids']=bool(reported) and reported<=known and all(any(t['task_id'] in reported for t in successes(aid)) for aid in case['targets'])
    validation_calls=[c for c in calls if tool_name(c)=='people_validate_activity' and not (case['category']=='partial_batch' and c.get('arguments',{}).get('actor_id')=='b' and set(call_errors(c))=={'TARGET_INVALID'})]
    first_parameters_passed=bool(validation_calls) and tool_body(validation_calls[0]).get('valid') is True
    first_tasks={}
    for t in tasks:first_tasks.setdefault(t['actor_id'],t)
    return {'case_id':case['case_id'],'split':case['split'],'polarity':case['polarity'],'category':case['category'],'passed':all(checks.values()),'checks':checks,
            'first_parameters_passed':first_parameters_passed,'first_execution_succeeded':bool(first_tasks) and all(t['status']=='succeeded' for t in first_tasks.values()),
            'repairs':repairs,'accepted_repair_requests':len(accepted_repairs),'rejected_plan_variants':len(rejected_variants),'tool_calls':len(calls),'tool_error_codes':actual_errors,'usage':dict(usage),'activity_status_counts':dict(Counter(t['status'] for t in tasks)),
            'tasks':[{k:t.get(k) for k in ['task_id','actor_id','status','started_sim_time','finished_sim_time','error']} for t in tasks],
            'wall_s':execution['wall_s'],'sim_s':after['sim_time']-before['sim_time'],'scope':'Actual native events and state, real host JSONL. Token limits assessed on reported usage; no estimated monetary cost.'}


def summarize(manifest, results):
    planned=len(manifest['case_ids'])*manifest['repetitions'];positive=[r for r in results if r['polarity']=='positive'];negative=[r for r in results if r['polarity']=='negative']
    def first(r):return r['passed'] and r['repairs']==0 and r['first_parameters_passed']
    def score(rows,fn):return {'passed':sum(bool(fn(r)) for r in rows),'total':len(rows),'rate':sum(bool(fn(r)) for r in rows)/len(rows) if rows else None}
    def clustered(rows,fn):
        groups={r['case_id']:[x for x in rows if x['case_id']==r['case_id']] for r in rows}
        if len(groups)<5:return None
        rng=random.Random(2033);ids=sorted(groups);values=[]
        for _ in range(4000):
            sampled=[r for _ in ids for r in groups[rng.choice(ids)]];values.append(sum(bool(fn(r)) for r in sampled)/len(sampled))
        values.sort();return {'lower':values[100],'upper':values[3899],'method':'case-cluster bootstrap, 4000 resamples, seed 2033; repeated attempts within case stay together'}
    first_rate=score(positive,first);recovered=score(positive,lambda r:r['passed']);neg=score(negative,lambda r:r['passed']);complete=len(results)==planned and {(r['case_id'],r['repetition']) for r in results}=={(c,i) for c in manifest['case_ids'] for i in range(1,manifest['repetitions']+1)}
    gates={'complete_20x3_formal_matrix':bool(manifest['formal'] and len(manifest['case_ids'])==20 and manifest['repetitions']==3 and complete),
           'positive_first_end_to_end_90pct':bool(positive and first_rate['rate']>=.9),'positive_bounded_recovery_95pct':bool(positive and recovered['rate']>=.95),
           'all_negative_cases_protected':bool(negative and neg['passed']==neg['total'])}
    return {'host':manifest['host'],'model':manifest['model'],'formal':manifest['formal'],'planned_attempts':planned,'finished_attempts':len(results),'unrun_attempts':planned-len(results),'passed':all(gates.values()),'gates':gates,
            'positive_first_end_to_end':first_rate,'positive_after_bounded_repairs':recovered,'negative_correct_rejections':neg,
            'first_parameters_passed':score(positive,lambda r:r['first_parameters_passed']),'first_accepted_activity_succeeded':score(positive,lambda r:r['first_execution_succeeded']),
            'positive_first_end_to_end_95pct_interval':clustered(positive,first),'positive_bounded_recovery_95pct_interval':clustered(positive,lambda r:r['passed']),
            'by_category':{k:score([r for r in results if r['category']==k],lambda r:r['passed']) for k in sorted({r['category'] for r in results})},
            'native_activity_status_counts':dict(sum((Counter(r['activity_status_counts']) for r in results),Counter())),
            'mean_tool_calls':sum(r['tool_calls'] for r in results)/len(results) if results else None,'mean_wall_s':sum(r['wall_s'] for r in results)/len(results) if results else None,
            'mean_sim_s':sum(r['sim_s'] for r in results)/len(results) if results else None,'usage':dict(sum((Counter(r['usage']) for r in results),Counter())),
            'model_cost':None,'limits':'Refusals are separate from positive denominator. First E2E requires full native predicates, first positive-plan validation and no extra accepted request or distinct rejected plan variant. The first-accepted-activity metric also retains intentional cancellations/failures. Pilots and incomplete matrices never qualify. Claude not inferred from Codex.'}
