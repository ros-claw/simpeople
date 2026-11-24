"""Synthetic task/claim counterexamples, never native supersession qualification."""
import copy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_local_yield_replacement import review
from test_local_yield_fault_audit import fixture as cancel_fixture


def fixture():
 start,phases,motions,fault,events,rows,roots,tasks,spec,_=copy.deepcopy(cancel_fixture())
 old=tasks['bt'];old.update(steps=[],status='cancelled',physical_stop_verified=False,finished_sim_time=10.2,error={'code':'CANCELLED','message':'superseded'})
 new={**old,'task_id':'new','control_epoch':2,'status':'succeeded','physical_stop_verified':True,'started_sim_time':10.2,'finished_sim_time':16.,'steps':[{'action':'move_to','target':[2.5,2.5,0],'timeout_s':15,'gait':'walk'}]};tasks['new']=new
 expected={'params':{'actor_id':'b','steps':[{k:v for k,v in new['steps'][0].items() if k!='gait'}]}}
 fault.update(method='run_activity',resolved_params=expected['params'],result={'task_id':'new'})
 events[:]=[e for e in events if e['kind']!='cancel_requested']
 events.extend([{**{k:new[k] for k in ['session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id']},'kind':'native_task_bound','backend_task_id':'route-new','native_task_id':None,'cursor':7},
  {'kind':'traffic_native_started','route_id':'route-new','native_task_id':101,'cursor':10,'sim_time':12.5},
  {'kind':'step_started','task_id':'new','sim_time':10.2}])
 # Release ordering is meaningful even though the old logical task finished earlier.
 events[-4]['cursor']=9  # original old-claim release precedes new SDK submission.
 for r in rows:
  if r['sim_time']>10.2:r['task_id']='new'
  if r['sim_time']>=12.5:
   progress=min(1,(r['sim_time']-12.5)/3)
   r.update(position_m=[2.5*progress,2.5,0],speed_mps=0 if progress==1 else 2.5/3,
    action='MoveAlong' if 0<progress<1 else 'Idle',native_task_id=101 if 0<progress<1 else 0,
    traffic_claim_cells=[[0,2],[1,2],[2,2]])
   if r['sim_time']==12.5:r.update(speed_mps=0)
 spec['steps']=[]
 return start,phases,motions,fault,events,rows,roots,tasks,spec,expected


def test_new_generation_waits_for_actual_old_claim_stop_before_reaching_new_goal():
 result=review(*fixture());assert result['verified'],result
 assert result['actual_stop_samples']==16 and result['new_task_id']=='new'


@pytest.mark.parametrize('fault',['early_new_sdk','early_submission','old_claim_gap','old_claim_release_missing',
 'wrong_new_epoch','wrong_body','false_old_physical_stop','old_deadline_reset','missing_stop_frame',
 'new_goal_not_reached','new_claim_disappears','old_route_resumes','new_task_not_bound'])
def test_old_terminal_and_new_acceptance_do_not_prove_a_safe_handoff(fault):
 args=list(copy.deepcopy(fixture()))
 if fault=='early_new_sdk':args[5][30]['native_task_id']=101
 elif fault=='early_submission':args[4][-2]['sim_time']=12
 elif fault=='old_claim_gap':args[5][30]['traffic_claim_cells']=[]
 elif fault=='old_claim_release_missing':args[4]=[e for e in args[4] if e['kind']!='traffic_cancelled_yield_claim_released']
 elif fault=='wrong_new_epoch':args[5][30]['control_epoch']=1
 elif fault=='wrong_body':args[5][30]['traffic_body_instance_id']='recreated'
 elif fault=='false_old_physical_stop':args[7]['bt']['physical_stop_verified']=True
 elif fault=='old_deadline_reset':args[4][1]['recovery']['deadline_sim_time']=999
 elif fault=='missing_stop_frame':args[5].pop(65)
 elif fault=='new_goal_not_reached':args[5][-1]['position_m']=[0,2.5,0]
 elif fault=='new_claim_disappears':args[5][100]['traffic_claim_cells']=[]
 elif fault=='old_route_resumes':args[4].append({'kind':'traffic_native_started','route_id':'r','cursor':20,'sim_time':13})
 else:args[4]=[e for e in args[4] if e['kind']!='native_task_bound']
 assert not review(*args)['verified']


def test_default_walk_normalization_is_preserved_but_an_unrequested_speed_is_rejected():
 args=fixture();assert 'gait' not in args[-1]['params']['steps'][0]
 assert args[7]['new']['steps'][0]['gait']=='walk' and review(*args)['verified']
 args[7]['new']['steps'][0]['speed_mps']=2
 assert not review(*args)['verified']


def test_route_supervisor_binding_is_separate_from_the_actual_sdk_subtask_id():
 args=fixture();binding=next(e for e in args[4] if e['kind']=='native_task_bound')
 assert binding['backend_task_id']=='route-new' and binding['native_task_id'] is None
 binding['native_task_id']=binding.pop('backend_task_id')
 assert not review(*args)['verified']
 args=fixture();binding=next(e for e in args[4] if e['kind']=='native_task_bound');binding['episode_id']='other-world'
 assert not review(*args)['verified']
