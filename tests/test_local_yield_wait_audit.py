"""Synthetic counterexamples for the wait handoff reader, not Native coverage."""
import copy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_local_yield_wait import review
from test_local_yield_replacement_audit import fixture as move_fixture


def fixture():
 args=list(copy.deepcopy(move_fixture()));start,phases,motions,fault,events,rows,roots,tasks,spec,expected=args
 step={'action':'wait','duration_s':2,'timeout_s':15};expected['params']['steps']=[step]
 fault['resolved_params']=copy.deepcopy(expected['params']);tasks['new'].update(steps=[step],finished_sim_time=14.5)
 events[:]=[e for e in events if e['kind'] not in {'traffic_native_started','step_started'}]
 binding=next(e for e in events if e['kind']=='native_task_bound')
 binding.update(backend_task_id=101,native_task_id=101,sim_time=12.5,cursor=10)
 events.extend([{'kind':'step_started','task_id':'new','sim_time':12.5,'cursor':11},
  {'kind':'action_admission_deferred','task_id':'new','sim_time':10.2,'cursor':8,'deadline_sim_time':25.2,
   'blocked_details':{'previous_route_id':'r','body_instance_id':'body'}}])
 # Use the actual synthetic admission body's identifier, never a second body.
 events[-1]['blocked_details']['body_instance_id']=rows[0]['traffic_body_instance_id']
 for r in rows:
  if r['sim_time']>=12.5:r.update(position_m=[0,2.5,0],action='Idle',speed_mps=0,native_task_id=101,traffic_claim_cells=[])
 return args


def test_wait_does_not_start_until_actual_stop_and_then_holds_full_duration():
 result=review(*fixture());assert result['verified'],result
 assert result['actual_wait_duration_s']==2 and result['actual_stop_samples']==16


@pytest.mark.parametrize('fault',['early_sdk','early_binding','short_hold','deadline_reset','early_claim_release',
 'old_resume','wrong_epoch','wrong_body','gap','missing_deferral','drift','different_sdk'])
def test_acceptance_and_terminal_wait_alone_cannot_prove_safe_handoff(fault):
 a=fixture();ev=a[4];rows=a[5]
 if fault=='early_sdk':rows[30]['native_task_id']=101
 elif fault=='early_binding':next(e for e in ev if e['kind']=='native_task_bound')['cursor']=6
 elif fault=='short_hold':a[7]['new']['finished_sim_time']=14.2
 elif fault=='deadline_reset':ev[-1]['deadline_sim_time']=999
 elif fault=='early_claim_release':rows[30]['traffic_claim_cells']=[]
 elif fault=='old_resume':ev.append({'kind':'traffic_native_started','route_id':'r','cursor':90,'sim_time':13})
 elif fault=='wrong_epoch':rows[30]['control_epoch']=1
 elif fault=='wrong_body':rows[30]['traffic_body_instance_id']='new-body'
 elif fault=='gap':rows.pop(75)
 elif fault=='missing_deferral':ev.pop()
 elif fault=='drift':rows[100]['position_m']=[.1,2.5,0]
 else:rows[100]['native_task_id']=102
 assert not review(*a)['verified']


def delayed_readback_fixture():
 a=fixture();a[7]['new']['finished_sim_time']=14.5+1/30
 at=next(r for r in a[5] if abs(r['sim_time']-12.5)<1e-7)
 previous=next(r for r in a[5] if abs(r['sim_time']-(12.5-1/30))<1e-7)
 at['native_task_id']=previous['native_task_id']
 return a


def test_same_tick_precommand_idle_is_not_counted_as_new_wait_sdk_evidence():
 result=review(*delayed_readback_fixture());assert result['verified'],result
 assert result['wait_native_submitted_sim_time']==12.5
 assert result['wait_sdk_first_observed_sim_time']==pytest.approx(12.5+1/30)
 assert result['actual_wait_duration_s']==pytest.approx(2)


@pytest.mark.parametrize('fault',['short_new_sdk_hold','two_old_sdk_frames','unrelated_sdk_at_submission'])
def test_submission_tick_exception_cannot_hide_late_sdk_or_shorten_actual_hold(fault):
 a=delayed_readback_fixture()
 if fault=='short_new_sdk_hold':a[7]['new']['finished_sim_time']=14.5
 elif fault=='two_old_sdk_frames':
  at=next(r for r in a[5] if abs(r['sim_time']-(12.5+1/30))<1e-7);at['native_task_id']=0
 else:next(r for r in a[5] if abs(r['sim_time']-12.5)<1e-7)['native_task_id']=999
 assert not review(*a)['verified']
