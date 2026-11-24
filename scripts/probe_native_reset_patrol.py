"""Repeated same-ID native patrol, with retired USD physics inspection.

No controller writes live roots/joints. One fixed-step Kit loop owns everything.
Use --source-root to compare frozen backend versions with this same harness.
"""
import argparse, hashlib, json, math, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--run-id', required=True)
p.add_argument('--source-root', default=str(ROOT))
p.add_argument('--gpu', type=int, default=3)
p.add_argument('--rounds', type=int, default=3)
p.add_argument('--seconds', type=int, default=30)
p.add_argument('--seed', type=int, default=42)
args = p.parse_args()
assert args.rounds >= 2 and args.seconds >= 20
out = ROOT/'runs'/args.run_id
out.mkdir(exist_ok=False)
snap = out/'source_snapshot'
snap.mkdir()
source = Path(args.source_root)
for name in ['src', 'configs', 'schemas']:
    shutil.copytree(source/name, snap/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
(snap/'reports').mkdir()
shutil.copy2(source/'reports/capability_matrix.json', snap/'reports/capability_matrix.json')
shutil.copy2(__file__, snap/Path(__file__).name)
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()}, indent=2)+'\n')
(out/'probe_config.json').write_text(json.dumps(vars(args), indent=2)+'\n')
sys.path.insert(0, str(snap/'src'))
sys.argv = [sys.argv[0]]
from isaacsim import SimulationApp
app = SimulationApp({'headless':True, 'active_gpu':args.gpu, 'multi_gpu':False, 'disable_viewport_updates':True, 'limit_cpu_threads':8})
engine = journal = recorder = None
code = 0
try:
    import carb, omni.kit.app, omni.usd
    from pxr import Usd, UsdGeom, UsdPhysics
    manager = omni.kit.app.get_app().get_extension_manager()
    for ext in ['omni.anim.behavior.core', 'omni.anim.navigation.core']:
        assert manager.set_extension_enabled_immediate(ext, True)
    settings=carb.settings.get_settings()
    settings.set('/exts/omni.anim.behavior.core/agentResponseTime',1/30)
    settings.set('/exts/omni.anim.behavior.core/agentResponseTimeMaxRandomOffset',0.0)
    settings.set('/exts/omni.anim.behavior.core/navBlockedTimeout',3.0)
    from simpeople.backends.native.environments import industrial_scene
    from simpeople.backends.native.reservations import ReservationNativeBackend
    from simpeople.backends.native.recording import Recorder
    from simpeople.core.engine import Engine
    from simpeople.core.journal import Journal
    from simpeople.tools.runtime_contract import capture_runtime_contract
    omni.usd.get_context().new_stage()
    semantics = industrial_scene()
    backend = ReservationNativeBackend(ROOT, semantics, False, config_dir=snap/'configs', capability_file=snap/'reports/capability_matrix.json')
    backend.enable_corridor_profile()
    backend.api.set_random_seed(args.seed)
    journal = Journal(out, {'scenario':'native_reset_patrol', 'gpu':args.gpu, 'warmup_wall_s':0})
    engine = Engine(backend, journal)
    counter = 0
    def call(method, params=None):
        global counter
        counter += 1
        return engine.call(method, {'controller_id':'reset-patrol-probe', 'request_id':f'probe_{counter}', **(params or {})})
    positions = {'a':[-15,-6,0], 'b':[-11,-6,0], 'c':[-7,-6,0], 'witness':[18,16,0]}
    def spawn():
        return {aid:call('spawn', {'actor_id':aid, 'spawn_anchor':point}) for aid, point in positions.items()}
    spawned = spawn()
    for _ in range(6):app.update()
    assert backend.nav.start_navmesh_baking_and_wait()
    timeline = backend.timeline
    timeline.set_time_codes_per_second(30)
    timeline.set_end_time(100000)
    timeline.set_auto_update(False)
    timeline.set_play_every_frame(True)
    timeline.play()
    for _ in range(120):
        timeline.forward_one_frame();app.update()
        if all(backend.observe(a['handle']).get('ready') for a in engine.actors.values()):break
    assert all(backend.observe(a['handle']).get('ready') for a in engine.actors.values())
    capture_runtime_contract(ROOT, out, backend=backend, engine=engine, extensions=[e for e in manager.get_extensions() if e.get('enabled') and 'omni.anim.' in e['id']])
    journal.write('runtime_settings.json', {k:settings.get('/exts/omni.anim.behavior.core/'+k) for k in ['agentResponseTime','agentResponseTimeMaxRandomOffset','navBlockedTimeout']})
    recorder = Recorder(out, (1920,1080), gpu_index=args.gpu)
    backend.recorder = recorder
    for _ in range(5):recorder.step(0)
    recorder.control({'mode':'start'})
    engine.tick(timeline.get_current_time())
    retired = []
    def inspect_retired():
        rows = []
        stage = backend.stage
        for path in retired:
            prim = stage.GetPrimAtPath(path)
            agent = backend.api.get_agent(path)
            physics = []
            if prim and prim.IsActive():
                for child in Usd.PrimRange(prim):
                    if child.HasAPI(UsdPhysics.CollisionAPI):
                        enabled = UsdPhysics.CollisionAPI(child).GetCollisionEnabledAttr().Get()
                        physics.append({'path':str(child.GetPath()), 'active':child.IsActive(), 'collision_enabled':enabled, 'type':child.GetTypeName()})
            rows.append({'path':path, 'prim_valid':bool(prim), 'prim_active':bool(prim and prim.IsActive()), 'sdk_present':agent is not None, 'sdk_enabled':bool(agent and agent.is_enabled()), 'active_colliders':physics})
        return rows
    rounds = []
    for repetition in range(args.rounds):
        if repetition:
            retired.extend(a['prim_path'] for a in spawned.values())
            call('reset', {'episode_id':engine.episode_id})
            journal.write(f'retired_immediate_{repetition}.json', inspect_retired())
            spawned = spawn()
            for _ in range(120):
                recorder.step(1/30);engine.tick(timeline.get_current_time())
                identity = {'source_tick':journal.frames, 'round':repetition+1, 'phase':'spawn_ready'}
                recorder.capture(timeline.get_current_time(), identity);journal.sample(engine, identity)
                if all(backend.observe(a['handle']).get('ready') for a in engine.actors.values()):break
            journal.write(f'retired_settled_{repetition}.json', inspect_retired())
        assert all(math.dist(backend.observe(engine.actors[a]['handle'])['position_m'][:2], positions[a][:2]) <= .3 for a in positions)
        tasks = {a:call('run_activity', {'actor_id':a, 'steps':[{'action':'wait','duration_s':3600}]})['task_id'] for a in ['a','b','c']}
        patrol = [s for _ in range(100) for s in [{'action':'move_to','target':[18,18,0],'timeout_s':60}, {'action':'move_to','target':[18,16,0],'timeout_s':60}, {'action':'wait','duration_s':2}]]
        tasks['witness'] = call('run_activity', {'actor_id':'witness', 'steps':patrol})['task_id']
        start = timeline.get_current_time()
        retargeted = False
        while timeline.get_current_time()-start < args.seconds-1e-7:
            if not retargeted and timeline.get_current_time()-start >= 4:
                for aid, point in [('a',[-15,-2,0]), ('b',[-11,-2,0])]:
                    tasks[aid] = call('move_to', {'actor_id':aid,'target':point,'timeout_s':60})['task_id']
                retargeted = True
            recorder.step(1/30);engine.tick(timeline.get_current_time())
            identity = {'source_tick':journal.frames,'round':repetition+1,'phase':'patrol'}
            recorder.capture(timeline.get_current_time(), identity);journal.sample(engine, identity)
        task_rows = {a:engine.public(engine.tasks[tid]) for a, tid in tasks.items()}
        no_ghosts = all(not r['sdk_enabled'] and not any(c['collision_enabled'] for c in r['active_colliders']) for r in inspect_retired())
        passed = task_rows['witness']['status']=='running' and task_rows['witness']['step_index']>=6 and all(task_rows[a]['status']=='succeeded' for a in ['a','b']) and no_ghosts
        result = {'round':repetition+1, 'passed':passed, 'tasks':task_rows, 'retired':inspect_retired(), 'positions':{a:backend.observe(v['handle'])['position_m'] for a,v in engine.actors.items()}}
        rounds.append(result)
        journal.write('rounds.json', rounds)
        print('RESET_PATROL_ROUND', repetition+1, passed, task_rows['witness']['status'], task_rows['witness']['step_index'], 'retired_active_colliders', sum(len(r['active_colliders']) for r in inspect_retired()), flush=True)
    passed = all(r['passed'] for r in rounds)
    journal.write('completed.json', {'harness_completed':True,'passed':passed,'rounds':len(rounds),'passed_rounds':sum(r['passed'] for r in rounds),'frames':recorder.frames,'scope':'Same-ID repeated reset, actual native patrol/tasks and retired physics USD inspection; not a full T2 or T8 release matrix.'})
    code = 0 if passed else 2
except Exception:
    import traceback
    traceback.print_exc()
    (out/'failed.txt').write_text(traceback.format_exc())
    code = 1
finally:
    if recorder:recorder.close()
    if engine:
        for aid in list(engine.actors):engine.abort_actor(aid, 'process_shutdown')
        engine.backend.close()
    if journal and engine:journal.finish(engine, process_exit_code=code)
    app.close(exit_code=code)
raise SystemExit(code)
