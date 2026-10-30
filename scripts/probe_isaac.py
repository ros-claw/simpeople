"""P0 runtime probe. Run exclusively with the selected Isaac python.sh."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import traceback

parser = argparse.ArgumentParser()
parser.add_argument('--output', default='reports/p0')
parser.add_argument('--gpu', type=int, default=3)
args, kit_args = parser.parse_known_args()
out = Path(args.output).resolve()
out.mkdir(parents=True, exist_ok=True)
sys.argv = [sys.argv[0]] + kit_args
from isaacsim import SimulationApp
app = SimulationApp({'headless': True, 'active_gpu': args.gpu, 'multi_gpu': False,
                     'width': 960, 'height': 540, 'limit_cpu_threads': 8})
try:
    import carb
    import omni.kit.app
    import omni.kit.commands
    import omni.usd
    import omni.timeline
    from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdSkel
    mgr = omni.kit.app.get_app().get_extension_manager()
    for ext in ['omni.anim.behavior.core', 'omni.anim.navigation.core']:
        print('ENABLE', ext, mgr.set_extension_enabled_immediate(ext, True), flush=True)
    import omni.anim.behavior.core as bh
    import omni.anim.navigation.core as nav
    carb.settings.get_settings().set('/persistent/app/usd/muteUsdDiagnostics', False)
    extensions = [e for e in mgr.get_extensions() if any(k in e['id'] for k in
                  ['omni.anim.', 'replicator.agent', 'behavior.tree', 'behavior_tree_gen'])]
    (out / 'extensions.json').write_text(json.dumps(extensions, default=str, indent=2))
    api = bh.acquire_interface()
    for label, obj in [('behavior', api), ('navigation', nav.acquire_interface())]:
        (out / (label + '_api.txt')).write_text('\n\n'.join(
            f'{n}: {getattr(obj,n).__doc__}' for n in dir(obj) if not n.startswith('_')))
    omni.usd.get_context().new_stage()
    stage = omni.usd.get_context().get_stage()
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage, '/World').GetPrim())
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    # A polygon mesh is picked up by the navigation baker.
    floor = UsdGeom.Mesh.Define(stage, '/World/Floor')
    floor.CreatePointsAttr([(-10,-10,0),(10,-10,0),(10,10,0),(-10,10,0)])
    floor.CreateFaceVertexCountsAttr([4])
    floor.CreateFaceVertexIndicesAttr([0,1,2,3])
    floor.CreateSubdivisionSchemeAttr('none')
    omni.kit.commands.execute('CreateNavMeshVolumeCommand', parent_prim_path=Sdf.Path('/World'),
                             volume_type=0)
    volume = stage.GetPrimAtPath('/World/NavMeshVolume')
    print('VOLUME',volume, flush=True)
    if volume:
        UsdGeom.XformCommonAPI(volume).SetScale(Gf.Vec3f(20,20,4))
    base = str(Path(__file__).resolve().parents[1] / 'assets/cache/behavior')
    print('LOCAL_EXISTS',Path(base+'/Characters/Human/Default.usd').exists(), flush=True)
    print('LAYER', Sdf.Layer.FindOrOpen(base+'/Characters/Human/Default.usd'), flush=True)
    UsdGeom.Scope.Define(stage,'/World/Humans')
    # Author payloads with USD directly: no URI rewriting by generic Kit commands.
    character=UsdGeom.Xform.Define(stage,'/World/Humans/person_001').GetPrim()
    character.GetPayloads().AddPayload(base+'/Characters/Human/Default.usd')
    character.GetAttribute('xformOp:scale').Set(Gf.Vec3d(.01,.01,.01))
    character.GetAttribute('xformOp:rotateXYZ').Set(Gf.Vec3d(90,0,0))
    motion=stage.DefinePrim('/World/HumanMotionLibrary')
    motion.GetPayloads().AddPayload(base+'/MotionLibrary/Human/HumanMotionLibrary.usd')
    print('SKELROOT',stage.GetPrimAtPath('/World/Humans/person_001/SkelRoot'),flush=True)
    print('CREATE_AGENT_START', flush=True)
    result = omni.kit.commands.execute('ApplyBehaviorAgentAPICommand',
        skelroot_prim_paths=[Sdf.Path('/World/Humans/person_001/SkelRoot')],
        motion_library_prim_path=Sdf.Path('/World/HumanMotionLibrary'),
        motion_library_skeleton_rig='Human')
    print('CREATE_AGENT_END',result, flush=True)
    for _ in range(60): app.update()
    print('BAKE', nav.acquire_interface().start_navmesh_baking_and_wait(),flush=True)
    stage.GetRootLayer().Export(str(out / 'probe.usda'))
    timeline = omni.timeline.get_timeline_interface()
    timeline.set_end_time(10000)
    timeline.set_auto_update(False)
    timeline.set_time_codes_per_second(30)
    timeline.play()
    agent = None
    for i in range(300):
        timeline.forward_one_frame()
        app.update()
        agent = api.get_agent('/World/Humans/person_001/SkelRoot')
        if agent: break
    print('AGENT',agent,flush=True)
    if agent:
        (out/'agent_api.txt').write_text('\n\n'.join(f'{n}: {getattr(agent,n).__doc__}' for n in dir(agent) if not n.startswith('_')))
        print('POSITION',agent.get_world_translation(),flush=True)
        tid=agent.move_to(target=(3.0,0.0,0.0))
        rows=[]
        for i in range(360):
            timeline.forward_one_frame(); app.update()
            p=agent.get_world_translation()
            rows.append({'time':timeline.get_current_time(),'position':[p.x,p.y,p.z],
                         'status':str(agent.get_task_status(tid))})
        (out/'probe_trajectory.json').write_text(json.dumps(rows,indent=2))
        print('MOVE_RESULT',agent.get_task_status(tid),agent.get_world_translation(),flush=True)
    (out/'result.json').write_text(json.dumps({'agent_created':agent is not None,'sim_version':os.environ.get('ISAAC_PATH')},indent=2))
except Exception:
    (out/'error.txt').write_text(traceback.format_exc())
    traceback.print_exc()
finally:
    app.close()
