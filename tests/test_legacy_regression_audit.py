import copy
import importlib.util
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('legacy_review',Path(__file__).parents[1]/'scripts/audit_legacy_regression.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


@pytest.fixture
def steps():
    task = {'actor_id':'a','task_id':'t','session_id':'s','episode_id':'e',
            'actor_instance_id':'i','control_epoch':1,
            'steps':[{'action':'custom_action','target':'dance','duration_s':25,'timeout_s':40}]}
    def event(kind, cursor, when, **values):
        return {**task,'kind':kind,'cursor':cursor,'sim_time':when,**values}
    events = [event('custom_action_space_reserved',1,2,agent='/A',clip='dance',native_task_id=10),
              event('native_task_bound',2,2,backend_task_id=10,native_task_id=10),
              event('step_started',3,2,index=0,step=task['steps'][0].copy(),native_kind='custom_action',backend_task_id=10,native_task_id=10),
              event('step_ended',4,27.1,index=0,action='custom_action'),
              event('native_task_bound',5,27.2,native_task_id=None,backend_task_id='route-x'),
              event('step_started',6,27.2,index=1,native_kind='reservation_route'),
              event('native_task_bound',7,31,native_task_id=99,backend_task_id=99),
              event('step_started',8,31,index=2,native_kind='wait')]
    return {'a':task},[{'actor_id':'a','action':'dance'}],events,{'a':'/A'}


def test_later_move_and_wait_sdk_ids_are_not_custom_ids(steps):
    assert module.custom_step_bindings(*steps) == {'a':{10}}


@pytest.mark.parametrize('bad',['owner','epoch','session','step_owner','end_owner','reservation_body',
    'reservation_clip','reservation_session','changed_budget','later_wait','missing_end','duplicate_start',
    'retry_binding','duplicate_cursor','boolean_sdk','unbound','deadline','reservation_nan'])
def test_wrong_custom_step_lineage_is_rejected(steps,bad):
    tasks,cast,events,prims=steps
    if bad=='owner':events[1]['actor_instance_id']='other'
    elif bad=='epoch':events[1]['control_epoch']=2
    elif bad=='session':events[1]['session_id']='other'
    elif bad=='step_owner':events[2]['actor_instance_id']='other'
    elif bad=='end_owner':events[3]['episode_id']='other'
    elif bad=='reservation_body':events[0]['agent']='/other'
    elif bad=='reservation_clip':events[0]['clip']='other'
    elif bad=='reservation_session':events[0]['session_id']='other'
    elif bad=='changed_budget':events[2]['step']['timeout_s']=60
    elif bad=='later_wait':events[2]['native_kind']='wait'
    elif bad=='missing_end':events.pop(3)
    elif bad=='duplicate_start':events.append({**events[2],'cursor':9})
    elif bad=='retry_binding':events[4]['sim_time']=25
    elif bad=='duplicate_cursor':events[1]['cursor']=1
    elif bad=='boolean_sdk':events[2]['native_task_id']=True
    elif bad=='unbound':events[2]['backend_task_id']=99
    elif bad=='reservation_nan':events[0]['sim_time']=float('nan')
    else:events[3]['sim_time']=45
    with pytest.raises(ValueError):module.custom_step_bindings(*steps)


@pytest.fixture
def sample():
    tasks={a:{'actor_id':a,'session_id':'s','episode_id':'e','task_id':'t_'+a,'actor_instance_id':'i_'+a,
              'control_epoch':1,'status':'succeeded'} for a in ['clip','witness']}
    cast=[{'actor_id':'clip','action':'clip'}];times=[];cameras=[];rows=[]
    for i in range(61):
        ident={'source_tick':i,'video_frame':i,'relative_sim_time':(i+1)/30}
        times.append({'frame':i,'sim_time':5+i/30,'frame_identity':ident})
        cameras.append({'sim_time':5+i/30,'frame_identity':ident,'shot_actor_id':'clip'})
        for a in tasks:
            rows.append({**tasks[a],'frame_identity':ident,'sim_time':5+i/30,'observation_sim_time':5+i/30,
                'ready':True,'position_source':'BehaviorAgent.get_world_translation','position_m':[i*.03,0,0],
                'native_actor_prim_path':'/World/'+a,'traffic_body_instance_id':'body_'+a,
                'action':'clip' if a=='clip' else 'MoveWalk','native_task_id':1 if a=='clip' else 2,
                'joints_m':{'LeftFoot':[0,0,.05],'RightFoot':[0,0,.05]}})
    return tasks,cast,'witness',rows,times,cameras,{'clip':{1}}


def test_real_frame_count_fences_sdk_and_close_view(sample):
    result=module.coherent_streams(*sample)
    assert result['actor_count']==2 and result['frames_per_actor']==61
    assert result['continuous_close_view_clip_frames']=={'clip':61}
    assert result['max_displacement_from_first_actual_m']['witness']==pytest.approx(1.8)


@pytest.mark.parametrize('bad',['duplicate','missing','epoch','actor_instance','session','static_xform','body_recreated',
    'body_shared','stale','wrong_sdk','wrong_camera','missing_joint','false_success','frame_gap','boolean_frame','nan_clock'])
def test_invalid_native_evidence_never_passes(sample,bad):
    tasks,cast,witness,rows,times,cameras,bound=sample
    if bad=='duplicate':rows.append(copy.deepcopy(rows[0]))
    elif bad=='missing':rows.pop(20)
    elif bad=='epoch':rows[20]['control_epoch']=2
    elif bad=='actor_instance':rows[20]['actor_instance_id']='other'
    elif bad=='session':rows[20]['session_id']='other'
    elif bad=='static_xform':rows[20]['position_source']='UsdGeom.Xform'
    elif bad=='body_recreated':rows[20]['traffic_body_instance_id']='newbody'
    elif bad=='body_shared':
        for row in rows:row['traffic_body_instance_id']='same'
    elif bad=='stale':rows[20]['observation_sim_time']-=1/30
    elif bad=='wrong_sdk':bound['clip']={99}
    elif bad=='wrong_camera':cameras[20]['shot_actor_id']='witness'
    elif bad=='missing_joint':rows[20]['joints_m'].pop('LeftFoot')
    elif bad=='false_success':tasks['clip']['status']='accepted'
    elif bad=='frame_gap':times[20]['sim_time']+=.02
    elif bad=='nan_clock':rows[20]['observation_sim_time']=float('nan')
    else:times[0]['frame']=False
    with pytest.raises(ValueError):module.coherent_streams(*sample)
