"""Compare native sole reconstruction with OpenUSD skinning on real assets."""
import argparse,hashlib,json,math,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args();out=Path(args.output).resolve();out.mkdir(exist_ok=False,parents=True);snap=out/'source_snapshot';snap.mkdir()
shutil.copytree(ROOT/'src',snap/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,snap/Path(__file__).name);sys.path.insert(0,str(snap/'src'))
import numpy as np
from pxr import Usd,UsdGeom,UsdSkel,Gf,Vt
from simpeople.backends.native.foot_geometry import FootGeometry
results=[]
for relative in ['assets/cache/behavior/Characters/Human/Default.usd','assets/characters/original_female_adult_business_02/female_adult_business_02.usd']:
    source=ROOT/relative;original=Usd.Stage.Open(str(source));stage=Usd.Stage.CreateInMemory();UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z');model=UsdGeom.Xform.Define(stage,'/World/Model');model.GetPrim().GetReferences().AddReference(str(source))
    transform=Gf.Matrix4d().SetScale(UsdGeom.GetStageMetersPerUnit(original))
    if UsdGeom.GetStageUpAxis(original)=='Y':transform*=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1,0,0),90))
    UsdGeom.Xformable(model).MakeMatrixXform().Set(transform);root=next(UsdSkel.Root(x) for x in Usd.PrimRange(model.GetPrim()) if x.IsA(UsdSkel.Root));sk=next(UsdSkel.Skeleton(x) for x in Usd.PrimRange(root.GetPrim()) if x.IsA(UsdSkel.Skeleton));names=list(map(str,sk.GetJointsAttr().Get()));leaves=[n.rsplit('/',1)[-1] for n in names]
    feet={side:leaves.index(short) for side,short in [('left','L_Ankle' if 'L_Ankle' in leaves else 'L_Foot'),('right','R_Ankle' if 'R_Ankle' in leaves else 'R_Foot')]};geometry=FootGeometry(stage,str(root.GetPath()),feet);cache=UsdSkel.Cache();cache.Populate(root,Usd.PrimDefaultPredicate);bind=list(sk.GetBindTransformsAttr().Get());world_xf=UsdGeom.XformCache().GetLocalToWorldTransform(sk.GetPrim());errors=[]
    for angle in [0,10]:
        pivot=bind[feet['left']].ExtractTranslation();delta=Gf.Matrix4d().SetTranslate(-pivot)*Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1,0,0),angle))*Gf.Matrix4d().SetTranslate(pivot);foot_path=names[feet['left']];posed=[b*delta if n==foot_path or n.startswith(foot_path+'/') else b for n,b in zip(names,bind)];world=[]
        for matrix in posed:
            matrix=matrix*world_xf;quat=Gf.Transform(matrix).GetRotation().GetQuat();world.append([*matrix.ExtractTranslation(),*quat.GetImaginary(),quat.GetReal()])
        actual=geometry.evaluate(world);expected={}
        for mesh in geometry.meshes:
            prim=stage.GetPrimAtPath(mesh['path']);query=cache.GetSkinningQuery(prim);points=Vt.Vec3fArray(UsdGeom.Mesh(prim).GetPointsAttr().Get());skin=Vt.Matrix4dArray([b.GetInverse()*q for b,q in zip(bind,posed)]);assert query.ComputeSkinnedPoints(skin,points,Usd.TimeCode.Default());selected=np.c_[np.array(points)[mesh['ids']],np.ones(len(mesh['ids']))]@np.array(world_xf);expected.setdefault(mesh['side'],[]).extend(selected[:,:3].tolist())
        worst=max(float(np.linalg.norm(np.array(actual[s])-np.array(expected[s]),axis=-1).max()) for s in actual);errors.append({'foot_rotation_deg':angle,'max_vertex_error_m':worst,'passed':worst<1e-5})
    results.append({'asset':relative,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'checks':errors,'patches':geometry.describe()})
result={'passed':all(c['passed'] for r in results for c in r['checks']),'assets':results,'scope':'Actual asset LBS math parity at bind and a known foot rotation; runtime contact/slip still requires actual SDK time series.'};(out/'foot_geometry_parity.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({r['asset']:r['checks'] for r in results},indent=2));raise SystemExit(0 if result['passed'] else 2)
