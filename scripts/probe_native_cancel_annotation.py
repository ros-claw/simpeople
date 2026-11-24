"""Raw SDK counterfactual: identical clip, neutral End versus zero-length End.

This does not exercise public cancellation or canonical entry admission. No live
pose writes, model requests, root teleporting or global Stop/Play are used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace-root',required=True);p.add_argument('--source-root',required=True)
    p.add_argument('--run-id',required=True);p.add_argument('--spec',required=True);p.add_argument('--gpu',type=int,default=3)
    args=p.parse_args();root=Path(args.workspace_root);source=Path(args.source_root);out=root/'runs'/args.run_id
    out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir()
    sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
    for name in ['src','configs','schemas']:
        shutil.copytree(source/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (snap/'reports').mkdir();shutil.copy2(source/'reports/capability_matrix.json',snap/'reports/capability_matrix.json')
    shutil.copy2(__file__,snap/'probe.py');shutil.copy2(args.spec,snap/'spec.json')
    spec=json.loads((snap/'spec.json').read_text());assert sha(spec['source_registry'])==spec['source_registry_sha256']
    assert spec['cancel_budget_s']==15 and spec['cancel_elapsed_s']==[1.5,13.,27.7]
    entries=spec['actions'];assert set(entries)=={'neutral_end','zero_end'}
    assert all(entries['neutral_end'][k]==entries['zero_end'][k] for k in ['clip','skeleton'])
    diag=snap/'diagnostic_configs';shutil.copytree(snap/'configs',diag)
    (diag/'custom_actions.json').write_text(json.dumps({'actions':entries},indent=2)+'\n')
    manifest={str(f.relative_to(snap)):sha(f) for f in sorted(snap.rglob('*')) if f.is_file()}
    (out/'source_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
    backend=engine=journal=recorder=stream=None;code=0
    try:
        import carb,carb.settings,omni.usd,omni.kit.app
        import numpy as np
        from pxr import UsdSkel,Usd,UsdGeom,Gf
        manager=omni.kit.app.get_app().get_extension_manager()
        for extension in ['omni.anim.behavior.core','omni.anim.navigation.core']:
            assert manager.set_extension_enabled_immediate(extension,True)
        settings=carb.settings.get_settings();prefix='/exts/omni.anim.behavior.core/'
        for key,value in [('agentResponseTime',1/30),('agentResponseTimeMaxRandomOffset',0.),('navBlockedTimeout',3.)]:settings.set(prefix+key,value)
        from simpeople.backends.native.idle_profile import configure_idle_profile
        startup=configure_idle_profile(settings,'basic')
        from simpeople.backends.native.scene import build_scene
        from simpeople.backends.native.reservations import ReservationNativeBackend
        from simpeople.backends.native.custom_actions import register
        from simpeople.backends.native.recording import Recorder
        from simpeople.core.engine import Engine
        from simpeople.core.journal import Journal
        from simpeople.tools.runtime_contract import capture_runtime_contract
        omni.usd.get_context().new_stage();semantics=build_scene(True)
        backend=ReservationNativeBackend(root,semantics,True,config_dir=diag,capability_file=snap/'reports/capability_matrix.json')
        backend.enable_corridor_profile();backend.quality_sampling=True;backend.api.set_random_seed(42);backend.native_idle_profile=startup
        from simpeople.core.asset_paths import resolve_asset_path
        inputs={resolve_asset_path(entry[k],root):sha(resolve_asset_path(entry[k],root)) for entry in entries.values() for k in ['clip','skeleton']}
        register(backend,out/'custom_actions')
        for path,digest in inputs.items():assert sha(path)==digest,'import mutated original source: '+path
        imported={}
        for aid in entries:
            files=list((out/'custom_actions/clips'/aid).glob('*.usd'));assert len(files)==1
            stage=Usd.Stage.Open(str(files[0]));animation=UsdSkel.Animation(stage.GetDefaultPrim())
            arrays={}
            for key,attr in [('translations',animation.GetTranslationsAttr()),('rotations',animation.GetRotationsAttr()),('scales',animation.GetScalesAttr())]:
                times=attr.GetTimeSamples();arrays[key+'_times']=np.asarray(times,dtype=float)
                if key=='rotations':
                    arrays[key]=np.asarray([[[*q.GetImaginary(),q.GetReal()] for q in attr.Get(t)] for t in times],dtype=float)
                else:arrays[key]=np.asarray([[list(v) for v in attr.Get(t)] for t in times],dtype=float)
            raw_path=out/(aid+'_imported_pose_arrays.npz');np.savez(raw_path,**arrays)
            imported[aid]={'file':str(files[0]),'sha256':sha(files[0]),'joint_paths':list(map(str,animation.GetJointsAttr().Get())),
                           'authored_pose_arrays_file':str(raw_path),'authored_pose_arrays_sha256':sha(raw_path),
                           'annotations':[{'tag':c.GetAttribute('tag').Get(),'start':c.GetAttribute('start').Get(),'end':c.GetAttribute('end').Get()}
                                          for c in animation.GetPrim().GetChildren() if c.HasAttribute('tag')]}
        journal=Journal(out,{'scenario':'sdk_cancel_annotation_diagnostic','gpu':args.gpu,'width':1920,'height':1080})
        engine=Engine(backend,journal)
        def call(method,params):return engine.call(method,{'controller_id':'cancel-annotation-diagnostic',**params})
        for aid,x,y in [('neutral_end',-3,-5.8),('zero_end',3,-5.8),('witness',-7,3)]:
            call('spawn',{'actor_id':aid,'asset_id':'default','spawn_anchor':[x,y,0],'request_id':'spawn_'+aid})
        for _ in range(5):app.update()
        assert backend.nav.start_navmesh_baking_and_wait()
        timeline=backend.timeline;timeline.set_time_codes_per_second(30);timeline.set_end_time(100000);timeline.set_auto_update(False);timeline.set_play_every_frame(True);timeline.play()
        for _ in range(180):
            timeline.forward_one_frame();app.update()
            if all(backend.observe(a['handle']).get('ready') for a in engine.actors.values()):break
        assert all(backend.observe(a['handle']).get('ready') for a in engine.actors.values())
        for aid in entries:backend.agent(engine.actors[aid]['handle']).idle(facing=carb.Float3(0,1,0))
        for _ in range(60):timeline.forward_one_frame();app.update()
        capture_runtime_contract(root,out,backend=backend,engine=engine,extensions=[e for e in manager.get_extensions() if e.get('enabled') and 'omni.anim.' in e['id']])
        journal.write('sdk_idle_settings.json',{'startup_profile':startup,'active_response':{prefix+k:settings.get(prefix+k) for k in ['agentResponseTime','agentResponseTimeMaxRandomOffset','navBlockedTimeout']},'requested_api_seed':42})
        journal.write('source_inputs_sha256.json',inputs);journal.write('asset_manifest.json',backend.assets)
        journal.write('actual_imported_annotations.json',{'actions':imported,'scope':'Actual imported UsdSkel sample arrays saved independently for CPU comparison; no array identity inferred from successful import.'})
        camera=UsdGeom.Camera(backend.stage.GetPrimAtPath('/World/Camera'));camera.GetFocalLengthAttr().Set(26)
        UsdGeom.Xformable(camera).GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(0,-18,6),Gf.Vec3d(0,-2,1),Gf.Vec3d(0,0,1)).GetInverse())
        recorder=Recorder(out,(1920,1080),gpu_index=args.gpu);backend.recorder=recorder
        for _ in range(5):recorder.step(0)
        recorder.control({'mode':'start'});origin=timeline.get_current_time();engine.tick(origin)
        witness=call('run_activity',{'actor_id':'witness','request_id':'witness','steps':[{'action':'move_to','target':[-7,y,0],'gait':'walk','timeout_s':25} for y in [-3,3]*40]})['task_id']
        skeletons={aid:next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(backend.stage.GetPrimAtPath(engine.actors[aid]['handle'])) if p.IsA(UsdSkel.Skeleton)) for aid in entries}
        names={aid:list(map(str,s.GetJointsAttr().Get())) for aid,s in skeletons.items()};assert all(len(v)==81 for v in names.values())
        stream=(out/'native_cancel_history.jsonl').open('w');latest={};trial_id=-1;phase='idle';retired={}
        def frame():
            recorder.step(1/30);engine.tick(timeline.get_current_time())
            ident={'source_tick':journal.frames,'video_frame':recorder.frames,'relative_sim_time':timeline.get_current_time()-origin}
            recorder.capture(engine.sim_time,ident);journal.sample(engine,ident)
            for aid in entries:
                actor=engine.actors[aid];handle=actor['handle'];agent=backend.agent(handle);obs=backend.observe(handle);pose=[]
                for index in range(81):
                    point=carb.Float3(0,0,0);q=carb.Float4(0,0,0,1);assert agent.get_joint_world_transform(index,point,q)
                    pose.append([*backend.to_public(point),q.x,q.y,q.z,q.w])
                row={'trial_id':trial_id,'phase':phase,'actor_id':aid,'actor_instance_id':actor['actor_instance_id'],
                     'session_id':engine.session_id,'episode_id':engine.episode_id,'control_epoch':actor['control_epoch'],
                     'native_actor_prim_path':handle,'traffic_body_instance_id':backend.instances[handle]['traffic_instance_id'],
                     'frame_identity':ident,'sim_time':engine.sim_time,'joint_paths':names[aid],'world_pose':pose,
                     'actual_observation':obs,'retired_native_task_id':retired.get(aid),
                     'retired_native_status':backend.task_state(handle,retired[aid]) if aid in retired else None}
                stream.write(json.dumps(row,allow_nan=False)+'\n');latest[aid]=row
        trials=[];aborted=False
        for trial_id,delay in enumerate(spec['cancel_elapsed_s']):
            phase='prepare';retired={}
            for aid in entries:backend.agent(engine.actors[aid]['handle']).idle(facing=carb.Float3(0,1,0))
            for _ in range(30):frame()
            anchors={aid:latest[aid] for aid in entries};began=engine.sim_time;phase='custom'
            for aid in entries:
                agent=backend.agent(engine.actors[aid]['handle']);retired[aid]=int(agent.custom_action(aid,duration=0.))
                assert retired[aid]>0
            for _ in range(round(delay*30)):frame()
            before={aid:latest[aid] for aid in entries};cancel_time=engine.sim_time;phase='cancel'
            for aid in entries:
                agent=backend.agent(engine.actors[aid]['handle'])
                assert agent.get_action_task_id()==retired[aid] and agent.get_task_name(retired[aid])==aid
                agent.cancel_task(retired[aid]);agent.idle()
            runs={aid:[] for aid in entries}
            for _ in range(round(spec['cancel_budget_s']*30)):
                frame()
                for aid in entries:
                    row=latest[aid];obs=row['actual_observation']
                    okay=(row['retired_native_status']!='running' and obs['action']=='Idle'
                          and obs['native_task_id']!=retired[aid] and obs['speed_mps']<.15)
                    if not okay:runs[aid].clear()
                    else:runs[aid].append(row['sim_time'])
                if all(len(v)>=16 and v[-1]-v[0]>=.5-1e-7 for v in runs.values()):break
            settled=all(len(v)>=16 and v[-1]-v[0]>=.5-1e-7 for v in runs.values())
            trials.append({'trial_id':trial_id,'requested_elapsed_s':delay,'started_sim_time':began,'cancel_sim_time':cancel_time,
                           'end_sim_time':engine.sim_time,'retired_native_ids':dict(retired),'anchors':anchors,
                           'before_cancel':before,'actual_idle_times':runs,'physical_stop_observed':settled})
            if not settled:aborted=True;break
        stream.close();stream=None
        for path,digest in inputs.items():assert sha(path)==digest,'original input mutated: '+path
        journal.write('cancel_trials.json',{'trials':trials,'remaining_trials_not_exercised':len(spec['cancel_elapsed_s'])-len(trials),
                      'witness_task':engine.public(engine.tasks[witness]),'aborted_after_physical_stop_failure':aborted,
                      'source_inputs_sha256':inputs,'scope':spec['scope']})
        journal.write('completed.json',{'harness_completed':True,'all_trials_exercised':not aborted and len(trials)==3,'frames':recorder.frames,
                      'duration_s':engine.sim_time-origin,'sdk_diagnostic_only':True,'native_quality_verified':False})
        print('CANCEL_ANNOTATION_DIAGNOSTIC_DONE',len(trials),flush=True)
    except Exception:
        import traceback;(out/'failed.txt').write_text(traceback.format_exc());traceback.print_exc();code=1
    finally:
        if stream:stream.close()
        if recorder:recorder.close()
        if engine:
            for aid in list(engine.actors):engine.abort_actor(aid,'process_shutdown')
            backend.close();journal.finish(engine,exit_code=code)
        app.close(exit_code=code)
    return code


if __name__=='__main__':raise SystemExit(main())
