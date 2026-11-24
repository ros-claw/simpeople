"""Prepare an offline SOMA derivative for the native Human retarget command."""
import hashlib
import shutil
from pathlib import Path
from pxr import Usd,UsdSkel,Sdf
import RetargetingSchema
from omni.anim.retarget.core.scripts.rig import RetargetRig


def prepare_soma_rig(source,destination):
    source=Path(source);destination=Path(destination)
    if destination.exists():raise FileExistsError(destination)
    shutil.copy2(source,destination)
    stage=Usd.Stage.Open(str(destination));skeleton=UsdSkel.Skeleton(stage.GetPrimAtPath('/Soma/Skeleton'))
    joints=[str(j) for j in skeleton.GetJointsAttr().Get()]
    if len(joints)!=78 or joints[:2]!=['Root','Root/Hips']:
        raise ValueError('native SOMA derivative requires identity Root above the full 77 joint rig')
    names=[j.rsplit('/',1)[-1] for j in joints];tags=RetargetRig('Human').get_tags()
    api=RetargetingSchema.ControlRigAPI.Apply(skeleton.GetPrim());api.GetRetargetTagsAttr().Set([n if n in tags else '' for n in names])
    if api.GetRetargetTagsAttr().Get()[1]!='Hips':raise ValueError('Human retarget profile lacks Hips tag')
    api.GetRetargetTransformsAttr().Set(skeleton.GetRestTransformsAttr().Get())
    skeleton.GetPrim().CreateAttribute('controlRig:upAxis',Sdf.ValueTypeNames.Token).Set('Y')
    skeleton.GetPrim().CreateAttribute('controlRig:forwardAxis',Sdf.ValueTypeNames.Token).Set('Z')
    stage.GetRootLayer().Save()
    return {'names':names,'tags':list(api.GetRetargetTagsAttr().Get()),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'prepared_sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'native_import_profile':'soma77-virtual-root-human110.4-v1'}
