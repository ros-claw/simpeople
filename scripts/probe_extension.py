"""Real existing-stage extension lifecycle and routed native movement acceptance."""
import argparse
import json
import math
from pathlib import Path
import sys
import time
from concurrent.futures import ThreadPoolExecutor
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'src'))
parser=argparse.ArgumentParser();parser.add_argument('--gpu',type=int,default=1);args=parser.parse_args()
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
report={'passed':False};pool=ThreadPoolExecutor(max_workers=1)
try:
    import carb
    import omni.kit.app
    import omni.timeline
    import omni.usd
    from pxr import Gf,UsdGeom
    from simpeople.backends.native.scene import build_scene
    from simpeople.tools.client import call
    manager=omni.kit.app.get_app().get_extension_manager()
    for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:manager.set_extension_enabled_immediate(ext,True)
    omni.usd.get_context().new_stage();sem=build_scene()
    stage=omni.usd.get_context().get_stage()
    UsdGeom.Xform.Define(stage,'/World/UserSentinel').AddTranslateOp().Set(Gf.Vec3d(2,3,4))
    for _ in range(10):app.update()
    import omni.anim.navigation.core as nav
    assert nav.acquire_interface().start_navmesh_baking_and_wait()
    timeline=omni.timeline.get_timeline_interface();timeline.set_auto_update(False)
    timeline.set_end_time(10000);timeline.set_time_codes_per_second(30);timeline.set_play_every_frame(True);timeline.play()
    for _ in range(10):timeline.forward_one_frame();app.update()
    baseline=stage.GetRootLayer().ExportToString();session=list(stage.GetSessionLayer().subLayerPaths)
    (root/'reports/extension_root_before.usda').write_text(baseline)
    original_edit=stage.GetEditTarget().GetLayer().identifier
    semantics_file=root/'reports/extension_test_semantics.json';semantics_file.write_text(json.dumps(sem))
    settings=carb.settings.get_settings();settings.set('/exts/rosclaw.simpeople/port',8770)
    settings.set('/exts/rosclaw.simpeople/semantics_file',str(semantics_file))
    manager.add_path(str(root/'extensions'))
    assert manager.set_extension_enabled_immediate('rosclaw.simpeople',True)
    def update():timeline.forward_one_frame();app.update()
    for _ in range(10):update()
    def invoke(method,params=None):
        future=pool.submit(call,'people.'+method,params or {},'http://127.0.0.1:8770')
        until=time.monotonic()+40
        while not future.done() and time.monotonic()<until:update()
        return future.result(timeout=1)
    inspection=invoke('inspect_scene');report['inspection']=inspection
    invoke('spawn',{'request_id':'gui-spawn','actor_id':'gui_worker','spawn_anchor':'entrance'})
    for _ in range(20):update()
    task=invoke('run_activity',{'request_id':'gui-route','actor_id':'gui_worker','steps':[
        {'action':'move_to','via':[[-5,-5,0],[5,-5,0]],'target':[5,0,0],'timeout_s':90}]})
    until=time.monotonic()+180
    while time.monotonic()<until:
        result=invoke('get_state',{'task_id':task['task_id']})
        if result['status'] in {'succeeded','failed','cancelled'}:break
        for _ in range(5):update()
    assert result['status']=='succeeded',result
    assert math.dist(result['observation']['position_m'][:2],[5,0])<.3
    report['routed_move_result']=result
    (root/'reports/extension_root_during.usda').write_text(stage.GetRootLayer().ExportToString())
    assert stage.GetRootLayer().ExportToString()==baseline,'user root layer changed'
    assert stage.GetEditTarget().GetLayer().identifier==original_edit
    report['root_layer_unchanged_during_control']=True
    namespace=inspection['managed_namespace'];assert stage.GetPrimAtPath(namespace)
    manager.set_extension_enabled_immediate('rosclaw.simpeople',False)
    for _ in range(5):update()
    report['session_sublayers_before']=session
    report['session_sublayers_after']=list(stage.GetSessionLayer().subLayerPaths)
    (root/'reports/extension_session_after.usda').write_text(stage.GetSessionLayer().ExportToString())
    assert not stage.GetPrimAtPath(namespace),'managed actors remain after unload'
    assert stage.GetRootLayer().ExportToString()==baseline
    assert list(stage.GetSessionLayer().subLayerPaths)==session
    assert stage.GetPrimAtPath('/World/UserSentinel')
    report.update(passed=True,unload_removed_only_owned_layer=True,user_sentinel_preserved=True)
    print('EXTENSION_LIFECYCLE_PASSED',flush=True)
except Exception:
    import traceback
    report['error']=traceback.format_exc();raise
finally:
    report['wall_time']=time.time()
    (root/'reports'/f'extension_lifecycle_{time.time_ns()}.json').write_text(json.dumps(report,indent=2))
    (root/'reports/extension_lifecycle.json').write_text(json.dumps(report,indent=2))
    pool.shutdown(wait=False);app.close()
