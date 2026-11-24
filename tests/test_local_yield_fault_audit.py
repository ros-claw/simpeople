"""Synthetic counterexamples for the independent reviewer; not native acceptance."""
import copy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_local_yield_faults import review_fault,forward_point
from test_local_yield_audit import fixture as admission_fixture


def fixture():
 start,phases,motion,_,rows,roots,events,task,spec=copy.deepcopy(admission_fixture())
 start.update(cursor=3);phases.pop('original_goal_restored');motion[0].update(kind='traffic_local_yield_motion_observed',cursor=4)
 current={**start,'body_instance_id':'body-b','current_route_id':'r','route_native_task_id':99,'sdk_task_id':99,
  'position_m':[0,.25,0],'task_status':'running','cancel_requested':False,
  'local_yield':{'path_m':start['points_m'],'body_generation':'body-b','native_task_id':99,'deadline_sim_time':18.}}
 proof={'kind':'native_local_yield_motion','release':{'fences':{k:start[k] for k in ['session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id']},
  'route_id':'r','native_task_id':99,'observed_sim_time':10.2,'points_m':start['points_m']},'current':current}
 fault={'kind':'benchmark_fault_applied','sim_time':10.2,'cursor':6,'trigger_evidence':proof,'method':'cancel','resolved_params':{'actor_id':'b'}}
 task.update(status='cancelled',physical_stop_verified=True,finished_sim_time=12.5)
 events.pop()
 events += [{'kind':'cancel_requested',**{k:task[k] for k in ['session_id','episode_id','actor_instance_id','task_id']},'control_epoch':2,'sim_time':10.2},
  {'kind':'traffic_cancelled_yield_claim_retained','route_id':'r','body_instance_id':'body-b','sim_time':10.2,'cells':start['reserved_cells']},
  {'kind':'traffic_cancelled_yield_claim_released','route_id':'r','body_instance_id':'body-b','sim_time':12.5,'cells':start['reserved_cells']}]
 for r in rows:
  r['traffic_claim_cells']=start['reserved_cells'] if r['sim_time']<12.5 else []
  if r['sim_time']>10.2:r['control_epoch']=2
  if r['sim_time']>=12:r.update(position_m=[0,2.5,0],action='Idle',speed_mps=0)
 # Tick-start admission data still uses the original epoch and native Idle.
 expected={'method':'cancel'}
 return start,phases,motion,fault,events,rows,roots,{'bt':task},spec,expected


def test_verified_cancel_requires_held_claim_and_actual_new_epoch_stop():
 result=review_fault(*fixture())
 assert result['verified'] and result['actual_stop_samples']==16
 assert result['actual_stop_control_epoch']==2


@pytest.mark.parametrize('fault',['no_lease','early_release','lease_gap','wrong_stop_epoch','wrong_motion',
 'new_task','same_name_new_body','missing_stop_sample','drift','resumed','priority_reset','report_only',
 'deadline_reset','late_fault','rebind_native','missing_motion','old_goal_resumed','no_cancel_event'])
def test_terminal_labels_and_single_still_cannot_substitute_for_fenced_stop(fault):
 args=list(copy.deepcopy(fixture()))
 if fault=='no_lease':args[4]=[e for e in args[4] if e['kind']!='traffic_cancelled_yield_claim_retained']
 elif fault=='early_release':args[4][-1]['sim_time']=10.2
 elif fault=='lease_gap':args[5][30]['traffic_claim_cells']=[]
 elif fault=='wrong_stop_epoch':args[5][65]['control_epoch']=1
 elif fault=='wrong_motion':args[2][0]['actual_position_m']=[99,0,0]
 elif fault=='new_task':args[5][65]['task_id']='replacement'
 elif fault=='same_name_new_body':args[5][30]['traffic_body_instance_id']='new-body'
 elif fault=='missing_stop_sample':args[5].pop(65)
 elif fault=='drift':args[5][65]['position_m']=[0,1,0]
 elif fault=='resumed':args[5][-1]['position_m']=[0,3,0]
 elif fault=='priority_reset':args[1]['native_submitted']['snapshot']['fair_gate']['pending']['r']['since']=10
 elif fault=='report_only':args[8]['on_blocked']='report'
 elif fault=='deadline_reset':args[4][1]['recovery']['deadline_sim_time']=99
 elif fault=='late_fault':args[3]['sim_time']=11
 elif fault=='rebind_native':args[3]['trigger_evidence']['current']['sdk_task_id']=100
 elif fault=='missing_motion':args[2]=[]
 elif fault=='old_goal_resumed':args[4].append({'kind':'traffic_native_started','route_id':'r','cursor':7})
 else:args[4]=[e for e in args[4] if e['kind']!='cancel_requested']
 result=review_fault(*args)
 assert not result['verified'] and result['errors']


def test_independent_box_projection_uses_actual_corners():
 assert forward_point([[0,0,0],[1,0,0],[1,1,0]],[.2,0,0],1.2,.05,.65)==pytest.approx([1,.4,.65])
 with pytest.raises(ValueError):forward_point([[0,0,0],[1,0,0]],[1,0,0],1.2,.05,.65)


def box_fixture():
 args=list(fixture());start,_,_,fault,events,rows,_,tasks,_,_=args
 fault.update(method='move_prop',resolved_params={'prop_id':'box','position_m':[0,1.45,.65]})
 events[:]=[e for e in events if e['kind'] not in {'cancel_requested','traffic_cancelled_yield_claim_retained','traffic_cancelled_yield_claim_released'}]
 events.extend([{'kind':'prop_moved','prop_id':'box','position_m':[0,1.45,.65],'sim_time':10.2},
  {'kind':'traffic_local_yield_brake','route_id':'r','reason':'dynamic_obstacle','sim_time':10.2+1/30},
  {'kind':'traffic_local_yield_ended','route_id':'r','status':'failed','sim_time':12.5},
  {'kind':'traffic_route_ended','route_id':'r','status':'failed','sim_time':12.5}])
 for r in rows:r['control_epoch']=1
 tasks['bt'].update(status='failed',error={'code':'BACKEND_TASK_FAILED'})
 args[-1]={'method':'move_prop','params':{'prop_id':'box'},'trigger':{'placement':{'forward_m':1.2,'end_margin_m':.05,'z_m':.65}}}
 return args


def test_box_failure_is_explicit_and_still_needs_actual_retained_stop():
 result=review_fault(*box_fixture());assert result['verified']
 assert result['actual_stop_control_epoch']==1


@pytest.mark.parametrize('fault',['off_path_box','missing_brake','false_success','early_claim_release','no_release'])
def test_obstacle_failure_labels_do_not_prove_a_safe_brake(fault):
 args=copy.deepcopy(box_fixture())
 if fault=='off_path_box':args[3]['resolved_params']['position_m']=[3,3,.65]
 elif fault=='missing_brake':args[4]=[e for e in args[4] if e['kind']!='traffic_local_yield_brake']
 elif fault=='false_success':args[7]['bt']['status']='succeeded'
 elif fault=='early_claim_release':args[5][30]['traffic_claim_cells']=[]
 else:args[4]=[e for e in args[4] if e['kind']!='traffic_route_ended']
 assert not review_fault(*args)['verified']


def test_crowd_wait_failure_stays_failed_even_when_local_cancel_is_safe():
 from audit_local_yield_faults import gate_results
 r=gate_results([{'verified':True}],[],['fair waiting budget violation'])
 assert r=={'qualification_passed':False,'local_fault_safety_verified':True,'waiting_budget_verified':False}
 assert not gate_results([{'verified':True}],['missing RGB'],[])['local_fault_safety_verified']
 assert not gate_results([],[],[])['qualification_passed']
 assert not gate_results([{'verified':False}],[],[])['local_fault_safety_verified']
