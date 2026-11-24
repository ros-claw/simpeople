"""Startup-only experimental motion matching features in an owned USD layer."""
import hashlib
from pathlib import Path


def configure_wrists(backend):
    backend.assert_thread()
    if backend.instances or backend.timeline.is_playing():
        raise ValueError('motion features require startup before agents and Play')
    from pxr import Usd, UsdSkel, Vt
    source = Path(backend.assets[0]['motion_library'])
    original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    library = backend.namespace+'/HumanMotionLibrary'
    prim = backend.stage.GetPrimAtPath(library)
    if not prim:
        prim = backend.stage.DefinePrim(library)
        prim.GetReferences().AddReference(str(source))
    keys = ('joints', 'jointPositionWeights', 'jointVelocityWeights')
    before = {key: list(prim.GetAttribute(key).Get()) for key in keys}
    if (before['joints'] != ['L_Ankle', 'R_Ankle', 'Pelvis']
            or before['jointPositionWeights'] != [.75, .75, 0.]
            or before['jointVelocityWeights'] != [1., 1., 1.]):
        raise ValueError('unexpected installed feature profile; review before editing')
    rig = next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(prim) if p.IsA(UsdSkel.Skeleton))
    leaves = [str(name).rsplit('/', 1)[-1] for name in rig.GetJointsAttr().Get()]
    if any(leaves.count(name) != 1 for name in ('L_Wrist', 'R_Wrist')):
        raise ValueError('target library lacks unambiguous wrist features')
    after = {'joints': before['joints']+['L_Wrist', 'R_Wrist'],
             'jointPositionWeights': before['jointPositionWeights']+[1., 1.],
             'jointVelocityWeights': before['jointVelocityWeights']+[0., 0.]}
    prim.GetAttribute('joints').Set(Vt.TokenArray(after['joints']))
    for key in keys[1:]: prim.GetAttribute(key).Set(Vt.FloatArray(after[key]))
    if any(list(prim.GetAttribute(key).Get()) != after[key] for key in keys):
        raise ValueError('motion feature readback differs')
    if hashlib.sha256(source.read_bytes()).hexdigest() != original_sha:
        raise ValueError('source motion library changed')
    return dict(profile='feet_wrists_position_v1', library_path=library, before=before, after=after,
                source_library_sha256=original_sha, original_asset_modified=False,
                before_agents_and_import=True, live_pose_writes=False,
                scope='Official library feature fields only. No assertion that SDK end variant selection uses these features.')
