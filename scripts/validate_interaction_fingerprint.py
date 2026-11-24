"""OpenUSD checks: identity prop ops stay stable; real geometry stays versioned."""
import argparse,hashlib,json,shutil,sys,threading
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--source-root',default=str(ROOT));args=p.parse_args();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False);snap=out/'source_snapshot';snap.mkdir();shutil.copytree(Path(args.source_root)/'src',snap/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,snap/Path(__file__).name);sys.path.insert(0,str(snap/'src'))
from pxr import Usd,UsdGeom,Gf,Vt
from simpeople.backends.native.interactions import snapshot_targets
from simpeople.core.scene_semantics import SceneInteractionRegistry

stage=Usd.Stage.CreateInMemory();UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z');stage.SetTimeCodesPerSecond(30)
UsdGeom.Xform.Define(stage,'/World');seat=UsdGeom.Xform.Define(stage,'/World/Seat');translate=seat.AddTranslateOp();translate.Set(Gf.Vec3d(7.5,-8.75,0))
mesh=UsdGeom.Mesh.Define(stage,'/World/Seat/Mesh');points=[Gf.Vec3f(x,y,z) for z in [.4,.5] for x,y in [(-.3,-.3),(.3,-.3),(.3,.3),(-.3,.3)]]+[Gf.Vec3f(0,-.3,.45)]
mesh.CreatePointsAttr(points);mesh.CreateFaceVertexCountsAttr([3]*4+[4]*5);mesh.CreateFaceVertexIndicesAttr([0,1,8,1,5,8,5,4,8,4,0,8,0,3,2,1,4,5,6,7,1,2,6,5,2,3,7,6,3,0,4,7]);mesh.CreateSubdivisionSchemeAttr('none')
hips=UsdGeom.Xform.Define(stage,'/World/Seat/Hips');hips.AddTranslateOp().Set(Gf.Vec3d(0,-.08,.56))
thread=threading.get_ident()
def assert_thread():assert threading.get_ident()==thread
backend=SimpleNamespace(stage=stage,timeline=SimpleNamespace(get_current_time=lambda:1),semantics={'seat':{'kind':'seat','prim_path':'/World/Seat','hips_prim_path':'/World/Seat/Hips','approach':[7.5,-10,0],'egress_targets':[[9,-10,0]]}},config_dir=out,to_public=lambda x:[float(v) for v in x],assert_thread=assert_thread)
def target():return SceneInteractionRegistry(snapshot_targets(backend),'probe').resolve('seat')
initial=target();results=[]
rotate=seat.AddRotateZYXOp();rotate.Set(Gf.Vec3f(-0.,0.,-0.));scale=seat.AddScaleOp();scale.Set(Gf.Vec3f(1,1,1));same=target();results.append({'case':'actual_observed_identity_rotate_scale_ops','passed':same['geometry_revision']==initial['geometry_revision']})
rotate.Set(Gf.Vec3f(0,0,5));results.append({'case':'real_rotation','passed':target()['geometry_revision']!=initial['geometry_revision']});rotate.Set(Gf.Vec3f(0))
deformed=list(points);deformed[-1]=Gf.Vec3f(0,-.28,.45);mesh.GetPointsAttr().Set(deformed);changed=target();results.append({'case':'interior_mesh_change_with_equal_bbox','passed':changed['bounds_m']==initial['bounds_m'] and changed['geometry_revision']!=initial['geometry_revision']});mesh.GetPointsAttr().Set(points)
rotation=hips.AddRotateXYZOp();rotation.Set(Gf.Vec3f(0,0,5));changed=target();results.append({'case':'anchor_orientation_with_same_position','passed':changed['anchors']==initial['anchors'] and changed['geometry_revision']!=initial['geometry_revision']});rotation.Set(Gf.Vec3f(0))
# An SDK-authored time sample can shadow a default-value edit. The version must
# reflect the evaluated transform, including an effective edit at current time.
translate.Set(Gf.Vec3d(7.5,-8.75,0),30);translate.Set(Gf.Vec3d(7.7,-8.75,0));results.append({'case':'shadowed_default_does_not_move_current_geometry','passed':target()['geometry_revision']==initial['geometry_revision']});translate.Set(Gf.Vec3d(7.7,-8.75,0),30);results.append({'case':'effective_current_time_edit','passed':target()['geometry_revision']!=initial['geometry_revision']})
stage.GetRootLayer().Export(str(out/'diagnostic_stage.usda'))
manifest={str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()};(out/'source_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
result={'passed':all(r['passed'] for r in results),'source_root':str(Path(args.source_root).resolve()),'usd_version':list(Usd.GetVersion()),'cases':results,'scope':'Offline OpenUSD geometry fingerprint semantics; actual native SDK seating is a separate probe.'};(out/'fingerprint_validation.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 2)
