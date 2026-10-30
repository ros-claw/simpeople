"""Discover existing user-installed human models without claiming animation validation."""
import argparse
import hashlib
import json
from pathlib import Path
from pxr import Usd, UsdGeom, UsdSkel

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--asset-dir',default='/data/omniverse/Assets/Isaac/5.1/Isaac/People/Characters')
args=parser.parse_args()
assets=[]
for path in sorted(Path(args.asset_dir).glob('original_*/*.usd')):
    stage=Usd.Stage.Open(str(path))
    skels=[p for p in stage.Traverse() if p.IsA(UsdSkel.Skeleton)]
    roots=[p for p in stage.Traverse() if p.IsA(UsdSkel.Root)]
    if len(skels)!=1 or not roots:continue
    asset_id=path.stem
    assets.append({'asset_id':asset_id,'base_identity_id':asset_id,'appearance_id':'original',
        'source_uri':str(path.resolve()),'content_hash':hashlib.sha256(path.read_bytes()).hexdigest(),
        'rig_id':'Human-auto-retarget-unverified','backend_support':['native'],
        'verified_actions':[],'radius_m':.35,'height_m':None,
        'motion_library':str(root/'assets/cache/behavior/MotionLibrary/Human/HumanMotionLibrary.usd'),
        'license_note':'Existing NVIDIA Isaac asset installation; not redistributed by this project.',
        'dependency_status':'discovered','source_meters_per_unit':UsdGeom.GetStageMetersPerUnit(stage),
        'source_up_axis':str(UsdGeom.GetStageUpAxis(stage)),'skelroot_path':str(roots[0].GetPath()),
        'skeleton_joint_count':len(UsdSkel.Skeleton(skels[0]).GetJointsAttr().Get())})
(root/'configs/assets.json').write_text(json.dumps({'assets':assets},indent=2))
print(json.dumps({'discovered_assets':len(assets),'config':str(root/'configs/assets.json')}))
