import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


spec=importlib.util.spec_from_file_location('queue_progress',Path(__file__).parents[1]/'scripts/audit_queue_route_progress.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


@pytest.fixture
def example():
    task={'task_id':'t','actor_id':'a','episode_id':'e','control_epoch':1,'step_started':0.,'finished_sim_time':.3,
          'step_index':0,'steps':[{'action':'queue','target':'q','timeout_s':.3,'duration_s':.1}],
          'status':'failed','error':{'code':'TIMEOUT'},'service_started':.1,'queue_egress_target':[1,0,0]}
    event=lambda kind,time,**kw:{'kind':kind,'episode_id':'e','sim_time':time,'cursor':round(time*300)+10,**kw}
    events=[event('tool_result',-1,method='spawn',result={'actor_id':'a','prim_path':'/A','backend':'native','episode_id':'e'}),
            event('queue_slot_assigned',0,actor_id='a',queue='q',index=0,target=[.2,0,0]),
            event('traffic_route_started',0,agent='/A',route_id='r1',goals_m=[[.2,0,0]]),
            event('traffic_native_started',0,route_id='r1',native_task_id=1,target_m=[.1,0,0]),
            event('traffic_route_started',.2,agent='/A',route_id='r2',goals_m=[[1,0,0]]),
            event('traffic_native_started',7/30,route_id='r2',native_task_id=2,target_m=[-1,0,0]),
            event('traffic_wait_ended',2/30,route_id='r1',wait_sim_s=1/30),
            event('task_ended',.3,task=copy.deepcopy(task)),
            event('traffic_wait_started',1/30,route_id='r1')]
    rows=[{'actor_id':'a','episode_id':'e','task_id':'t','control_epoch':1,'ready':True,
           'sim_time':i/30,'observation_sim_time':i/30,'position_m':[x,0,0],
           'position_source':'BehaviorAgent.get_world_translation',
           'speed_mps':999} for i,x in enumerate([0,0,.1,.2,.2,.2,.2,.1,.05,.05])]
    return task,events,rows


def test_split_actual_horizontal_motion_and_logged_wait(example):
    result=module.review(*example)
    assert result['total']['horizontal_path_m']==pytest.approx(.35)
    assert result['total']['horizontal_moving_s']==pytest.approx(4/30)
    assert result['total']['horizontal_stationary_s']==pytest.approx(5/30)
    assert result['pre_service']['horizontal_path_m']==pytest.approx(.2)
    assert result['logged_completed_traffic_wait_s']==pytest.approx(1/30)
    assert result['commands_farther_from_goal']==1
    assert result['phases'][-1]['euclidean_away_from_goal_m']==pytest.approx(.15)
    assert sum(p['duration_s'] for p in result['phases'])==pytest.approx(.3)


@pytest.mark.parametrize('problem', ['missing','duplicate','stale','owner','epoch','episode','nonfinite','unready','boundary','static_xform'])
def test_reject_unbound_or_incomplete_body_stream(example,problem):
    task,events,rows=example
    if problem=='missing':rows.pop(4)
    elif problem=='duplicate':rows.insert(4,copy.deepcopy(rows[4]))
    elif problem=='stale':rows[4]['observation_sim_time']-=1/30
    elif problem=='owner':rows[4]['task_id']='other'
    elif problem=='epoch':rows[4]['control_epoch']=2
    elif problem=='episode':rows[4]['episode_id']='other'
    elif problem=='nonfinite':rows[4]['position_m'][0]=float('nan')
    elif problem=='unready':rows[4]['ready']=False
    elif problem=='static_xform':rows[4]['position_source']='UsdGeom.Xform'
    else:rows.pop()
    with pytest.raises(ValueError):module.review(task,events,rows)


@pytest.mark.parametrize('problem', ['recreated','wrong_agent','command_tick','wrong_terminal','changed_deadline','wrong_queue','no_service','non_native','wrong_wait'])
def test_reject_unexercised_or_changed_queue_evidence(example,problem):
    task,events,rows=example
    if problem=='recreated':events.insert(0,copy.deepcopy(events[0]))
    elif problem=='wrong_agent':events[0]['result']['prim_path']='/Other'
    elif problem=='command_tick':events[3]['sim_time']=.01
    elif problem=='wrong_terminal':next(e for e in events if e['kind']=='task_ended')['task']['status']='succeeded'
    elif problem=='changed_deadline':task['steps'][0]['timeout_s']=2
    elif problem=='wrong_queue':events[1]['queue']='other'
    elif problem=='non_native':events[0]['result']['backend']='mock'
    elif problem=='wrong_wait':next(e for e in events if e['kind']=='traffic_wait_ended')['wait_sim_s']=1
    else:task.pop('service_started')
    with pytest.raises(ValueError):module.review(task,events,rows)


def test_vertical_idle_motion_is_not_horizontal_travel():
    rows=[{'sim_time':i/30,'position_m':[0,0,.02*i]} for i in range(4)]
    result=module.motion(rows,[1,0,0])
    assert result['horizontal_path_m']==0
    assert result['horizontal_moving_s']==0
    assert result['horizontal_stationary_s']==pytest.approx(.1)


def test_euclidean_retreat_is_measurement_not_arbitration_verdict(example):
    result=module.review(*example)
    assert result['commands_farther_from_goal']>0
    assert 'fairness_passed' not in result and 'unnecessary_detour' not in result
    assert 'not proof' in result['scope']


def test_missing_run_is_unverified(tmp_path):
    result=module.audit(tmp_path,'t')
    assert not result['verified'] and result['full_release_verified'] is False


def test_cancelled_wait_keeps_its_unserved_lower_bound(example):
    task,events,rows=example
    events[:]=[e for e in events if e['kind']!='traffic_wait_ended']
    events.append({'kind':'traffic_route_cancelled','episode_id':'e','sim_time':2/30,'cursor':30,'route_id':'r1'})
    result=module.review(task,events,rows)
    assert result['logged_completed_traffic_wait_s']==0
    assert result['logged_unserved_traffic_waits'][0]['wait_lower_bound_s']==pytest.approx(1/30)


def test_streaming_file_hash_matches_original_bytes(tmp_path):
    data=b'queue-clock\0'*(110000);path=tmp_path/'large.jsonl';path.write_bytes(data)
    assert module.sha_file(path)==hashlib.sha256(data).hexdigest()


def phase_example(example,phase):
    task,events,rows=example;task['step_phase']=phase;task.pop('queue_egress_target')
    events[:]=[e for e in events if e.get('route_id')!='r2']
    if phase in {'queue_waiting','queue_admission'}:task.pop('service_started')
    if phase=='queue_admission':
        events[:]=[e for e in events if not e['kind'].startswith('traffic_') and e['kind']!='queue_slot_assigned']
    next(e for e in events if e['kind']=='task_ended')['task']=copy.deepcopy(task)
    return task,events,rows


def test_serving_timeout_preserves_partial_service(example):
    result=module.review(*phase_example(example,'serving'))
    assert [p['phase'] for p in result['phases']]==['slot_0_approach','service']
    assert result['service_elapsed_before_egress_or_timeout_s']==pytest.approx(.2)
    assert not result['unserved_at_timeout']


def test_unserved_queue_timeout_keeps_full_request_age(example):
    result=module.review(*phase_example(example,'queue_waiting'))
    assert result['service_started'] is None
    assert result['unserved_at_timeout'] and result['unserved_request_age_lower_bound_s']==pytest.approx(.3)
    assert [p['phase'] for p in result['phases']]==['slot_0_approach']
    assert result['metric_goal_m']==[.2,0,0]
    assert result['pre_service']['duration_s']==pytest.approx(.3)


def test_unassigned_timeout_does_not_invent_world_target_or_sdk_calls(example):
    result=module.review(*phase_example(example,'queue_admission'))
    assert result['metric_goal_m'] is None
    assert result['total']['final_distance_to_goal_m'] is None
    assert result['total']['horizontal_path_m']==pytest.approx(.35)
    assert not result['native_command_lineage_exercised']
    assert result['commands_farther_from_goal']==0


def test_no_commands_is_explicitly_unexercised_not_a_motion_certificate(example):
    task,events,rows=example;events[:]=[e for e in events if e['kind']!='traffic_native_started']
    result=module.review(task,events,rows)
    assert result['total']['horizontal_path_m']>0 and not result['native_command_lineage_exercised']
    assert 'do not qualify' in result['scope']


def test_no_goal_still_counts_vertical_idle_correctly():
    rows=[{'sim_time':i/30,'position_m':[0,0,.02*i]} for i in range(4)]
    result=module.motion(rows,None)
    assert result['horizontal_path_m']==0 and result['horizontal_stationary_s']==pytest.approx(.1)
    assert result['euclidean_toward_goal_m'] is None and result['euclidean_away_from_goal_m'] is None


def test_serving_phase_cannot_borrow_old_boundary(example):
    task,events,rows=phase_example(example,'queue_waiting');task['service_started']=.1
    next(e for e in events if e['kind']=='task_ended')['task']=copy.deepcopy(task)
    with pytest.raises(ValueError,match='ambiguous'):module.review(task,events,rows)


def test_terminal_phase_cannot_be_changed_after_run(example):
    task,events,rows=phase_example(example,'serving');task['service_started']=.2
    with pytest.raises(ValueError,match='terminal phase'):module.review(task,events,rows)


def batch_folder(tmp_path,example,broken=False):
    tasks=[];events=[];rows=[]
    for i in range(2):
        task,actor_events,actor_rows=copy.deepcopy(example)
        if i:task,actor_events,actor_rows=phase_example((task,actor_events,actor_rows),'queue_admission')
        actor=f'a{i}';tid=f't{i}'
        task.update(actor_id=actor,task_id=tid)
        if broken and i:task['step_phase']='serving'
        for event in actor_events:
            if event.get('actor_id')=='a':event['actor_id']=actor
            if event.get('agent')=='/A':event['agent']='/'+actor
            if event.get('route_id'):event['route_id']+=str(i)
            if event['kind']=='tool_result':event['result'].update(actor_id=actor,prim_path='/'+actor)
            if event['kind']=='task_ended':event['task']=copy.deepcopy(task)
        for row in actor_rows:row.update(actor_id=actor,task_id=tid)
        tasks.append(task);events.extend(actor_events);rows.extend(actor_rows)
    events.sort(key=lambda e:e['sim_time'])
    for cursor,event in enumerate(events,1):event['cursor']=cursor
    for name,data in [('completed.json',{'harness_completed':True}),('tasks.json',tasks),
                      ('benchmark_done.json',{'event_cursor':len(events)}),('source_manifest.json',{}),
                      ('outcomes.json',{'denominator':100})]:
        (tmp_path/name).write_text(json.dumps(data)+'\n')
    for name,data in [('events.jsonl',events),('trajectories.jsonl',rows)]:
        (tmp_path/name).write_text(''.join(json.dumps(row)+'\n' for row in data))
    return tmp_path


def test_batch_keeps_nominal_denominator_separate_from_failed_subset(tmp_path,example):
    result=module.audit_many(batch_folder(tmp_path,example))
    assert result['verified'],result['errors']
    assert result['requested_timeout_tasks']==result['verified_timeout_tasks']==2
    assert result['original_nominal_request_denominator']==100
    assert result['full_release_verified'] is False
    assert result['results'][1]['measurement']['unserved_at_timeout']


def test_batch_keeps_unverifiable_task_in_denominator(tmp_path,example):
    result=module.audit_many(batch_folder(tmp_path,example,broken=True))
    assert not result['verified']
    assert result['requested_timeout_tasks']==2 and result['verified_timeout_tasks']==1
    assert len(result['results'])==2 and result['results'][1]['errors']
    assert result['original_nominal_request_denominator']==100
