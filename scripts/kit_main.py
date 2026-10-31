"""Dedicated Isaac process. Never imports Kit in controller Python."""
import argparse
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
import sys
import time
import traceback
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
parser=argparse.ArgumentParser()
parser.add_argument('--scenario',default='single_life_cycle')
parser.add_argument('--people',type=int,default=1);parser.add_argument('--seed',type=int,default=42)
parser.add_argument('--asset-id',default='default')
parser.add_argument('--gpu',type=int,default=3);parser.add_argument('--port',type=int,default=8768)
parser.add_argument('--width',type=int);parser.add_argument('--height',type=int)
parser.add_argument('--mode',choices=['interactive','generation','audit','experimental'],default='generation')
parser.add_argument('--duration',type=float);parser.add_argument('--run-id')
parser.add_argument('--camera',choices=['overview','follow','seat_side','gait_side'],default='overview')
parser.add_argument('--traffic-profile',choices=['native','segmented','corridor'],default='segmented')
parser.add_argument('--quality-audit',action='store_true')
parser.add_argument('--capture-profile',choices=['full','no_encode','render_only','none'],default='full')
parser.add_argument('--warmup-wall-s',type=float,default=30)
parser.add_argument('--measure-wall-s',type=float)
parser.add_argument('--performance-profile',choices=['baseline','optimized'],default='optimized')
parser.add_argument('--tracy',action='store_true')
parser.add_argument('--encoder-threads',type=int)
parser.add_argument('--cpu-threads',type=int,choices=range(1,65),default=8)
parser.add_argument('--renderer-profile',choices=['default','ampere_retrace'],default='default')
parser.add_argument('--cinematic-config')
parser.add_argument('--custom-actions',action='store_true',help='Import configured local clips through the native Behavior pipeline')
for name in ['serve','no-video','allow-unverified','realtime','visible']:parser.add_argument('--'+name,action='store_true')
args=parser.parse_args()
production_config=json.loads(Path(args.cinematic_config).read_text()) if args.cinematic_config else None
if production_config and (args.scenario!='industrial_life' or args.capture_profile!='full' or args.serve):
    parser.error('cinematic production uses standalone industrial_life and full capture')
from simpeople.core.modes import resolve_mode
for key,value in resolve_mode(args.mode,args.width,args.height,args.quality_audit).items():setattr(args,key,value)
if args.no_video:args.capture_profile='none'
if args.people<1 or args.people>100:parser.error('people must be between 1 and 100')
run_id=args.run_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
if not run_id.replace('-','').replace('_','').isalnum():parser.error('invalid run ID')
directory=ROOT/'runs'/run_id;directory.mkdir(parents=True,exist_ok=False)
SNAPSHOT=directory/'source_snapshot'
sources={}
for base in ['src','scripts','configs','extensions','schemas','skills']:
    for path in (ROOT/base).rglob('*'):
        if not path.is_file() or path.suffix not in {'.py','.json','.toml','.md'}:continue
        data=path.read_bytes();relative=path.relative_to(ROOT);saved=SNAPSHOT/relative
        saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(data)
        sources[str(relative)]=hashlib.sha256(data).hexdigest()
capability_data=(ROOT/'reports/capability_matrix.json').read_bytes()
(SNAPSHOT/'reports').mkdir(parents=True,exist_ok=True)
(SNAPSHOT/'reports/capability_matrix.json').write_bytes(capability_data)
sys.path.insert(0,str(SNAPSHOT/'src'))
(directory/'manifest.json').write_text(json.dumps({'source_sha256':sources,
    'asset_cache_manifest':'../../reports/asset_cache_manifest.json','scenario':args.scenario,'seed':args.seed},indent=2))
(directory/'bootstrap.json').write_text(json.dumps({'pid':__import__('os').getpid(),'run_id':run_id}))
if production_config:(directory/'production_config.json').write_text(json.dumps(production_config,ensure_ascii=False,indent=2))
sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':not args.visible,'active_gpu':args.gpu,'multi_gpu':False,
                   'profiler_backend':['tracy'] if args.tracy else [],
                   'width':args.width,'height':args.height,'limit_cpu_threads':args.cpu_threads,
                   'disable_viewport_updates':not args.visible})
engine=journal=bridge=recorder=monitor=frame_file=app_subscription=director=None
keep_running=True
def stop(*_):
    global keep_running
    keep_running=False
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
exit_code=0
try:
    import carb
    import omni.kit.app
    import omni.usd
    import omni.timeline
    import omni.replicator.core as rep
    manager=omni.kit.app.get_app().get_extension_manager()
    trace_api=None
    if args.tracy:
        manager.set_extension_enabled_immediate('omni.kit.profiler.tracy',True)
        from omni.kit.profiler.tracy import start_tracy_profiling
        start_tracy_profiling()
        trace_api=carb.profiler.acquire_profiler_interface(plugin_name='carb.profiler-tracy.plugin')
        trace_api.ensure_thread()
        trace_api.set_capture_mask(1)
        journal_trace_metadata={'run_id':run_id,'pid':__import__('os').getpid(),'interface':'carb.profiler-tracy.plugin',
                              'python_profiler_active':carb.profiler.is_profiler_active(),'capture_mask':trace_api.get_capture_mask(),
                              'manual_zone_api':'carb.profiler.begin_with_location'}
        (directory/'trace_metadata.json').write_text(json.dumps(journal_trace_metadata,indent=2))
    def trace_begin(name):
        carb.profiler.begin_with_location(1,name,name,__file__,1)
    for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:
        if not manager.set_extension_enabled_immediate(ext,True):raise RuntimeError('cannot load '+ext)
    # The SDK defaults throttle the crowd solver to 0.3–0.4 seconds. Keep
    # navigation response at the same 30 Hz as the animation/simulation clock.
    settings=carb.settings.get_settings()
    settings.set('/exts/omni.anim.behavior.core/agentResponseTime',1/30)
    settings.set('/exts/omni.anim.behavior.core/agentResponseTimeMaxRandomOffset',0.0)
    settings.set('/exts/omni.anim.behavior.core/navBlockedTimeout',3.0)
    from simpeople.backends.native.scene import build_scene
    from simpeople.backends.native.environments import industrial_scene,asset_validation_scene,gait_quality_scene
    from simpeople.backends.native.adapter import NativeBackend
    from simpeople.backends.native.reservations import ReservationNativeBackend
    from simpeople.backends.native.recording import Recorder
    from simpeople.core.journal import Journal
    from simpeople.core.engine import Engine
    from simpeople.core.monitor import ResourceMonitor
    from simpeople.core.quality import QualityAudit
    from simpeople.tools.bridge import Bridge
    omni.usd.get_context().new_stage()
    asset_pool=['default']+[a['asset_id'] for a in json.loads((SNAPSHOT/'configs/assets.json').read_text()).get('assets',[])] if (SNAPSHOT/'configs/assets.json').exists() else ['default']
    slots=None
    if args.scenario in {'asset_pool_validation','appearance_contact_sheet'}:
        asset_pool=asset_pool[:args.people]
        semantics,slots=asset_validation_scene(len(asset_pool),args.scenario=='appearance_contact_sheet')
    elif args.scenario=='industrial_life':
        if production_config:
            from simpeople.backends.native.production_art import shift_change_scene
            semantics=shift_change_scene(directory,training=production_config.get('activity_profile')=='lively',audition=production_config['mode']=='audition')
        else:semantics=industrial_scene()
    elif args.scenario=='gait_quality_validation':semantics=gait_quality_scene()
    else:semantics=build_scene(False)
    backend_type=ReservationNativeBackend if args.scenario in {'industrial_life','native_avoidance','gait_quality_validation'} and args.traffic_profile!='native' else NativeBackend
    backend=backend_type(ROOT,semantics,args.allow_unverified,config_dir=SNAPSHOT/'configs',
                          capability_file=SNAPSHOT/'reports/capability_matrix.json')
    backend.quality_sampling=args.quality_audit
    backend.run_mode=args.mode;backend.render_profile={'width':args.width,'height':args.height,'capture_profile':args.capture_profile,
        'renderer_profile':args.renderer_profile,'rt2_retrace':settings.get('/rtx/pathtracing/cached/retrace')}
    backend.scene_id=args.scenario
    backend.scene_revision=hashlib.sha256(json.dumps({'semantics':semantics,'scene_source':sources.get('src/simpeople/backends/native/scene.py'),
        'environment_source':sources.get('src/simpeople/backends/native/environments.py')},sort_keys=True).encode()).hexdigest()
    backend.performance_optimized=args.performance_profile=='optimized'
    if args.custom_actions:
        from simpeople.backends.native.custom_actions import register
        register(backend,directory/'custom_actions')
    if args.traffic_profile=='corridor':
        if not hasattr(backend,'enable_corridor_profile'):raise RuntimeError('corridor profile is not implemented in this source revision')
        backend.enable_corridor_profile()
    backend.api.set_random_seed(args.seed)
    journal=Journal(directory,vars(args))
    monitor=ResourceMonitor(directory,args.gpu)
    engine=Engine(backend,journal)
    if production_config:
        from simpeople.backends.native.production import ShiftChangeDirector
        director=ShiftChangeDirector(engine,production_config,directory)
    quality=QualityAudit(engine.event,broad_phase=backend.performance_optimized)
    journal.write('environment.json',{'isaac_version':(Path(__import__('os').environ['ISAAC_PATH'])/'VERSION').read_text().strip(),
        'default_viewport_updates':args.visible,'rgb_camera_count':0 if args.capture_profile=='none' else 1,
        'capture_profile':args.capture_profile,'traffic_profile':args.traffic_profile,'quality_sampling':args.quality_audit,
        'cpu_threads':args.cpu_threads,'renderer_profile':args.renderer_profile,'rt2_retrace':settings.get('/rtx/pathtracing/cached/retrace'),
        'capture_api':'rep.orchestrator.step(delta_time=1/30,wait_for_render=True)',
        'crowd_response_time_s':settings.get('/exts/omni.anim.behavior.core/agentResponseTime'),
        'crowd_response_random_offset_s':settings.get('/exts/omni.anim.behavior.core/agentResponseTimeMaxRandomOffset'),
        'native_blocked_timeout_s':settings.get('/exts/omni.anim.behavior.core/navBlockedTimeout'),
        'traffic_controller':backend_type.__name__,
        'overview_camera_profile':'industrial-wide-v2' if args.scenario=='industrial_life' else 'lab-v1',
        'overview_lens':{name:backend.stage.GetPrimAtPath('/World/Camera').GetAttribute(name).Get() for name in ['focalLength','horizontalAperture','verticalAperture']},
        'extensions':[e for e in manager.get_extensions() if any(k in e['id'] for k in ['omni.anim.','replicator.agent','behavior.tree'])]})
    journal.write('asset_manifest.json',backend.assets)
    journal.write('scene_semantics.json',semantics)
    if not args.serve and not director:
        if args.scenario=='native_avoidance':
            crossing=[([-8,0,0],[0,0,0]),([0,0,0],[-8,0,0]),([-4,-4,0],[-4,4,0]),([-4,4,0],[-4,-4,0])]
            for i,(position,_) in enumerate(crossing):
                engine.call('people.spawn',{'request_id':f'cross-spawn-{i}','actor_id':f'cross_{i}',
                            'spawn_anchor':position,'asset_id':args.asset_id})
        elif slots:
            for i,asset in enumerate(asset_pool):
                engine.call('people.spawn',{'request_id':f'asset-spawn-{i}','actor_id':f'asset_{i:02d}',
                            'spawn_anchor':slots[i]['spawn'],'asset_id':asset})
        elif args.scenario=='industrial_life':
            if not args.allow_unverified:
                gate=ROOT/'reports/phase_gates.json'
                if not gate.exists() or not json.loads(gate.read_text()).get('P3',{}).get('passed'):
                    raise RuntimeError('Industrial scenario requires the recorded P3 control gate; --allow-unverified is explicit engineering mode')
            verified=[a['asset_id'] for a in backend.assets if all(k in a.get('verified_actions',[]) for k in ['walk','run','sit','leave_seat'])
                      and a.get('appearance_status')!='discovered']
            engine.call('people.populate',{'request_id':'initial-population','count':args.people,
                        'seed':args.seed,'asset_pool':verified or ['default']})
        else:
            engine.call('people.spawn',{'request_id':'initial-spawn','actor_id':'person_001','spawn_anchor':'entrance','asset_id':args.asset_id})
    for _ in range(5):app.update()
    print('SIMPEOPLE_PHASE navmesh_bake',flush=True)
    if not backend.nav.start_navmesh_baking_and_wait():raise RuntimeError('NavMesh bake failed')
    if director:director.nav_check()
    timeline=backend.timeline;timeline.set_end_time(100000);timeline.set_time_codes_per_second(30)
    timeline.set_auto_update(False)
    carb.settings.get_settings().set('/app/player/useFixedTimeStepping',True)
    timeline.set_play_every_frame(True);timeline.play()
    for i in range(90):
        timeline.forward_one_frame();app.update()
        if not engine.actors or all(backend.observe(a['handle'])['ready'] for a in engine.actors.values()):break
    if engine.actors and not slots and not all(backend.observe(a['handle'])['ready'] for a in engine.actors.values()):
        raise RuntimeError('Behavior agent not created')
    if args.capture_profile!='none':
        print('SIMPEOPLE_PHASE recorder_setup',flush=True)
        recorder=Recorder(directory,(args.width,args.height),gpu_index=args.gpu,capture_profile=args.capture_profile,
                          encoder_threads=args.encoder_threads if args.encoder_threads is not None else (4 if backend.performance_optimized else 0));backend.recorder=recorder
        recorder.camera_mode=args.camera
        for _ in range(10):app.update()
        recorder.step(0.0)
        print('SIMPEOPLE_PHASE recorder_ready',flush=True)
        if director:
            # Native pre-roll uses the same synchronized capture step, with
            # recording still off. The opening frame already has moving people.
            for _ in range(30):
                engine.tick(timeline.get_current_time(),False)
                recorder.step(1/30)
        recorder.control({'mode':'start'})
    # Opening a stage initializes render defaults and can overwrite an earlier
    # setting. Apply this explicit quality tradeoff after the first render.
    if args.renderer_profile=='ampere_retrace':settings.set('/rtx/pathtracing/cached/retrace',.1)
    backend.render_profile['rt2_retrace']=settings.get('/rtx/pathtracing/cached/retrace')
    environment=json.loads((directory/'environment.json').read_text())
    environment['rt2_retrace_before_profile']=environment.get('rt2_retrace')
    environment['rt2_retrace']=backend.render_profile['rt2_retrace']
    journal.write('environment.json',environment)
    bridge=Bridge(engine,args.port)
    engine.tick(timeline.get_current_time(),False)
    initial_task=None;initial_tasks=[]
    if not args.serve and not director:
        if args.scenario=='native_avoidance':
            for i,(_,target) in enumerate(crossing):
                initial_tasks.append(engine.call('people.move_to',{'request_id':f'cross-move-{i}',
                    'actor_id':f'cross_{i}','target':target})['task_id'])
        elif args.scenario=='industrial_life':pass
        elif slots:
            for i,slot in enumerate(slots):
                aid=f'asset_{i:02d}'
                task={'request_id':f'asset-cycle-{i}','actor_id':aid,'steps':[
                    {'action':'move_to','target':slot['walk'],'gait':'walk'},
                    {'action':'move_to','target':slot['run'],'gait':'run'},
                    {'action':'sit','target':slot['seat'],'duration_s':2},
                    {'action':'leave_seat'},
                    {'action':'move_to','target':slot['spawn'],'gait':'walk'}]}
                if args.scenario=='appearance_contact_sheet':
                    task['steps']=[{'action':'look_at','target':'/World/Camera'}]
                initial_tasks.append(engine.call('people.run_activity',task)['task_id'])
        else:
            task=json.loads((SNAPSHOT/'configs'/f'{args.scenario}.json').read_text())
            initial_task=engine.call('people.run_activity',task)['task_id'];initial_tasks=[initial_task]
    if engine.controller_id=='legacy-local':
        engine.controller_id=None;engine.controller_epoch+=1
        engine.event('controller_bootstrap_released')
    ready={'run_id':run_id,'pid':__import__('os').getpid(),'endpoint':f'http://127.0.0.1:{args.port}',
           'status':'ready','allow_unverified':args.allow_unverified}
    journal.write('ready.json',ready);print('SIMPEOPLE_READY '+json.dumps(ready),flush=True)
    journal.write('runtime_settings.json',{'requested_cpu_threads':args.cpu_threads,'renderer_profile':args.renderer_profile,
        'renderer_mode':settings.get('/rtx/rendermode'),'rt2_retrace':settings.get('/rtx/pathtracing/cached/retrace'),
        'cpu_worker_settings':{key:settings.get(key) for key in ['/plugins/carb.tasking.plugin/threadCount',
            '/persistent/physics/numThreads','/plugins/omni.tbb.globalcontrol/maxThreadCount']}})
    omni.usd.get_context().get_stage().GetRootLayer().Export(str(directory/'stage.usda'))
    start_sim=timeline.get_current_time();start_wall=time.monotonic()
    journal.start_wall=journal.last_wall=start_wall
    journal.first_sim=start_sim
    default_duration=({10:600,30:900,50:600,100:120}.get(args.people,600) if args.scenario=='industrial_life' else 180)
    limit=args.duration or (600 if args.serve else default_duration)
    frame_events={'count':0,'dt_sum_s':0.0,'last_dt_s':None}
    def observe_app_update(event):
        dt=float(event.payload.get('dt',0.0))
        frame_events['count']+=1;frame_events['dt_sum_s']+=dt;frame_events['last_dt_s']=dt
    app_subscription=omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(observe_app_update,name='SimPeople frame identity')
    frame_file=(directory/'frame_identity.jsonl').open('w',buffering=1)
    trace_process=None;trace_log=None
    if args.measure_wall_s is not None:
        journal.start_wall=time.monotonic();journal.last_wall=journal.start_wall
    while app.is_running() and keep_running:
        frame_events.update(count=0,dt_sum_s=0.0,last_dt_s=None)
        if args.tracy and trace_process is None and time.monotonic()-journal.start_wall>=args.warmup_wall_s:
            import subprocess
            extension=Path(manager.get_extension_path_by_module('omni.kit.profiler.tracy'))
            import psutil
            trace_process_info=psutil.Process()
            connections=getattr(trace_process_info,'net_connections',None) or trace_process_info.connections
            listeners=[connection for connection in connections(kind='tcp') if connection.status==psutil.CONN_LISTEN and connection.laddr.port==8086]
            if not listeners:raise RuntimeError('Tracy listener 8086 is not owned by this Kit process; refusing an unverified capture')
            journal_trace_metadata.update(listener_verified_pid=__import__('os').getpid(),listener_port=8086,
                capture_start_wall_time=time.time(),capture_start_sim_time=timeline.get_current_time(),
                capture_start_mainloop_wall_s=time.monotonic()-journal.start_wall)
            journal.write('trace_metadata.json',journal_trace_metadata)
            trace_log=(directory/'tracy_capture.log').open('w')
            trace_process=subprocess.Popen([str(extension/'bin/capture'),'-a','127.0.0.1','-p','8086','-o',str(directory/'profile.tracy'),'-s','10','-f'],stdout=trace_log,stderr=subprocess.STDOUT)
        if args.tracy:trace_begin('SimPeople::commands')
        wall=time.monotonic();bridge.drain()
        if args.tracy:carb.profiler.end(1);trace_begin('SimPeople::KitRender')
        after_commands=time.monotonic()
        if director:
            director.before_step(recorder.frames)
            if director.needs_warmup and timeline.is_playing():
                before_warm=timeline.get_current_time()
                timeline.pause();timeline.commit();app.update()
                warm_agents={handle:backend.api.get_agent(handle) for handle in backend.instances}
                before_roots={handle:agent.get_world_translation() for handle,agent in warm_agents.items() if agent}
                for _ in range(2):recorder.step(0.)
                if abs(timeline.get_current_time()-before_warm)>1e-6:raise RuntimeError('camera warmup advanced simulation')
                motion=[]
                for handle,p in before_roots.items():
                    q=warm_agents[handle].get_world_translation()
                    motion.append(((p.x-q.x)**2+(p.y-q.y)**2+(p.z-q.z)**2)**.5)
                max_motion=max(motion,default=0)
                with (directory/'cinematic_warmups.jsonl').open('a') as warm_log:
                    warm_log.write(json.dumps({'frame':recorder.frames,'sim_time':before_warm,'max_native_root_motion_m':max_motion})+'\n')
                if max_motion>.001:raise RuntimeError('native root changed during frozen camera warmup')
                timeline.play();timeline.commit()
        elif recorder and recorder.camera_mode!='overview' and engine.actors:
            focus=engine.actors.get(recorder.focus_actor_id) or next(iter(engine.actors.values()))
            obs=backend.observe(focus['handle'])
            if obs['ready']:recorder.follow(obs['position_m'])
        if timeline.is_playing() and recorder:recorder.step(1/30)
        elif timeline.is_playing() and args.measure_wall_s is not None:
            rep.orchestrator.step(rt_subframes=1,delta_time=1/30,pause_timeline=False,wait_for_render=True)
        else:
            if timeline.is_playing():timeline.forward_one_frame()
            app.update()
        after_render=time.monotonic()
        if args.tracy:carb.profiler.end(1);trace_begin('SimPeople::supervisor')
        now_sim=timeline.get_current_time()
        if args.quality_audit:backend.observation_frame_id=journal.frames
        engine.tick(now_sim,not timeline.is_playing())
        quality.tick(now_sim,{aid:backend.observe(a['handle']) for aid,a in engine.actors.items()},
                     {a['asset_id']:a.get('runtime_radius_m',.25) for a in backend.assets},engine.episode_id)
        after_supervisor=time.monotonic()
        if args.tracy:carb.profiler.end(1);trace_begin('SimPeople::journal')
        identity={'sample':journal.frames,'video_frame':recorder.frames if recorder and recorder.pipe and timeline.is_playing() else None,
                  'video_file':getattr(recorder,'name',None),'recording_id':getattr(recorder,'recording_id',None),
                  'sim_time':now_sim,'timeline_before_step':start_sim if journal.frames==0 else journal.last_sim,
                  'app_updates':frame_events['count'],'app_dt_sum_s':frame_events['dt_sum_s'],'last_app_dt_s':frame_events['last_dt_s']}
        if args.tracy:carb.profiler.end(1);trace_begin('SimPeople::RGBencode')
        if recorder and timeline.is_playing():identity['video_frame']=recorder.capture(now_sim,identity)
        if director:director.record(identity)
        after_capture=time.monotonic()
        if args.tracy:carb.profiler.end(1);trace_begin('SimPeople::journal')
        journal.sample(engine,identity)
        after_journal=time.monotonic()
        if args.tracy:carb.profiler.end(1)
        frame_file.write(json.dumps(identity)+'\n')
        journal.sample_timings({'commands_s':after_commands-wall,'kit_and_render_s':after_render-after_commands,
            'supervisor_s':after_supervisor-after_render,'journal_s':after_journal-after_capture,
            'rgb_and_encode_s':after_capture-after_supervisor})
        if quality.report()['critical_count']>=3:
            exit_code=3;engine.event('quality_stop',reason='three geometry flags; inspect evidence before expanding');break
        if engine.population and any(a.get('suspended_reason')=='three_failed_cycles' for a in engine.population.assignments.values()):
            exit_code=4;engine.event('population_stop',reason='three consecutive failed cycles; inspect before expanding');break
        if initial_tasks and all(engine.tasks[tid]['status'] in {'succeeded','failed','cancelled'} for tid in initial_tasks):
            if any(engine.tasks[tid]['status']!='succeeded' for tid in initial_tasks):exit_code=2
            break
        if now_sim-start_sim>=limit:break
        if director and recorder.frames>=director.frames:break
        if args.measure_wall_s is not None and time.monotonic()-journal.start_wall>=args.warmup_wall_s+args.measure_wall_s:break
        if args.realtime or args.serve:
            time.sleep(max(0,1/30-(time.monotonic()-wall)))
    journal.measurement_end_wall=time.monotonic()
    journal.write('runtime_settings_end.json',{'renderer_profile':args.renderer_profile,
        'rt2_retrace':settings.get('/rtx/pathtracing/cached/retrace')})
    if args.renderer_profile=='ampere_retrace' and abs(settings.get('/rtx/pathtracing/cached/retrace')-.1)>1e-6:
        raise RuntimeError('requested retrace profile did not remain applied; reject this comparison')
    if trace_process:
        trace_process.wait(timeout=30);trace_log.close()
    frame_file.close();app_subscription=None
    if director:director.close();director=None
    journal.write('observation_counters.json',backend.observation_counters)
    journal.write('quality_audit.json',quality.report())
    journal.write('measurement_end_state.json',engine.cmd_get_state({}))
    if args.scenario=='appearance_contact_sheet' and recorder:
        from PIL import Image,ImageDraw,ImageFont
        previews=[]
        for aid,actor in engine.actors.items():
            obs=backend.observe(actor['handle'])
            if not obs['ready']:continue
            recorder.follow(obs['position_m'])
            for _ in range(3):app.update()
            file=f'portraits/{aid}.png';recorder.snapshot(file)
            previews.append({'actor_id':aid,'file':file,'asset_id':obs['asset_id'],
                'base_identity_id':obs['base_identity_id'],'appearance_id':obs['appearance_id'],
                'appearance_overrides_applied':obs['appearance_overrides_applied']})
        sheet=Image.new('RGB',(1440,540*((len(previews)+3)//4)),(240,242,244))
        draw=ImageDraw.Draw(sheet);font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
        for i,item in enumerate(previews):
            image=Image.open(directory/item['file']);w,h=image.size
            crop=image.crop((w//2-h//3,0,w//2+h//3,h)).resize((320,480))
            x=(i%4)*360+20;y=(i//4)*540
            sheet.paste(crop,(x,y));draw.text((x,y+482),item['base_identity_id'],fill=(20,30,40),font=font)
            draw.text((x,y+503),item['appearance_id'],fill=(20,30,40),font=font)
        sheet.save(directory/'asset_contact_sheet.jpg',quality=95)
        journal.write('appearance_audit.json',previews)
    if engine.population:journal.write('population.json',engine.population.assignments)
    journal.write('asset_manifest.json',backend.assets)
    journal.write('completion.json',{'scenario_task_id':initial_task,'scenario_task_ids':initial_tasks,'exit_code':exit_code,
        'stopped_by_signal':not keep_running,'capabilities_are_acceptance_verified':False})
except Exception:
    (directory/'error.txt').write_text(traceback.format_exc());traceback.print_exc();exit_code=1
finally:
    if frame_file and not frame_file.closed:frame_file.close()
    app_subscription=None
    if bridge:bridge.close()
    if monitor:monitor.close()
    if recorder:
        try:recorder.close()
        except Exception:traceback.print_exc();exit_code=1
    if engine:
        for aid in engine.actors:
            try:engine.abort_actor(aid,'process_shutdown')
            except Exception:traceback.print_exc()
        engine.backend.close()
        journal.finish(engine,exit_code=exit_code,video_timebase='simulation frames',
            camera_resolution=[args.width,args.height] if recorder else None,
            recorded_frames=recorder.frames if recorder and args.capture_profile=='full' else 0,
            rgb_readback_frames=recorder.frames if recorder and args.capture_profile in {'full','no_encode'} else 0,
            capture_profile=args.capture_profile,performance_profile=args.performance_profile)
    app.close()
raise SystemExit(exit_code)
