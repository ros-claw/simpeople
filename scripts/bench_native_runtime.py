"""Frozen workload / request-lifecycle evidence in the installed Isaac 6.2."""
import argparse,hashlib,importlib.util,json,os,shutil,sys,time,signal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);mode=p.add_mutually_exclusive_group(required=True);mode.add_argument('--case');mode.add_argument('--lifecycle',action='store_true');p.add_argument('--gpu',type=int,default=3);p.add_argument('--port',type=int,default=8872);p.add_argument('--source-root',default=str(ROOT));p.add_argument('--host-probe',action='store_true');p.add_argument('--policy-json')
p.add_argument('--diagnostic-idle-tags',choices=['default','basic','disabled'],default='default')
p.add_argument('--diagnostic-native-release-triggers','--diagnostic-native-fault-triggers',dest='diagnostic_native_release_triggers',action='store_true')
args=p.parse_args()
input_case=json.loads(Path(args.case).read_text()) if args.case else None
has_triggers=bool(input_case and any('trigger' in e for e in input_case.get('events',[])))
if has_triggers!=args.diagnostic_native_release_triggers:p.error('event-bound faults require --diagnostic-native-release-triggers and a trigger case')
if has_triggers:
    from native_fault_triggers import validate_triggers
    validate_triggers(input_case['events'],{a['actor_id'] for a in input_case['actors']})
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);source=Path(args.source_root).resolve();snap=out/'source_snapshot';snap.mkdir();
for name in ['src','configs','schemas']:
    shutil.copytree(source/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(snap/'reports').mkdir();shutil.copy2(source/'reports/capability_matrix.json',snap/'reports/capability_matrix.json')
shutil.copy2(__file__,snap/Path(__file__).name);sys.path.insert(0,str(snap/'src'));sys.argv=[sys.argv[0]]
harness=snap/'harness';harness.mkdir()
for helper in ['src/simpeople/core/workloads.py','src/simpeople/tools/runtime_contract.py','src/simpeople/backends/native/probe_scenes.py','src/simpeople/backends/native/idle_profile.py','src/simpeople/core/release_scene.py']:
    shutil.copy2(ROOT/helper,harness/Path(helper).name)
case=json.loads(Path(args.case).read_text()) if args.case else None
if has_triggers:shutil.copy2(ROOT/'scripts/native_fault_triggers.py',harness/'native_fault_triggers.py')
if case:(harness/'case.json').write_text(json.dumps(case,indent=2)+'\n')
if args.policy_json and case and case.get('runtime_policy'):raise ValueError('use a case policy or --policy-json, not both')
if case and case.get('runtime_policy'):(snap/'configs/runtime_policy.json').write_text(json.dumps(case['runtime_policy'],indent=2)+'\n')
if args.policy_json:shutil.copy2(args.policy_json,snap/'configs/runtime_policy.json')
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n')
(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));keep_running=True
def stop(*_):
    global keep_running
    keep_running=False
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});engine=journal=recorder=bridge=monitor=None;code=0
try:
    import omni.kit.app,omni.usd,omni.timeline,carb
    manager=omni.kit.app.get_app().get_extension_manager()
    for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:assert manager.set_extension_enabled_immediate(ext,True)
    settings=carb.settings.get_settings();settings.set('/exts/omni.anim.behavior.core/agentResponseTime',1/30);settings.set('/exts/omni.anim.behavior.core/agentResponseTimeMaxRandomOffset',0.);settings.set('/exts/omni.anim.behavior.core/navBlockedTimeout',3.)
    idle_key='/exts/omni.anim.behavior.core/idleAnimationTags';original_idle=settings.get(idle_key)
    startup_profile=None
    if args.diagnostic_idle_tags=='disabled':
        settings.set(idle_key,['']*len(original_idle or range(7)))
    else:
        idle_module=load(harness/'idle_profile.py','simpeople_probe_idle_profile')
        startup_profile=idle_module.configure_idle_profile(settings,args.diagnostic_idle_tags)
    (out/'sdk_idle_settings.json').write_text(json.dumps({
        'mode':args.diagnostic_idle_tags,'original_tags':original_idle,'active_tags':settings.get(idle_key),
        'agent_response_time_s':settings.get('/exts/omni.anim.behavior.core/agentResponseTime'),
        'agent_response_max_random_offset_s':settings.get('/exts/omni.anim.behavior.core/agentResponseTimeMaxRandomOffset'),
        'nav_blocked_timeout_s':settings.get('/exts/omni.anim.behavior.core/navBlockedTimeout'),
        'requested_api_seed':17,
        'startup_profile':startup_profile,
        'scope':'Dedicated workload diagnostic before agents/Play. Product defaults and workload/deadlines unchanged; a seed is not a deterministic-native guarantee.'
    },indent=2)+'\n')
    from simpeople.backends.native.scene import build_scene
    from simpeople.backends.native.environments import industrial_scene
    from simpeople.backends.native.adapter import NativeBackend
    from simpeople.backends.native.reservations import ReservationNativeBackend
    from simpeople.backends.native.recording import Recorder
    from simpeople.core.engine import Engine
    from simpeople.core.journal import Journal
    from simpeople.core.monitor import ResourceMonitor
    from simpeople.core.errors import SimPeopleError
    from simpeople.tools.bridge import Bridge
    work=load(harness/'workloads.py','simpeople.core.workloads')
    contract_module=load(harness/'runtime_contract.py','simpeople.tools.runtime_contract')
    # Scene revision is shared by both runtime versions, including B0 where
    # this new pure helper does not exist. It is not an execution-code patch.
    load(harness/'release_scene.py','simpeople.core.release_scene')
    probe_scenes=load(harness/'probe_scenes.py','simpeople.backends.native.probe_scenes')
    omni.usd.get_context().new_stage()
    scene_id=case['scene']['id'] if case else 'request_lifecycle'
    semantics=build_scene(False) if args.lifecycle else probe_scenes.narrow_traffic_probe_scene() if scene_id=='industrial_narrow_probe_v1' else probe_scenes.narrow_release_scene() if scene_id=='industrial_narrow_release_v2' else industrial_scene();kind=NativeBackend if args.lifecycle else ReservationNativeBackend
    if case:
        work.validate_case(case,allow_diagnostic_triggers=args.diagnostic_native_release_triggers)
        assert case['capture_profile']=='full','this evidence driver requires the full capture profile'
        actual_revision=hashlib.sha256(json.dumps(semantics,sort_keys=True).encode()).hexdigest()
        assert scene_id in {'industrial','industrial_narrow_probe_v1','industrial_narrow_release_v2'} and case['scene']['revision']==actual_revision,'frozen scene revision mismatch'
    backend=kind(ROOT,semantics,False,config_dir=snap/'configs',capability_file=snap/'reports/capability_matrix.json');backend.quality_sampling=True;backend.performance_optimized=True
    if not args.lifecycle:backend.enable_corridor_profile()
    backend.api.set_random_seed(17);journal=Journal(out,{'scenario':'request_lifecycle' if args.lifecycle else 'frozen_workload','warmup_wall_s':30,'gpu':args.gpu,'width':1920,'height':1080,'capture_profile':'full'});engine=Engine(backend,journal);bridge=Bridge(engine,args.port);monitor=ResourceMonitor(out,args.gpu)
    journal.write('asset_manifest.json',backend.assets)
    class Client:
        def call(self,method,params):return engine.call(method,{'controller_id':'runtimebench',**params})
    client=Client();actors=case['actors'] if case else [{'actor_id':'operator','spawn_anchor':[-5,-3,0]},{'actor_id':'witness','spawn_anchor':[-8,-2,0]}]
    triggers=None
    if has_triggers:
        trigger_module=load(harness/'native_fault_triggers.py','simpeople_diagnostic_fault_triggers')
        triggers=trigger_module.NativeReleaseTriggers(case['events'],[a['actor_id'] for a in actors])
        def trigger_context(handle,witness_id=None):
            aid=backend.actor_label(handle);actor=engine.actors[aid];route=backend.owner_routes.get(handle)
            task=engine.tasks.get(actor['task_id'],{})
            observation=backend.observe(handle)
            context={'session_id':engine.session_id,'episode_id':engine.episode_id,'actor_id':aid,
                'actor_instance_id':actor['actor_instance_id'],'control_epoch':actor['control_epoch'],
                'task_id':actor['task_id'],'agent':handle,'body_instance_id':backend.instances[handle]['traffic_instance_id'],
                'task_status':task.get('status'),'cancel_requested':task.get('cancel_requested'),
                'current_route_id':route,'route_native_task_id':backend.routes.get(route,{}).get('native_task_id'),
                'sdk_task_id':int(backend.agent(handle).get_action_task_id()),'position_m':observation['position_m'],
                'sim_time':engine.sim_time,'actual_observation':observation}
            local=backend.routes.get(route,{}).get('local_yield')
            if local:
                context['local_yield']={key:local[key] for key in ['native_task_id','body_generation','path_m','deadline_sim_time']}
            if witness_id:
                witness=engine.actors[witness_id];task=engine.tasks.get(witness['task_id'],{})
                context['witness']={'actor_id':witness_id,'actor_instance_id':witness['actor_instance_id'],
                    'task_id':witness['task_id'],'control_epoch':witness['control_epoch'],'status':task.get('status'),
                    'observation':backend.observe(witness['handle'])}
            return context
        native_handler=backend.on_event
        def observe_release(kind,**payload):
            native_handler(kind,**payload)
            if kind in {'traffic_tail_tracking','traffic_tail_released','traffic_local_yield_motion_observed'}:
                triggers.observe(kind,payload,trigger_context(payload['agent']),backend.grid.cell)
        backend.on_event=observe_release
    spawned={}
    for a in actors:spawned[a['actor_id']]=client.call('spawn',{'request_id':'spawn_'+a['actor_id'],**a})
    # Publish authored geometry to the native navigation extension before baking,
    # as in kit_main.py. An immediate bake sees an empty/unpublished stage.
    for _ in range(5):app.update()
    assert backend.nav.start_navmesh_baking_and_wait()
    if hasattr(backend,'segment'):
        import math
        for a in actors:
            point=backend.resolve_target(a['spawn_anchor']);path=backend.segment(point,backend.resolve_target('entrance'))
            assert path and math.dist(path[0],point)<=.3,('spawn anchor is not on the intended NavMesh',a['actor_id'],point)
    timeline=backend.timeline;timeline.set_time_codes_per_second(30);timeline.set_end_time(100000);timeline.set_auto_update(False)
    settings.set('/app/player/useFixedTimeStepping',True);timeline.set_play_every_frame(True);timeline.play()
    for _ in range(120):
        timeline.forward_one_frame();app.update()
        if all(backend.observe(a['handle']).get('ready') for a in engine.actors.values()):break
    assert all(backend.observe(a['handle']).get('ready') for a in engine.actors.values())
    contract=contract_module.capture_runtime_contract(ROOT,out,backend=backend,engine=engine,extensions=[e for e in manager.get_extensions() if e.get('enabled') and any(n in e['id'] for n in ['omni.anim.','replicator.agent'])])
    recorder=Recorder(out,(1920,1080),gpu_index=args.gpu);backend.recorder=recorder
    for _ in range(6):recorder.step(0)
    recorder.control({'mode':'start'});origin=timeline.get_current_time();engine.tick(origin);duration=30 if args.lifecycle else case['duration_s'];replay=work.WorkloadReplay(case,client,origin,allow_diagnostic_triggers=args.diagnostic_native_release_triggers) if case else None
    (out/'workload.json').write_text(json.dumps(case or {'scenario':'request_lifecycle','plan_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2));journal.write('scene_semantics.json',semantics)
    (out/'ready.json').write_text(json.dumps({'endpoint':f'http://127.0.0.1:{args.port}','origin_sim_time':origin,'session_id':engine.session_id,'episode_id':engine.episode_id}));print('NATIVE_BENCH_READY',args.run_id,flush=True)
    started=time.monotonic();journal.start_wall=journal.last_wall=started;last_replay=-1.;last_probe=0;results={};tasks={};commands=[];original_episode=engine.episode_id;original_instance=spawned.get('operator',{}).get('actor_instance_id');applied_events=set();checked=set();checkpoint_results=[]
    def invoke(label,method,params,expect_error=None):
        row={'label':label,'relative_sim_time':engine.sim_time-origin,'method':method,'params':params}
        try:row['result']=client.call(method,{'command_id':'native_lifecycle','attempt_id':'attempt1',**params})
        except SimPeopleError as err:row['error']=err.as_dict()
        if expect_error:assert row.get('error',{}).get('code')==expect_error,row
        else:assert 'error' not in row,row
        commands.append(row);return row.get('result')
    def matches_expectations():
        expected={r['request_case_id']:r for r in case['requests']}
        for row in replay.summary()['requests']:
            spec=expected[row['request_case_id']]
            if row['state']!=spec.get('expected_outcome','succeeded'):return False
            if 'expected_error_code' in spec and (row.get('error') or {}).get('code')!=spec['expected_error_code']:return False
            if 'expected_physical_stop' in spec and engine.tasks[row['task_id']].get('physical_stop_verified')!=spec['expected_physical_stop']:return False
        return True
    while app.is_running() and keep_running:
        elapsed=timeline.get_current_time()-origin
        if elapsed>=duration-1e-7:break
        bridge.drain()
        if replay and elapsed-last_replay>=.2-1e-7:replay.tick(elapsed);last_replay=elapsed
        if case:
            for event in case.get('events',[]):
                if event['event_id'] in applied_events or elapsed<event['at_s']:continue
                assert event['method'] in {'cancel','move_prop'} or (args.diagnostic_native_release_triggers and event.get('trigger',{}).get('kind') in {'native_local_yield_motion','activity_succeeded'} and event['method']=='run_activity'),'unsupported frozen fault operation'
                resolved=event['params'];trigger_proof=None
                if triggers:
                    trigger=event.get('trigger',{});context=trigger_context(engine.actors[trigger['actor_id']]['handle'],trigger['witness_actor_id']) if trigger.get('kind') in {'native_diagonal_release','native_local_yield_motion','activity_succeeded'} else None
                    decision=triggers.ready(event['event_id'],elapsed,context)
                    if decision is None:continue
                    resolved,trigger_proof=decision
                params={'request_id':case['case_id']+'-'+event['event_id'],'command_id':case['case_id'],'attempt_id':'fault',**resolved}
                receipt=client.call(event['method'],params);applied_events.add(event['event_id'])
                if triggers:triggers.applied(event['event_id'],elapsed,receipt=receipt,context=context)
                engine.event('benchmark_fault_applied',event_id=event['event_id'],scheduled_at_s=event['at_s'],actual_at_s=elapsed,method=event['method'],resolved_params=resolved,trigger_evidence=trigger_proof,result=receipt)
            for checkpoint in case.get('checkpoints',[]):
                if checkpoint['label'] in checked or elapsed<checkpoint['at_s']:continue
                checked.add(checkpoint['label']);row={'label':checkpoint['label'],'actual_at_s':elapsed,'state':engine.cmd_get_state({})}
                if checkpoint['kind']=='queue_exit_blocked':
                    actor=engine.actor(checkpoint['actor_id']);task=engine.tasks[actor['task_id']]
                    assert task['step_phase']=='serving' and task['blocked_details']['reason']=='no_free_egress'
                    assert engine.queues.members[checkpoint['resource_id']][0]==checkpoint['actor_id']
                else:raise ValueError('unknown checkpoint kind')
                row['passed']=True;checkpoint_results.append(row)
            if case.get('stop_when_complete') and matches_expectations() and len(applied_events)==len(case.get('events',[])) and len(checked)==len(case.get('checkpoints',[])):break
        if args.lifecycle:
            if last_probe==0:
                tasks['old']=invoke('operator_walk','run_activity',{'request_id':'walk_a','actor_id':'operator','steps':[{'action':'move_to','target':[4.7,2.6,0],'timeout_s':25}]})['task_id'];tasks['witness']=invoke('witness_walk','run_activity',{'request_id':'walk_b','actor_id':'witness','steps':[{'action':'move_to','target':[-8,5,0],'timeout_s':25}]})['task_id'];last_probe=1
            if last_probe==1 and elapsed>=1:
                before=tuple((engine.actors[a]['control_epoch'],engine.actors[a]['task_id']) for a in ['operator','witness'])
                invoke('conflicting_cancel_actor','cancel',{'request_id':'wrong_actor_cancel','actor_id':'witness','task_id':tasks['old']},'INVALID_REQUEST')
                assert before==tuple((engine.actors[a]['control_epoch'],engine.actors[a]['task_id']) for a in ['operator','witness'])
                assert not engine.tasks[tasks['old']]['cancel_requested'] and not engine.tasks[tasks['witness']]['cancel_requested']
                epoch=engine.controller_epoch;invoke('takeover','control_session',{'request_id':'takeover','controller_id':'other','action':'takeover','expected_epoch':epoch});invoke('take_back','control_session',{'request_id':'takeback','action':'takeover','expected_epoch':engine.controller_epoch});invoke('release','control_session',{'request_id':'release','action':'release','expected_epoch':engine.controller_epoch})
                before=(engine.controller_id,engine.controller_epoch);invoke('stale_rejection','move_to',{'request_id':'stale','controller_id':'intruder','session_id':'stale_session','actor_id':'operator','target':[0,0,0]},'SESSION_MISMATCH');assert (engine.controller_id,engine.controller_epoch)==before
                invoke('reacquire','control_session',{'request_id':'reacquire','action':'acquire'});last_probe=2
            if last_probe==2 and elapsed>=2.5:
                tasks['replacement']=invoke('replace_operator','run_activity',{'request_id':'replacement','actor_id':'operator','steps':[{'action':'move_to','target':[4.7,-3,0],'timeout_s':25}]})['task_id'];last_probe=3
            if last_probe==3 and elapsed>=3.5:invoke('cancel_operator','cancel',{'request_id':'cancel','task_id':tasks['replacement']});last_probe=4
            if last_probe==4 and elapsed>=18:
                old=client.call('get_state',{'task_id':tasks['old']});cancelled=client.call('get_state',{'task_id':tasks['replacement']});witness=client.call('get_state',{'task_id':tasks['witness']})
                assert old['status']=='cancelled' and old['error']['message']=='superseded';assert cancelled['status']=='cancelled' and cancelled.get('physical_stop_verified');assert witness['status']=='succeeded';assert engine.actors['witness']['task_id']==tasks['witness']
                results.update(old=old,cancelled=cancelled,witness=witness);retired_goal=list(cancelled['observation']['position_m']);reset={'request_id':'reset','episode_id':original_episode,'controller_epoch':engine.controller_epoch};first=invoke('reset','reset',reset);second=invoke('reset_retry','reset',reset);assert second.get('idempotent_replay') and first['episode_id']==second['episode_id']
                newer=invoke('same_name_respawn','spawn',{'request_id':'respawn','actor_id':'operator','spawn_anchor':[-5,-3,0]});assert newer['actor_instance_id']!=original_instance
                invoke('late_actor_binding','run_activity',{'request_id':'late_actor','actor_id':'operator','actor_instance_id':original_instance,'steps':[{'action':'wait','duration_s':1}]},'ACTOR_INSTANCE_MISMATCH');assert client.call('get_state',{'task_id':tasks['old']})['observation'] is None;last_probe=5
            if last_probe==5 and elapsed>=18.5:
                observation=backend.observe(engine.actors['operator']['handle'])
                if observation.get('ready'):
                    import math
                    error=math.dist(observation['position_m'][:2],[-5,-3])
                    old_path=spawned['operator']['prim_path'];old_agent=backend.api.get_agent(old_path);old_prim=backend.stage.GetPrimAtPath(old_path)
                    result={'ready':True,'requested_spawn_m':[-5,-3,0],'actual_observation':observation,'spawn_error_m':error,'original_prim_path':old_path,'new_prim_path':engine.actors['operator']['handle'],'old_instance':original_instance,'new_instance':engine.actors['operator']['actor_instance_id'],
                        'old_runtime_agent_present':old_agent is not None,'old_runtime_agent_enabled':bool(old_agent and old_agent.is_enabled()),'old_prim_valid':bool(old_prim),'old_prim_active':bool(old_prim and old_prim.IsActive()),'old_prim_has_behavior_api':bool(old_prim and 'BehaviorAgentAPI' in old_prim.GetAppliedSchemas())}
                    journal.write('post_respawn_native_state.json',result)
                    assert error<=.3,('same-name native actor retained its old pose',result)
                    assert result['original_prim_path']!=result['new_prim_path'],'native physical path must not alias the old SDK instance'
                    assert not result['old_runtime_agent_enabled'] and not result['old_prim_has_behavior_api'],'despawn left an enabled native agent behind'
                    assert not result['old_prim_active'],'despawn left an active native subtree behind'
                    bound=invoke('bound_partial_batch','batch',{'request_id':'bound_batch','operation':'run_activity','items':[
                        {'actor_id':'operator','actor_instance_id':result['new_instance'],'if_busy':'reject','on_blocked':'report','steps':[{'action':'wait','duration_s':1}]},
                        {'actor_id':'operator','actor_instance_id':original_instance,'steps':[{'action':'wait','duration_s':3}]}]})
                    assert bound['accepted']==1 and bound['rejected']==1 and bound['results'][1]['error']['code']=='ACTOR_INSTANCE_MISMATCH',bound
                    tasks['bound_batch']=bound['results'][0]['result']['task_id'];assert engine.actors['operator']['task_id']==tasks['bound_batch'];last_probe=6
            if last_probe==6 and engine.tasks[tasks['bound_batch']]['status']=='succeeded':
                results['bound_batch']=engine.public(engine.tasks[tasks['bound_batch']]);tasks['retired_point']=invoke('reach_retired_position','move_to',{'request_id':'retired_position','actor_id':'operator','target':retired_goal,'timeout_s':8})['task_id'];last_probe=7
            if last_probe==7 and engine.tasks[tasks['retired_point']]['status'] in {'succeeded','failed','cancelled'}:
                results['retired_position']=client.call('get_state',{'task_id':tasks['retired_point']});assert results['retired_position']['status']=='succeeded',results['retired_position'];last_probe=8
        before_step=time.monotonic();recorder.step(1/30);after_step=time.monotonic();engine.tick(timeline.get_current_time());after_engine=time.monotonic();identity={'source_tick':journal.frames,'relative_sim_time':timeline.get_current_time()-origin};recorder.capture(timeline.get_current_time(),identity);after_capture=time.monotonic();journal.sample(engine,identity)
        journal.sample_timings({'kit_and_render_s':after_step-before_step,'supervisor_s':after_engine-after_step,'rgb_and_encode_s':after_capture-after_engine,'journal_s':time.monotonic()-after_capture})
        if elapsed>=duration:break
    assert keep_running,'run interrupted'
    actual_elapsed=timeline.get_current_time()-origin
    if replay:
        replay.tick(actual_elapsed);journal.write('outcomes.json',replay.summary(actual_elapsed));(out/'workload.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in replay.trace));assert replay.summary(actual_elapsed)['conservation_passed']
        if case.get('finite',True) and not matches_expectations():code=2
        assert len(applied_events)==len(case.get('events',[])) and len(checked)==len(case.get('checkpoints',[]))
        journal.write('checkpoints.json',checkpoint_results)
    else:
        assert last_probe==8;journal.write('lifecycle_results.json',{'passed':True,'results':results,'commands':commands,'scope':'actual native moves, replacement, measured cancellation, takeover, reset retry, actual respawn root, old controller retirement, reachability of retired position and per-item incarnation fencing; no motion generation claim'})
    journal.measurement_end_wall=time.monotonic()
    journal.write('bench_timings.json',{name:{'samples':len(values),'median_s':sorted(values)[len(values)//2],
        'p95_s':sorted(values)[min(len(values)-1,int(.95*len(values)))]} for name,values in journal.timings.items() if values})
    journal.write('asset_manifest.json',backend.assets)
    journal.write('measurement_end_state.json',engine.cmd_get_state({}))
    journal.write('benchmark_done.json',{'completed':True,'time_s':timeline.get_current_time(),'event_cursor':engine.event_sequence});print('NATIVE_BENCH_DONE',args.run_id,flush=True)
    if args.host_probe:
        until=timeline.get_current_time()+90
        with (out/'host_trajectories.jsonl').open('w') as host_trace:
            while timeline.get_current_time()<until and not (out/'host_probe.done').exists():
                bridge.drain();recorder.step(1/30);engine.tick(timeline.get_current_time());recorder.capture(timeline.get_current_time())
                for aid,a in engine.actors.items():
                    host_trace.write(json.dumps({'actor_id':aid,'actor_instance_id':a.get('actor_instance_id'),'task_id':a['task_id'],'sim_time':engine.sim_time,'phase':'host_probe',**backend.observe(a['handle'])})+'\n')
        journal.write('host_probe_end_state.json',engine.cmd_get_state({}))
    journal.write('completed.json',{'passed':code==0,'harness_completed':True,'functional_expected_matched':matches_expectations() if replay else True,
        'source_root':str(source),'duration_s':actual_elapsed,'duration_limit_s':duration,'frames':recorder.frames,'runtime':contract['isaac_version'],'human_host_inference':False})
except Exception:
    import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
    if bridge:bridge.close()
    if monitor:monitor.close()
    if recorder:recorder.close()
    if engine:
        for aid in list(engine.actors):engine.abort_actor(aid,'process_shutdown')
        engine.backend.close();journal.finish(engine,exit_code=code)
    app.close(exit_code=code)
raise SystemExit(code)
