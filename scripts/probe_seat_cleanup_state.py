"""Own-stage Native seat-exit obstruction and read-only crowd-state probe."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace-root',required=True);p.add_argument('--source-root',required=True)
    p.add_argument('--run-id',required=True);p.add_argument('--case',required=True);p.add_argument('--gpu',type=int,default=3)
    args=p.parse_args();root=Path(args.workspace_root);source=Path(args.source_root);out=root/'runs'/args.run_id
    out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
    for name in ['src','configs','schemas']:shutil.copytree(source/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (snap/'reports').mkdir();shutil.copy2(source/'reports/capability_matrix.json',snap/'reports/capability_matrix.json')
    shutil.copy2(__file__,snap/'probe.py');shutil.copy2(args.case,snap/'case.json')
    (out/'source_manifest.json').write_text(json.dumps({str(p.relative_to(snap)):sha(p) for p in sorted(snap.rglob('*')) if p.is_file()},indent=2)+'\n')
    case=json.loads((snap/'case.json').read_text());assert case['duration_s']==45 and case['blocked_hold_s']==.5
    sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
    engine=backend=journal=recorder=stream=None;code=0
    try:
        import carb.settings,omni.kit.app,omni.usd
        from pxr import UsdGeom,Gf
        manager=omni.kit.app.get_app().get_extension_manager()
        for extension in ['omni.anim.behavior.core','omni.anim.navigation.core']:assert manager.set_extension_enabled_immediate(extension,True)
        from simpeople.backends.native.idle_profile import configure_idle_profile
        settings=carb.settings.get_settings();prefix='/exts/omni.anim.behavior.core/'
        for key,value in [('agentResponseTime',1/30),('agentResponseTimeMaxRandomOffset',0.),('navBlockedTimeout',3.)]:settings.set(prefix+key,value)
        startup=configure_idle_profile(settings,'default')
        from simpeople.backends.native.scene import build_scene
        from simpeople.backends.native.reservations import ReservationNativeBackend
        from simpeople.backends.native.recording import Recorder
        from simpeople.core.engine import Engine
        from simpeople.core.journal import Journal
        from simpeople.tools.runtime_contract import capture_runtime_contract
        omni.usd.get_context().new_stage();semantics=build_scene(False)
        backend=ReservationNativeBackend(root,semantics,False,config_dir=snap/'configs',capability_file=snap/'reports/capability_matrix.json')
        backend.enable_corridor_profile();backend.quality_sampling=True;backend.native_idle_profile=startup;backend.run_mode='audit';backend.api.set_random_seed(42)
        journal=Journal(out,{'scenario':'seat_cleanup_state_native','gpu':args.gpu,'width':1920,'height':1080})
        engine=Engine(backend,journal)
        def call(method,params=None):return engine.call(method,{'controller_id':'seat-cleanup-state-probe',**(params or {})})
        for actor in case['actors']:call('spawn',{'request_id':'spawn_'+actor['actor_id'],**actor})
        for _ in range(5):app.update()
        assert backend.nav.start_navmesh_baking_and_wait()
        timeline=backend.timeline;timeline.set_time_codes_per_second(30);timeline.set_end_time(100000);timeline.set_auto_update(False);timeline.set_play_every_frame(True);timeline.play()
        for _ in range(180):
            timeline.forward_one_frame();app.update()
            if all(backend.observe(a['handle']).get('ready') for a in engine.actors.values()):break
        assert all(backend.observe(a['handle']).get('ready') for a in engine.actors.values())
        capture_runtime_contract(root,out,backend=backend,engine=engine,extensions=[e for e in manager.get_extensions() if e.get('enabled') and 'omni.anim.' in e['id']])
        journal.write('sdk_idle_settings.json',{'startup_profile':startup,'requested_api_seed':42,'active_response':{prefix+k:settings.get(prefix+k) for k in ['agentResponseTime','agentResponseTimeMaxRandomOffset','navBlockedTimeout']}})
        camera=UsdGeom.Camera(backend.stage.GetPrimAtPath('/World/Camera'));camera.GetFocalLengthAttr().Set(28)
        UsdGeom.Xformable(camera).GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(10,-14,9),Gf.Vec3d(0,-1,1),Gf.Vec3d(0,0,1)).GetInverse())
        recorder=Recorder(out,(1920,1080),gpu_index=args.gpu);backend.recorder=recorder
        for _ in range(5):recorder.step(0)
        recorder.control({'mode':'start'});origin=timeline.get_current_time();engine.tick(origin)
        task=call('run_activity',{'actor_id':'operator','request_id':'seat_cycle','steps':case['operator_steps']})['task_id']
        witness=call('run_activity',{'actor_id':'witness','request_id':'witness','steps':case['witness_steps']})['task_id']
        def internal_fence():
            return copy.deepcopy((engine.actors,engine.tasks,engine.resources.snapshot(),engine.queues.snapshot(),
                                  backend.owner_routes,backend.routes,backend.grid.claims if backend.grid else {}))
        def public_fence():
            return copy.deepcopy({'sim_time':timeline.get_current_time(),'session_id':engine.session_id,'episode_id':engine.episode_id,
                    'controller_id':engine.controller_id,'controller_epoch':engine.controller_epoch,
                    'tasks':{t['task_id']:engine.public(t) for t in engine.tasks.values()},
                    'actors':{aid:{'actor_instance_id':a['actor_instance_id'],'control_epoch':a['control_epoch'],'task_id':a['task_id'],
                                   'native_task_id':int(backend.agent(a['handle']).get_action_task_id()),'seat':a['seat']} for aid,a in engine.actors.items()},
                    'resources':engine.resources.snapshot(),'queues':engine.queues.snapshot()})
        stream=(out/'cleanup_api_frames.jsonl').open('w');installed=False;cleared=False;blocked=[];controls=[]
        for index in range(1350):
            current=engine.tasks[task]
            if not installed and current['step_index']==2:
                result=call('move_prop',{'request_id':'obstruct_exit','prop_id':'movable_box','position_m':case['obstruct_position_m']})
                installed=True;controls.append({'kind':'obstruct_exit','sim_time':engine.sim_time,'result':result})
            recorder.step(1/30);engine.tick(timeline.get_current_time())
            identity={'source_tick':journal.frames,'video_frame':recorder.frames,'relative_sim_time':engine.sim_time-origin}
            recorder.capture(engine.sim_time,identity);journal.sample(engine,identity)
            internal=internal_fence();before=public_fence()
            state=call('crowd_state',{'details':True});repeat=call('crowd_state',{'details':True});after=public_fence()
            unchanged=internal==internal_fence() and before==after
            if not unchanged:journal.write('read_mutation_failure.json',{'before':before,'after':after})
            assert unchanged,'public read changed activity, lease, native task, route or simulation clock'
            actor=engine.actors['operator'];snapshot=next(a for a in state['actors'] if a['actor_id']=='operator')['seat_cleanup']
            repeated=next(a for a in repeat['actors'] if a['actor_id']=='operator')['seat_cleanup'];assert snapshot==repeated
            raw={k:copy.deepcopy(actor.get(k)) for k in ['handle','actor_instance_id','control_epoch','task_id','seat','seat_lease_token',
                  'release_seat_when_standing','cleanup_started','cleanup_target','cleanup_task','cleanup_retry_at','cleanup_error']}
            route=copy.deepcopy(backend.routes.get(actor.get('cleanup_task')))
            # JSON cannot represent tuple-keyed search history. Keep the raw
            # fields that independently identify this route and its admission.
            route={k:route.get(k) for k in ['handle','status','phase','native_task_id','goals','blocked_since','blocked_details']} if route else None
            record={'frame_identity':identity,'sim_time':engine.sim_time,'before':before,'after':after,'read_only_internal_unchanged':unchanged,
                    'crowd_state':state,'operator_cleanup_raw':raw,'exit_route_raw':route,
                    'operator_observation':backend.observe(actor['handle']),
                    'body_bindings':{aid:{'native_actor_prim_path':a['handle'],'traffic_body_instance_id':backend.instances[a['handle']]['traffic_instance_id']} for aid,a in engine.actors.items()}}
            if snapshot.get('phase')=='exit_wait':
                record['actual_claims']={owner:sorted(map(list,cells)) for owner,cells in backend.grid.claims.items()}
                record['actual_actor_positions_m']=copy.deepcopy(backend.positions)
            stream.write(json.dumps(record,allow_nan=False)+'\n')
            if installed and not cleared:
                obs=record['operator_observation']
                if snapshot.get('phase')=='exit_wait' and backend.is_standing(actor['handle'],obs) and obs['speed_mps']<.15:blocked.append(engine.sim_time)
                else:blocked.clear()
                if len(blocked)>=16 and blocked[-1]-blocked[0]>=case['blocked_hold_s']-1e-7:
                    assert snapshot['remaining_sim_s']>0,'do not unblock after the original cleanup deadline'
                    result=call('move_prop',{'request_id':'clear_exit','prop_id':'movable_box','position_m':case['clear_position_m']})
                    cleared=True;controls.append({'kind':'clear_exit','sim_time':engine.sim_time,'result':result,
                                               'observed_blocked_times':list(blocked),'cleanup_deadline_sim_time':snapshot['deadline_sim_time']})
        stream.close();stream=None
        actor=engine.actors['operator'];end=call('get_state');passed=bool(installed and cleared and engine.tasks[task]['status']=='succeeded'
              and engine.tasks[witness]['status']=='running' and not actor.get('release_seat_when_standing') and actor['seat'] is None)
        journal.write('seat_cleanup_api_acceptance.json',{'measurement_completed':True,'functional_expected_matched':passed,
                      'controls':controls,'operator_task':engine.public(engine.tasks[task]),'witness_task':engine.public(engine.tasks[witness]),
                      'final_crowd_state':call('crowd_state',{'details':True}),'final_state':end,
                      'scope':'Public Engine crowd-state integration on existing Native bodies. No MCP transport or whole-workload/rig/catalog qualification.'})
        journal.write('completed.json',{'harness_completed':True,'functional_expected_matched':passed,'frames':recorder.frames,
                      'duration_s':engine.sim_time-origin,'production_source_installed':False})
        code=0 if passed else 2;print('SEAT_CLEANUP_API_DONE',passed,flush=True)
    except Exception:
        import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
    finally:
        if stream:stream.close()
        if recorder:recorder.close()
        if engine:
            for aid in list(engine.actors):engine.abort_actor(aid,'process_shutdown')
            backend.close();journal.finish(engine,exit_code=code)
        app.close(exit_code=code)
    return code


if __name__=='__main__':raise SystemExit(main())
