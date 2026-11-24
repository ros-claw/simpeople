"""Synthetic two-joint readbacks; no generated Human or SDK qualification."""
import copy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_canonical_heading_rejection import review_rejection


def fixture():
 before={'session_id':'s','episode_id':'e','actor_instance_id':'i','control_epoch':3,'task_id':'wait','native_task_id':7}
 ref={'facing_direction':[0,1,0],'world_pose':[[0,0,1,0,0,0,1],[0,1,1,0,0,0,1]]}
 rows=[]
 for i in range(297,331):
  t=i/30;obs={'ready':True,'observation_sim_time':t,'facing_direction':[0,-1,0],'speed_mps':0.,'action':'Idle','native_task_id':7}
  rows.append({'actor_id':'a','actor_instance_id':'i','source_tick':i,'sim_time':t,'actual_observation':obs,
   'world_pose':[[0,0,1,0,0,-1,0],[0,-1,1,0,0,-1,0]],'task':{**before,'status':'running'}})
 r={'actor_id':'a','before':before,'after':copy.deepcopy(before),'sim_time':10.,'source_tick':300,'after_hold_sim_time':11.,
    'actual_observation':copy.deepcopy(rows[3]['actual_observation']),'after_hold_task':{**before,'status':'running'},
    'error':{'code':'MOTION_ENTRY_NOT_READY'}}
 return rows,ref,r


def test_refusal_preserves_actual_native_base_and_whole_owner_window():
 result=review_rejection(*fixture())
 assert result['verified'] and result['actual_entry_samples']==4 and result['actual_post_rejection_samples']==31


@pytest.mark.parametrize('fault',['new_epoch','new_instance','new_task','new_sdk','clip_started','not_ready',
 'wrong_heading','stale_observation','body_mismatch','entry_gap','post_gap','too_short','changed_receipt','terminal'])
def test_error_receipt_does_not_replace_actual_entry_and_continued_owned_idle(fault):
 rows,ref,r=copy.deepcopy(fixture())
 if fault=='new_epoch':r['after']['control_epoch']=4
 elif fault=='new_instance':rows[10]['actor_instance_id']='recreated'
 elif fault=='new_task':rows[10]['task']['task_id']='new'
 elif fault=='new_sdk':rows[10]['actual_observation']['native_task_id']=8
 elif fault=='clip_started':rows[10]['actual_observation']['action']='generated'
 elif fault=='not_ready':rows[10]['actual_observation']['ready']=False
 elif fault=='wrong_heading':rows[0]['actual_observation']['facing_direction']=[0,1,0]
 elif fault=='stale_observation':rows[10]['actual_observation']['observation_sim_time']=0
 elif fault=='body_mismatch':rows[0]['world_pose'][1][0]=.2
 elif fault=='entry_gap':rows.pop(1)
 elif fault=='post_gap':rows.pop(10)
 elif fault=='too_short':r['after_hold_sim_time']=10.5
 elif fault=='changed_receipt':r['source_tick']=301
 else:r['after_hold_task']['status']='cancelled'
 result=review_rejection(rows,ref,r)
 assert not result['verified'] and result['errors']


def test_absent_world_fences_and_boolean_speed_cannot_establish_owned_native_samples():
 rows,ref,r=copy.deepcopy(fixture());r['before']['session_id']=None;r['after']['session_id']=None
 for row in rows:row['task']['session_id']=None
 r['after_hold_task']['session_id']=None
 assert not review_rejection(rows,ref,r)['verified']
 rows,ref,r=fixture();rows[10]['actual_observation']['speed_mps']=False
 assert not review_rejection(rows,ref,r)['verified']


def test_positive_entry_independently_needs_actual_owned_idle_and_unbroken_world_heading():
 from audit_canonical_heading_rejection import review_admissions
 rows,ref,_=fixture();rows=rows[:4];task={**rows[0]['task'],'native_task_id':7}
 for r in rows:r.update(phase='canonical_admission_left_low',world_pose=ref['world_pose']);r['actual_observation']['facing_direction']=[0,1,0]
 admissions=[{'case':'left_low','precondition_task_ids':{'a':'wait'}}];registry={'actions':{'canonical_a__left_low':{'canonical_entry':ref}}}
 assert review_admissions(rows,admissions,{'wait':task},registry)['verified']
 rows[1]['actual_observation']['native_task_id']=8
 assert not review_admissions(rows,admissions,{'wait':task},registry)['verified']
 rows[1]['actual_observation']['native_task_id']=7;rows[1]['actual_observation']['facing_direction']=[0,-1,0]
 assert not review_admissions(rows,admissions,{'wait':task},registry)['verified']


def test_same_owned_body_reader_has_explicit_supported_heading_mode_without_relabelling_data():
 rows,ref,receipt=fixture()
 for r in rows:
  r['actual_observation']['facing_direction']=[0,1,0]
  r['world_pose']=copy.deepcopy(ref['world_pose'])
 receipt['actual_observation']=copy.deepcopy(rows[3]['actual_observation'])
 assert not review_rejection(rows,ref,receipt)['verified']
 assert review_rejection(rows,ref,receipt,expected_facing_y=1)['verified']
 with pytest.raises(ValueError):review_rejection(rows,ref,receipt,expected_facing_y=True)
