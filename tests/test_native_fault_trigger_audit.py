"""Synthetic auditor counterexamples; never an Isaac acceptance substitute."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_native_fault_triggers import audit


@pytest.fixture
def evidence(tmp_path):
    def write(name,data):
        (tmp_path/name).write_text(json.dumps(data))
    lead={'session_id':'s','episode_id':'e','actor_id':'lead','actor_instance_id':'i','control_epoch':1,'task_id':'l'}
    witness={**lead,'actor_id':'witness','actor_instance_id':'wi','task_id':'w'}
    points=[[0,0,0],[10,10,0]]
    current={**lead,'agent':'/lead','body_instance_id':'body','current_route_id':'r','route_native_task_id':7,
             'sdk_task_id':7,'position_m':[2,2,0],'task_status':'running','cancel_requested':False,
             'witness':{**witness,'status':'running'}}
    release={'fences':{**lead,'agent':'/lead','body_instance_id':'body'},'route_id':'r','native_task_id':7,
             'observed_sim_time':5,'points_m':points,'position_m':[2,2,0]}
    events=[{'kind':'traffic_grid_ready','cell_m':1.25,'cursor':1,'sim_time':0},
            {'kind':'traffic_tail_tracking','route_id':'r','native_task_id':7,'eligible':True,
             'diagonal_straight_enabled':True,'points_m':points,'cursor':2,'sim_time':3},
            {**lead,'kind':'traffic_tail_released','agent':'/lead','body_instance_id':'body',
             'route_id':'r','native_task_id':7,'cursor':3,'sim_time':5},
            {**lead,'kind':'cancel_requested','control_epoch':2,'cursor':4,'sim_time':5},
            {'kind':'benchmark_fault_applied','event_id':'cancel','cursor':5,'sim_time':5,'method':'cancel','session_id':'s','episode_id':'e',
             'trigger_evidence':{'kind':'native_diagonal_release','release':release,'current':current}}]
    (tmp_path/'source_snapshot').mkdir();source=tmp_path/'source_snapshot/source.txt';source.write_text('fixture only')
    write('source_manifest.json',{'source.txt':hashlib.sha256(source.read_bytes()).hexdigest()})
    write('bootstrap.json',{'diagnostic_native_release_triggers':True})
    write('completed.json',{'harness_completed':True,'functional_expected_matched':True})
    write('benchmark_done.json',{'event_cursor':5})
    write('workload.json',{'events':[{'event_id':'cancel','method':'cancel','trigger':{'kind':'native_diagonal_release','actor_id':'lead','witness_actor_id':'witness'}}]})
    write('tasks.json',[{**lead,'status':'cancelled','physical_stop_verified':True,'started_sim_time':1,'finished_sim_time':6,'cancel_sim_time':5},
                        {**witness,'status':'succeeded','started_sim_time':1,'finished_sim_time':12}])
    write('runtime_audit.json',{'wait_budget_violations':0})
    write('acceptance_summary.json',{'trajectory_proxies':{'sustained_overlap_segments':[],'root_discontinuities':[]}})
    write('diagonal_review_v2.json',{'qualification_passed':True})
    rows=[{**lead,'ready':True,'sim_time':5,'position_m':[2,2,0],'native_task_id':7},
          {**witness,'ready':True,'sim_time':5,'position_m':[5,8,0],'native_task_id':2},
          {**witness,'ready':True,'sim_time':6,'position_m':[6,8,0],'native_task_id':2}]
    rows.extend({**lead,'control_epoch':2,'ready':True,'sim_time':5.5+i/30,'position_m':[2.2,2.2,0],'native_task_id':8,'action':'Idle'} for i in range(16))
    def journals():
        for name,data in [('events.jsonl',events),('trajectories.jsonl',rows)]:
            (tmp_path/name).write_text(''.join(json.dumps(r)+'\n' for r in data))
    journals()
    return tmp_path,events,rows,write,journals


def test_actual_identity_geometry_and_active_witness_are_all_required(evidence):
    folder,*_=evidence;result=audit(folder)
    assert result['qualification_passed'] and not result['errors'] and not result['full_release_passed']


@pytest.mark.parametrize('field,value',[('sdk_task_id',8),('body_instance_id','recreated'),
                                    ('control_epoch',2),('task_status','succeeded')])
def test_claimed_context_cannot_replace_actual_sdk_evidence(evidence,field,value):
    folder,events,rows,write,journals=evidence;events[-1]['trigger_evidence']['current'][field]=value;journals()
    assert not audit(folder)['qualification_passed']


def test_axis_or_unexercised_diagonal_gate_does_not_pass(evidence):
    folder,events,rows,write,journals=evidence;events[1]['points_m']=[[0,0,0],[10,0,0]];journals()
    assert not audit(folder)['qualification_passed']


def test_late_first_release_or_missing_actual_fault_row_fails(evidence):
    folder,events,rows,write,journals=evidence;events[-1]['sim_time']=7;journals()
    assert not audit(folder)['qualification_passed']


def test_changed_witness_generation_after_fault_cannot_supply_motion(evidence):
    folder,events,rows,write,journals=evidence;rows[2]['actor_instance_id']='recreated';journals()
    assert not audit(folder)['qualification_passed']


def test_finished_witness_and_incomplete_frozen_source_are_not_accepted(evidence):
    folder,events,rows,write,journals=evidence;events[-1]['trigger_evidence']['current']['witness']['control_epoch']=2;journals()
    assert not audit(folder)['qualification_passed']
    (folder/'source_snapshot/source.txt').write_text('tampered')
    assert any('changed frozen source' in e for e in audit(folder)['errors'])


@pytest.fixture
def box_evidence(evidence):
    folder,events,rows,write,journals=evidence
    events.pop(3)  # No cancellation epoch transition in a box experiment.
    placement={'forward_m':3,'end_margin_m':.05,'z_m':.65};position=[2+3/2**.5,2+3/2**.5,.65]
    enter={'event_id':'enter','method':'move_prop','params':{'prop_id':'movable_box'},
           'trigger':{'kind':'native_diagonal_release','actor_id':'lead','witness_actor_id':'witness','placement':placement}}
    clear={'event_id':'clear','method':'move_prop','params':{'prop_id':'movable_box','position_m':[-4,10,.65]},
           'trigger':{'kind':'event_applied','event_id':'enter','delay_s':8}}
    events[-1].update(event_id='enter',method='move_prop',cursor=5,resolved_params={'prop_id':'movable_box','position_m':position})
    events.insert(3,{'kind':'prop_moved','prop_id':'movable_box','position_m':position,'sim_time':5,'cursor':4})
    events.extend([{'kind':'traffic_obstacle_brake','route_id':'r','agent':'/lead','sim_time':5+1/30,'cursor':6},
                   {'kind':'prop_moved','prop_id':'movable_box','position_m':[-4,10,.65],'sim_time':13,'cursor':7},
                   {'kind':'benchmark_fault_applied','event_id':'clear','method':'move_prop','sim_time':13,'cursor':8,
                    'resolved_params':clear['params'],'trigger_evidence':{'kind':'event_applied'}}])
    write('workload.json',{'events':[enter,clear]});write('benchmark_done.json',{'event_cursor':8})
    tasks=json.loads((folder/'tasks.json').read_text());tasks[0].update(status='succeeded',physical_stop_verified=False,finished_sim_time=15);tasks[1]['finished_sim_time']=16;write('tasks.json',tasks)
    write('runtime_audit.json',{'wait_budget_violations':0,'dynamic_box_geometry_proxy':{'passed':True}})
    journals();return evidence


def test_actual_box_path_placement_brake_and_relative_clearing_are_required(box_evidence):
    folder,*_=box_evidence;assert audit(folder)['qualification_passed']


@pytest.mark.parametrize('fault',['wrong_route','wrong_position','wrong_clear_time','no_prop_clear','bad_geometry'])
def test_box_metadata_cannot_substitute_for_real_execution(box_evidence,fault):
    folder,events,rows,write,journals=box_evidence
    if fault=='wrong_route':events[5]['route_id']='another-route'
    elif fault=='wrong_position':events[4]['resolved_params']['position_m']=[8,8,.65]
    elif fault=='wrong_clear_time':events[-1]['sim_time']=8
    elif fault=='no_prop_clear':events[-2]['kind']='other_event'
    else:write('runtime_audit.json',{'wait_budget_violations':0,'dynamic_box_geometry_proxy':{'passed':False}})
    journals();assert not audit(folder)['qualification_passed']


def test_physical_stop_boolean_does_not_replace_actual_stop_window(evidence):
    folder,events,rows,write,journals=evidence
    rows[-1]['position_m']=[3,3,0];journals()
    assert not audit(folder)['qualification_passed']


@pytest.mark.parametrize('fault',['missing_cancel','wrong_cancel_epoch','wrong_cancel_instance',
                                 'old_stop_epoch','replaced_stop_epoch','moving_in_window','wrong_stop_action'])
def test_post_cancel_epoch_must_be_explicit_and_same_body_not_ignored(evidence,fault):
    folder,events,rows,write,journals=evidence
    if fault=='missing_cancel':events[3]['kind']='other_event'
    elif fault=='wrong_cancel_epoch':events[3]['control_epoch']=3
    elif fault=='wrong_cancel_instance':events[3]['actor_instance_id']='recreated'
    elif fault=='old_stop_epoch':
        for row in rows[3:]:row['control_epoch']=1
    elif fault=='replaced_stop_epoch':rows[-1]['control_epoch']=3
    elif fault=='moving_in_window':rows[-1]['position_m']=[3,3,0]
    else:rows[-1]['action']='MoveTo'
    journals();assert not audit(folder)['qualification_passed']
