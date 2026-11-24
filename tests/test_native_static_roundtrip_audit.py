import copy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

spec=importlib.util.spec_from_file_location('native_static_review',Path(__file__).parents[1]/'scripts/audit_native_static_roundtrip.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def pose_row():
    return {'joint_paths':['Root','Root/Hand'],'world_pose':[[0,0,0,0,0,0,1],[0,.5,1,0,0,0,1]],
            'actual_observation':{'facing_direction':[0,-1,0]}}


def test_body_pose_invariant_to_world_translation_heading_and_quaternion_sign():
    ref=pose_row();actual=copy.deepcopy(ref);q=Rotation.from_euler('z',65,degrees=True)
    p=np.array(actual['world_pose'],dtype=float);p[:,:3]=q.apply(p[:,:3])+[4,7,0];p[:,3:]=-(q*Rotation.from_quat(p[:,3:])).as_quat()
    actual['world_pose']=p.tolist();actual['actual_observation']['facing_direction']=q.apply([0,-1,0]).tolist()
    result=m.compare(ref,actual)
    assert result['max_position_m']<1e-12 and result['max_angle_deg']<1e-10


@pytest.mark.parametrize('bad',['joint_order','short_array','nan','quat_norm','zero_heading'])
def test_invalid_actual_pose_rejected(bad):
    ref=pose_row();actual=copy.deepcopy(ref)
    if bad=='joint_order':actual['joint_paths'].reverse()
    elif bad=='short_array':actual['world_pose'].pop()
    elif bad=='nan':actual['world_pose'][1][0]=float('nan')
    elif bad=='quat_norm':actual['world_pose'][1][-1]=1.1
    else:actual['actual_observation']['facing_direction']=[0,0,0]
    with pytest.raises(ValueError):m.compare(ref,actual)


def test_angle_error_is_not_hidden_by_position_match():
    ref=pose_row();actual=copy.deepcopy(ref);actual['world_pose'][1][3:]=Rotation.from_euler('x',35,degrees=True).as_quat().tolist()
    result=m.compare(ref,actual)
    assert result['max_position_m']==0 and result['max_angle_deg']==pytest.approx(35)


@pytest.fixture
def experiment(tmp_path):
    run=tmp_path/'run';source=tmp_path/'source';bundle=tmp_path/'bundle'
    for p in [run,source,bundle,run/'source_snapshot']:p.mkdir(parents=True,exist_ok=True)
    write=lambda p,v:p.write_text(json.dumps(v)+'\n')
    probe=tmp_path/'probe.py';probe.write_text('# static diagnostic\n')
    manifest={'probe.py':m.sha(probe)};write(source/'source_manifest.json',{})
    (run/'source_snapshot/probe.py').write_bytes(probe.read_bytes());write(run/'source_manifest.json',manifest)
    reference=pose_row();registry={'actions':{},'roundtrip_sources':{'a':reference,'b':reference}}
    phases=[];poses=[];bodies=[];events=[];stamps=[]
    for index in range(120):
        sim=1+index/30;phase='rt_idle_'+('full' if index<60 else 'reference');ident={'source_tick':index}
        stamps.append({'frame':index,'frame_identity':ident,'sim_time':sim})
        for aid in ['a','b']:
            taskid=phase+aid;owner={'session_id':'s','episode_id':'e','actor_id':aid,'actor_instance_id':'i'+aid,'control_epoch':1 if index<60 else 2,'task_id':taskid}
            target='clip_'+taskid;registry['actions'][target]={'actor_source':aid}
            obs={'facing_direction':[0,-1,0],'position_m':[0,0,0],'ready':True,'observation_sim_time':sim,
                 'position_source':'BehaviorAgent.get_world_translation','native_task_id':1,'action':target,
                 'sim_paused':False,'root_changed_without_sim_time':False}
            poses.append({**reference,'actor_id':aid,'actor_instance_id':'i'+aid,'phase':phase,'source_tick':index+1,
                'sim_time':sim,'phase_time_s':.5+(index%60)/30,'activity_task_id':taskid,'task':{**owner,'status':'running'},'actual_observation':obs})
            bodies.append({**obs,**owner,'sim_time':sim,'frame_identity':ident,'traffic_body_instance_id':'body'+aid,'native_actor_prim_path':'/'+aid})
            if index in [0,60]:
                events.append({**owner,'kind':'native_task_bound','native_task_id':1})
                if aid=='a':phases.append({'name':phase,'tasks':[]})
                phases[-1]['tasks'].append({**owner,'status':'succeeded','steps':[{'action':'custom_action','target':target,'duration_s':3.,'timeout_s':10.}]})
    for name,values in [('video_timestamps.jsonl',stamps),('native_pose_history.jsonl',poses),('trajectories.jsonl',bodies),('events.jsonl',events)]:
        (run/name).write_text(''.join(json.dumps(x)+'\n' for x in values))
    write(run/'completed.json',{'harness_completed':True,'functional_expected_matched':True,'frames':120})
    write(run/'recording_metrics.json',{'frames_written':120,'empty_rgb_frames':0,'dropped_frames':0})
    write(run/'generated_native_acceptance.json',{'passed':True,'phases':phases})
    write(bundle/'actions.json',registry);write(bundle/'bundle_manifest.json',{'files_sha256':{'actions.json':m.sha(bundle/'actions.json')}})
    plan={'run_id':'run','model_requests_added':0,'source':str(source),'source_manifests':{str(source):m.sha(source/'source_manifest.json')},
          'argv':['python',str(probe)],'frozen_files':{str(probe):m.sha(probe),str(bundle/'actions.json'):m.sha(bundle/'actions.json')},'inputs':str(bundle),'native_cases':['idle']}
    path=tmp_path/'plan.json';write(path,plan)
    return run,path


def test_complete_independent_static_measurement(experiment):
    result=m.audit(*experiment)
    assert result['static_pose_measurements_verified'],result['errors']
    assert len(result['measurements'])==4
    assert result['qualified_generated_native_rigs']==[]


def test_one_actor_cannot_cover_a_missing_actor_in_another_phase(experiment):
    run,plan=experiment;p=run/'generated_native_acceptance.json';data=json.loads(p.read_text())
    data['phases'][0]['tasks'].pop();p.write_text(json.dumps(data))
    result=m.audit(run,plan)
    assert not result['static_pose_measurements_verified']
    assert result['errors']==['both declared actors required in every static phase']


@pytest.mark.parametrize('bad',['sdk','epoch','stale','body','phase','clock','pause','root','pose','missing','duplicate','angle'])
def test_actual_stream_faults_cannot_pass(experiment,bad):
    run,plan=experiment
    filename='native_pose_history.jsonl';rows=[json.loads(x) for x in (run/filename).open()]
    r=rows[10]
    if bad=='sdk':r['actual_observation']['native_task_id']=99
    elif bad=='epoch':r['task']['control_epoch']=99
    elif bad=='stale':r['actual_observation']['observation_sim_time']-=1/30
    elif bad=='body':r['actor_instance_id']='other'
    elif bad=='phase':r['phase']='unknown'
    elif bad=='clock':r['sim_time']+=.01
    elif bad=='pause':r['actual_observation']['sim_paused']=True
    elif bad=='root':r['world_pose'][0][0]=.1
    elif bad=='pose':r['world_pose'][1][0]=.1
    elif bad=='missing':rows[:]=[x for i,x in enumerate(rows) if i not in range(10,20)]
    elif bad=='duplicate':rows.insert(10,copy.deepcopy(r))
    else:r['world_pose'][1][3:]=Rotation.from_euler('y',30,degrees=True).as_quat().tolist()
    (run/filename).write_text(''.join(json.dumps(x)+'\n' for x in rows))
    result=m.audit(run,plan)
    assert not result['static_pose_measurements_verified'],result
