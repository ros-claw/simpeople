"""Navigation regression for the new B3 bench and recessed service foyer."""
import argparse,json,os,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,out/Path(__file__).name);sys.path.insert(0,str(out/'source_snapshot/src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});backend=None;code=0
try:
 import omni.usd,omni.kit.app,omni.kit.commands,carb,numpy as np
 from pxr import UsdGeom,Gf,Sdf
 manager=omni.kit.app.get_app().get_extension_manager()
 for ext in ['omni.anim.behavior.core','omni.anim.navigation.core']:manager.set_extension_enabled_immediate(ext,True)
 import omni.anim.navigation.core as nav
 from simpeople.backends.native.platform04_90_scene import create_director_scene
 from simpeople.backends.native.adapter import NativeBackend
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();scene=create_director_scene(stage,ROOT,collision=True);stage.GetRootLayer().customLayerData={'navmeshSettings':{'agentMaxFloorSlope':30.,'agentMaxRadius':.65,'agentMinRadius':.2,'agentMinHeight':1.6,'agentMaxStepHeight':.2,'agentMinIslandRadius':.2,'agentSamplingDistance':.12,'excludeRigidBodies':True}};omni.kit.commands.execute('CreateNavMeshVolumeCommand',parent_prim_path=Sdf.Path('/World'),volume_type=0);v=stage.GetPrimAtPath('/World/NavMeshVolume');UsdGeom.XformCommonAPI(v).SetTranslate(Gf.Vec3d(17,5,1.5));UsdGeom.XformCommonAPI(v).SetScale(Gf.Vec3f(52,25,6));backend=NativeBackend(ROOT,{},allow_unverified=True)
 for _ in range(8):app.update()
 assert backend.nav.start_navmesh_baking_and_wait();mesh=backend.nav.get_navmesh();profile=nav.NavAgentDesc(radius=.4,height=1.75,collision_gap=.05);records=[]
 for name,start,goal in [('car_to_platform',[17,-1.35,0],[25,1.5,0]),('door_to_gate',[23,.02,0],[28,11,0]),('bench_side_to_gate',[24.1,5.5,0],[28,10.2,0])]:
  path=mesh.query_shortest_path(start_pos=carb.Float3(*start),end_pos=carb.Float3(*goal),agent=profile);points=[list(x) for x in path.get_points()] if path else [];ok=bool(points) and np.linalg.norm(np.array(points[-1])-goal)<.3;records.append({'name':name,'reachable':bool(ok),'start':start,'goal':goal,'actual_navmesh_points':points})
 assert all(x['reachable'] for x in records),records
 (out/'connectivity.json').write_text(json.dumps(records,indent=2));(out/'completed.json').write_text(json.dumps({'passed':True,'queries':3,'runtime':backend.runtime_revision,'bench_B3_m':scene['B3'],'scope':'actual baked NavMesh queries after adding B3 and recessing foyer wall; no new Native traversal/pursuit claim; previous ordinary Jog traversal evidence retained'},indent=2));stage.GetRootLayer().Export(str(out/'scene.usda'))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if backend:backend.close()
 app.close()
raise SystemExit(code)
