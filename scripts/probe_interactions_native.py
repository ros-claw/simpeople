"""Own-stage native registry, live revision invalidation and witness probe."""
import argparse,hashlib,json,shutil,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);p.add_argument('--port',type=int,default=8881);p.add_argument('--layout',choices=['industrial','room'],default='industrial');p.add_argument('--gestures',action='store_true');p.add_argument('--minimal-sampling',action='store_true')
p.add_argument('--workspace-root',default=str(ROOT));p.add_argument('--source-root');p.add_argument('--handoff')
p.add_argument('--discovery',action='store_true',help='Unverified room gestures; never writes a strict gesture acceptance file')
p.add_argument('--startup-profile',choices=['sdk-default','product-default'],default='sdk-default')
args=p.parse_args();ROOT=Path(args.workspace_root).resolve();source=Path(args.source_root or ROOT).resolve()
if args.discovery and not (args.gestures and args.layout=='room'):p.error('discovery requires room layout and gestures')
if args.handoff and args.layout!='room':p.error('handoff requires room layout')
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir()
(out/'probe_config.json').write_text(json.dumps(vars(args),indent=2)+'\n')
for name in ['src','configs','schemas']:shutil.copytree(source/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(snap/'reports').mkdir();shutil.copy2(source/'reports/capability_matrix.json',snap/'reports/capability_matrix.json');shutil.copy2(__file__,snap/Path(__file__).name)
if args.layout=='room':
    (snap/'harness').mkdir();shutil.copy2(Path(args.handoff) if args.handoff else ROOT/'examples/interaction_room_handoff.json',snap/'harness/interaction_room_handoff.json')
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n')
sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
engine=journal=recorder=bridge=gesture_stream=None;code=0
try:
    import omni.kit.app,omni.usd
    startup=None;settings=None
    from pxr import UsdGeom,Gf
    manager=omni.kit.app.get_app().get_extension_manager()
    for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:assert manager.set_extension_enabled_immediate(ext,True)
    if args.startup_profile=='product-default':
        import carb.settings
        from simpeople.backends.native.idle_profile import configure_idle_profile
        settings=carb.settings.get_settings();prefix='/exts/omni.anim.behavior.core/'
        for key,value in [('agentResponseTime',1/30),('agentResponseTimeMaxRandomOffset',0.),('navBlockedTimeout',3.)]:settings.set(prefix+key,value)
        startup=configure_idle_profile(settings,'default')
    from simpeople.backends.native.environments import industrial_scene
    from simpeople.backends.native.scene import build_scene,mesh_box
    from simpeople.backends.native.reservations import ReservationNativeBackend
    from simpeople.backends.native.recording import Recorder
    from simpeople.core.engine import Engine
    from simpeople.core.journal import Journal
    from simpeople.core.errors import SimPeopleError
    from simpeople.tools.bridge import Bridge
    from simpeople.tools.runtime_contract import capture_runtime_contract
    omni.usd.get_context().new_stage();sem=industrial_scene() if args.layout=='industrial' else build_scene(False);stage=omni.usd.get_context().get_stage()
    station_id='work_00';seat_id='seat_00';station_prim='/World/Workstations/Desk_0';moved_position=[-13.8,7,.55];operator_spawn=[-14,5.7,0];witness_spawn=[10,-5,0];witness_goal=[15,-5,0];bay_position=[-18,15,0]
    if args.layout=='room':
        handoff=json.loads((snap/'harness/interaction_room_handoff.json').read_text());sem.update(handoff['locations'])
        stage.GetRootLayer().customLayerData={'simpeople_scene_id':handoff['scene_id'],'simpeople_scene_revision':handoff['revision']}
        mesh_box(stage,'/Room/Counter',[-4,4,.6],[2,1.2,1.2],[.4,.3,.2])
        station_id='room_work';seat_id='chair_01';station_prim='/World/Workbench';moved_position=[6,3,.55];operator_spawn=[4.7,2.6,0];witness_spawn=[-5,-3,0];witness_goal=[-5,2,0];bay_position=[-6,6,0]
        shutil.copy2(snap/'harness/interaction_room_handoff.json',out/'scene_handoff.json')
    marker=UsdGeom.Xform.Define(stage,'/World/RegistryProbe/Activity');marker.AddTranslateOp().Set(Gf.Vec3d(*bay_position))
    sem['probe_bay']={'kind':'activity_bay','prim_path':str(marker.GetPath()),'clip':'uninstalled_probe_clip','clearance_radius_m':1.5,'capacity':1}
    backend=ReservationNativeBackend(ROOT,sem,args.discovery,config_dir=snap/'configs',capability_file=snap/'reports/capability_matrix.json');backend.enable_corridor_profile();backend.quality_sampling=not args.minimal_sampling
    if startup:
        backend.native_idle_profile=startup;backend.api.set_random_seed(42)
    journal=Journal(out,{'scenario':'interaction_registry_native','gpu':args.gpu,'width':1920,'height':1080,'warmup_wall_s':30});engine=Engine(backend,journal);bridge=Bridge(engine,args.port)
    if startup:journal.write('sdk_idle_settings.json',{'startup_profile':startup,'active_response':{prefix+k:settings.get(prefix+k) for k in ['agentResponseTime','agentResponseTimeMaxRandomOffset','navBlockedTimeout']},'requested_api_seed':42})
    def call(method,params=None):return engine.call(method,{'controller_id':'registry-probe',**(params or {})})
    def fence(aid):
        actor=engine.actors[aid];agent=backend.agent(actor['handle'])
        gesture=backend.instances[actor['handle']].get('gesture',{})
        return {'controller_id':engine.controller_id,'controller_epoch':engine.controller_epoch,'task_count':len(engine.tasks),
                'actor_instance_id':actor['actor_instance_id'],'control_epoch':actor['control_epoch'],'task_id':actor['task_id'],
                'actual_native_action_task_id':int(agent.get_action_task_id()),
                'owned_gesture_ids':{k:gesture.get(k) for k in ['native_task_id','return_task_id','cancelled_return_task_id','base_task_id']}}
    call('spawn',{'request_id':'operator','actor_id':'operator','spawn_anchor':operator_spawn})
    call('spawn',{'request_id':'witness','actor_id':'witness','asset_id':'female_adult_business_02','spawn_anchor':witness_spawn})
    for _ in range(5):app.update()
    assert backend.nav.start_navmesh_baking_and_wait()
    timeline=backend.timeline;timeline.set_time_codes_per_second(30);timeline.set_end_time(100000);timeline.set_auto_update(False);timeline.set_play_every_frame(True);timeline.play()
    for _ in range(120):
        timeline.forward_one_frame();app.update()
        if all(backend.observe(a['handle']).get('ready') for a in engine.actors.values()):break
    assert all(backend.observe(a['handle']).get('ready') for a in engine.actors.values())
    contract=capture_runtime_contract(ROOT,out,backend=backend,engine=engine,extensions=[e for e in manager.get_extensions() if e.get('enabled') and 'omni.anim.' in e['id']])
    recorder=Recorder(out,(1920,1080),gpu_index=args.gpu);backend.recorder=recorder
    for _ in range(6):recorder.step(0)
    recorder.control({'mode':'start'});origin=timeline.get_current_time();engine.tick(origin)
    if args.gestures:gesture_stream=(out/'gesture_frame_states.jsonl').open('w')
    (out/'ready.json').write_text(json.dumps({'endpoint':f'http://127.0.0.1:{args.port}','origin_sim_time':origin,'interaction_target':station_id}));print('REGISTRY_READY',flush=True)
    initial=call('list_interactions');kinds={r['kind'] for r in initial['interactions']};assert kinds=={'seat','queue','workstation','activity_bay'},kinds
    station=next(r for r in initial['interactions'] if r['semantic_id']==station_id);old_revision=station['geometry_revision']
    preflight=call('validate_interaction',{'actor_id':'operator','action':'wait','target':station_id,'revision':old_revision});assert preflight['valid'] and not preflight['reservation_acquired']
    bay=call('validate_interaction',{'actor_id':'operator','action':'custom_action','target':'probe_bay'});assert not bay['valid']
    first=call('run_activity',{'request_id':'first','actor_id':'operator','steps':[{'action':'wait','duration_s':5,'resource_id':station_id,'interaction_revision':old_revision}]})['task_id']
    witness=call('move_to',{'request_id':'witness_move','actor_id':'witness','target':witness_goal,'timeout_s':15})['task_id']
    moved=False;restarted=False;busy=None;fresh=None;new_revision=None;stale_error=None;stale_fences=None
    gesture_data={};gesture_head=gesture_hand=None;gesture_stale=None
    while timeline.get_current_time()-origin<(16 if args.gestures else 12)-1e-7:
        bridge.drain();elapsed=timeline.get_current_time()-origin
        if busy is None and elapsed>=.3:
            busy=call('validate_interaction',{'actor_id':'witness','action':'wait','target':station_id});assert not busy['valid'] and any(e['code']=='RESOURCE_BUSY' for e in busy['errors'])
        if not moved and elapsed>=1:
            prim=stage.GetPrimAtPath(station_prim);UsdGeom.Xformable(prim).GetOrderedXformOps()[0].Set(Gf.Vec3d(*moved_position));moved=True
            updated=call('list_interactions',{'target':station_id})['interactions'][0];new_revision=updated['geometry_revision'];assert new_revision!=old_revision
            assert call('list_interactions',{'target':seat_id})['interactions'][0]['geometry_revision']==next(r['geometry_revision'] for r in initial['interactions'] if r['semantic_id']==seat_id)
            engine.event('interaction_probe_geometry_changed',old_revision=old_revision,new_revision=new_revision,prim_path=str(prim.GetPath()))
        if moved and not restarted and elapsed>=1.5:
            state=call('get_state',{'task_id':first});assert state['status']=='failed' and state['error']['code']=='TARGET_STALE',state
            before=(engine.controller_id,engine.controller_epoch,len(engine.tasks))
            before_fence=fence('operator')
            try:call('run_activity',{'request_id':'stale','actor_id':'operator','steps':[{'action':'wait','duration_s':1,'resource_id':station_id,'interaction_revision':old_revision}]})
            except SimPeopleError as error:stale_error=error.as_dict();assert error.code=='TARGET_STALE'
            else:raise AssertionError('stale geometry accepted')
            assert before==(engine.controller_id,engine.controller_epoch,len(engine.tasks))
            stale_fences={'before':before_fence,'after':fence('operator')};assert stale_fences['before']==stale_fences['after']
            assert not engine.resources.owners
            fresh=call('run_activity',{'request_id':'fresh','actor_id':'operator','steps':[{'action':'wait','duration_s':2,'resource_id':station_id,'interaction_revision':new_revision}]})['task_id'];restarted=True
        if args.gestures and elapsed>=4 and gesture_head is None:
            from simpeople.backends.native.gestures import observe as gesture_observe
            obs=gesture_observe(backend,engine.actors['operator']['handle']);head=obs['joints_m']['Head'];shoulder=obs['joints_m']['RightArm'];f=obs['facing_direction'];root=obs['position_m']
            group='/World/RegistryProbe/GestureStation';UsdGeom.Xform.Define(stage,group)
            for tag,point in [('Look',[head[i]+f[i] for i in range(3)]),('Palm',[shoulder[0]+f[0]*.3,shoulder[1]+f[1]*.3,root[2]+1.2])]:
                UsdGeom.Xform.Define(stage,group+'/'+tag).AddTranslateOp().Set(Gf.Vec3d(*point))
            sem['gesture_station']={'kind':'workstation','prim_path':group,'approach':list(root),'allowed_actions':['head_look','reach_hand'],
                'look_prim_path':group+'/Look','palm_right_prim_path':group+'/Palm','capacity':1}
            target=call('list_interactions',{'target':'gesture_station'})['interactions'][0];gesture_revision=target['geometry_revision']
            gesture_data['head_preflight']=call('validate_interaction',{'actor_id':'operator','target':'gesture_station','revision':gesture_revision,'action':'head_look'})
            result=gesture_data['head_preflight']
            if args.discovery:
                assert not result['valid'] and result['errors'] and all(e['code']=='ACTION_UNVERIFIED' for e in result['errors']),result
            else:assert result['valid'],gesture_data
            gesture_head=call('run_activity',{'request_id':'bound_head','actor_id':'operator','steps':[{'action':'head_look','target':target['anchors']['look']['position_m'],'duration_s':.6,'timeout_s':8,'resource_id':'gesture_station','interaction_revision':gesture_revision}]})['task_id']
        if gesture_head and engine.tasks[gesture_head]['status']=='succeeded' and gesture_hand is None:
            gesture_data['hand_preflight']=call('validate_interaction',{'actor_id':'operator','target':'gesture_station','revision':gesture_revision,'action':'reach_hand','hand':'right'})
            result=gesture_data['hand_preflight']
            if args.discovery:
                assert not result['valid'] and result['errors'] and all(e['code']=='ACTION_UNVERIFIED' for e in result['errors']),result
            else:assert result['valid'],gesture_data
            gesture_hand=call('run_activity',{'request_id':'bound_hand','actor_id':'operator','steps':[{'action':'reach_hand','hand':'right','target':target['anchors']['palm_right']['position_m'],'duration_s':.6,'timeout_s':8,'resource_id':'gesture_station','interaction_revision':gesture_revision}]})['task_id']
        if gesture_hand and engine.tasks[gesture_hand]['status']=='succeeded' and gesture_stale is None:
            palm=stage.GetPrimAtPath(group+'/Palm');op=UsdGeom.Xformable(palm).GetOrderedXformOps()[0];position=op.Get();op.Set(position+Gf.Vec3d(.05,0,0))
            before=(engine.controller_epoch,engine.actors['operator']['control_epoch'],engine.actors['operator']['task_id'])
            before_fence=fence('operator')
            try:call('run_activity',{'request_id':'old_palm','actor_id':'operator','steps':[{'action':'reach_hand','hand':'right','target':target['anchors']['palm_right']['position_m'],'duration_s':.6,'resource_id':'gesture_station','interaction_revision':gesture_revision}]})
            except SimPeopleError as error:gesture_stale=error.as_dict();assert error.code=='TARGET_STALE'
            else:raise AssertionError('changed palm anchor accepted with old revision')
            assert before==(engine.controller_epoch,engine.actors['operator']['control_epoch'],engine.actors['operator']['task_id'])
            gesture_data['stale_anchor_fences']={'before':before_fence,'after':fence('operator')};assert gesture_data['stale_anchor_fences']['before']==gesture_data['stale_anchor_fences']['after']
        recorder.step(1/30);engine.tick(timeline.get_current_time());identity={'source_tick':journal.frames,'relative_sim_time':timeline.get_current_time()-origin};recorder.capture(timeline.get_current_time(),identity);journal.sample(engine,identity)
        if gesture_stream:
            actor=engine.actors['operator'];instance=backend.instances[actor['handle']];state=instance.get('gesture',{})
            owned={k:state[k] for k in ['native_task_id','return_task_id','cancelled_return_task_id','base_task_id'] if state.get(k) is not None}
            gesture_stream.write(json.dumps({'frame_identity':identity,'sim_time':engine.sim_time,'actor_id':'operator',
                'actor_instance_id':actor['actor_instance_id'],'session_id':engine.session_id,'episode_id':engine.episode_id,
                'control_epoch':actor['control_epoch'],'task_id':actor['task_id'],'native_actor_prim_path':actor['handle'],
                'traffic_body_instance_id':instance['traffic_instance_id'],'owned':{k:{'native_task_id':tid,'actual_status':backend.task_state(actor['handle'],tid)} for k,tid in owned.items()}})+'\n')
    if gesture_stream:gesture_stream.close();gesture_stream=None
    assert engine.tasks[fresh]['status']=='succeeded' and engine.tasks[witness]['status']=='succeeded' and not engine.resources.owners
    if args.gestures:
        assert gesture_stale and engine.tasks[gesture_head]['status']=='succeeded' and engine.tasks[gesture_hand]['status']=='succeeded'
        result={**gesture_data,'head_task':engine.public(engine.tasks[gesture_head]),'hand_task':engine.public(engine.tasks[gesture_hand]),'old_anchor_error':gesture_stale}
        if args.discovery:journal.write('bound_gesture_discovery.json',{'measurement_completed':True,'strict_catalog_verified':False,**result})
        else:journal.write('bound_gesture_acceptance.json',{'passed':True,**result})
        states=[]
        for line in (out/'events.jsonl').open():
            event=json.loads(line)
            if event['kind'] in {'native_gesture_started','native_gesture_return_started'}:
                aid=next(aid for aid,a in engine.actors.items() if a['handle']==event['agent']);actor=engine.actors[aid]
                states.append({'actor_id':aid,'actor_instance_id':actor['actor_instance_id'],'agent':actor['handle'],
                               'native_task_id':event['native_task_id'],'kind':event['kind'],
                               'actual_status':backend.task_state(actor['handle'],event['native_task_id'])})
        journal.write('gesture_owned_task_states.json',{'sim_time':engine.sim_time,'states':states,
                      'remaining_gesture_owners':[aid for aid,a in engine.actors.items() if backend.instances[a['handle']].get('gesture')],
                      'resource_snapshot':engine.resources.snapshot()})
    journal.write('registry_acceptance.json',{'passed':True,'initial':initial,'initial_preflight':preflight,'busy_preflight':busy,'unsupported_bay':bay,
        'old_revision':old_revision,'new_revision':new_revision,'stale_error':stale_error,'stale_revision_fences':stale_fences,'bound_task':engine.public(engine.tasks[first]),'fresh_task':engine.public(engine.tasks[fresh]),'witness_task':engine.public(engine.tasks[witness]),'bound_head_hand_verified':bool(args.gestures and not args.discovery),'bound_head_hand_execution_completed':bool(args.gestures),'gesture_scope':('discovery only; no catalog qualification' if args.discovery else 'default asset at explicit anchors; two-asset qualification is separate') if args.gestures else None})
    journal.write('asset_manifest.json',backend.assets);journal.write('measurement_end_state.json',engine.cmd_get_state({}));journal.write('benchmark_done.json',{'completed':True,'time_s':engine.sim_time,'event_cursor':engine.event_sequence})
    journal.write('completed.json',{'passed':True,'harness_completed':True,'functional_expected_matched':True,'duration_s':timeline.get_current_time()-origin,'frames':recorder.frames,'unverified_gesture_discovery':args.discovery,'strict_catalog_verified':bool(args.gestures and not args.discovery)})
    print('REGISTRY_PROBE_DONE',flush=True)
except Exception:
    import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
    if gesture_stream:gesture_stream.close()
    if bridge:bridge.close()
    if recorder:recorder.close()
    if engine:
        for aid in list(engine.actors):engine.abort_actor(aid,'process_shutdown')
        engine.backend.close();journal.finish(engine,exit_code=code)
    app.close(exit_code=code)
raise SystemExit(code)
