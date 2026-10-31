"""Opt-in, local clip imports. Behavior remains the only live pose writer."""
import hashlib
import json
from pathlib import Path
import carb.settings
import omni.kit.commands
from pxr import Sdf, Usd, UsdSkel, Gf, Vt
from simpeople.core.asset_paths import resolve_asset_path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def register(backend, directory):
    backend.assert_thread()
    registry=backend.config_dir/'custom_actions.json'
    if not registry.is_file():raise ValueError('custom action registry missing')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    backend.custom_actions={}
    backend.custom_action_directory=directory
    library=backend.namespace+'/HumanMotionLibrary'
    if not backend.stage.GetPrimAtPath(library):
        backend.stage.DefinePrim(library).GetReferences().AddReference(backend.assets[0]['motion_library'])
    from omni.anim.behavior.core.scripts.user_storage import SETTING_USER_CUSTOM_ACTION_FOLDER
    settings=carb.settings.get_settings();old=settings.get(SETTING_USER_CUSTOM_ACTION_FOLDER)
    settings.set(SETTING_USER_CUSTOM_ACTION_FOLDER,str(directory/'clips'))
    try:
        for name,entry in json.loads(registry.read_text())['actions'].items():
            source={k:resolve_asset_path(entry[k],backend.root) for k in ['skeleton','clip']}
            if not all(Path(v).is_file() for v in source.values()):
                backend.custom_actions[name]={**entry,'status':'unsupported','reason':'local source missing'};continue
            ok,paths=omni.kit.commands.execute('ImportCustomActionCommand',motion_library_prim_path=Sdf.Path(library),
                rig_name='Human',skeleton_asset=source['skeleton'],action_name=name,
                animation_asset_urls=[source['clip']],action_type='Custom')
            if not ok or not paths or not all(backend.stage.GetPrimAtPath(p).IsValid() for p in paths):
                raise RuntimeError('native custom action import failed: '+name)
            # Retarget output is zero based in this SDK, even when its input
            # stage starts at frame 1. Keep annotation bounds on actual samples.
            for file in (directory/'clips'/name).glob('*.usd'):
                clip=Usd.Stage.Open(str(file));animation=UsdSkel.Animation(clip.GetDefaultPrim())
                times=animation.GetRotationsAttr().GetTimeSamples()
                lo,hi=min(times),max(times)
                clip.SetStartTimeCode(lo);clip.SetEndTimeCode(hi)
                for child in animation.GetPrim().GetChildren():
                    tag=child.GetAttribute('tag').Get()
                    if tag in {name,'ActionLoop'}:span=[lo,hi]
                    elif tag in {'ActionStart','ActionEnd'}:span=[lo,lo]
                    else:continue
                    child.GetAttribute('start').Set(span[0]);child.GetAttribute('end').Set(span[1])
                # Authored clip calibration, before Play. Never move the live
                # actor or write live bones to hide contact problems.
                lift=entry.get('pelvis_lift_m',0)*100
                if lift or entry.get('in_place'):
                    joints=list(animation.GetJointsAttr().Get());pelvis=joints.index('Root/Pelvis')
                    attr=animation.GetTranslationsAttr()
                    for t in attr.GetTimeSamples():
                        values=list(attr.Get(t));p=values[pelvis]
                        values[pelvis]=Gf.Vec3f(0 if entry.get('in_place') else p[0],p[1]+lift,0 if entry.get('in_place') else p[2])
                        attr.Set(Vt.Vec3fArray(values),t)
                clip.GetRootLayer().Save()
            backend.custom_actions[name]={**entry,'status':'discovered','source_sha256':{k:digest(v) for k,v in source.items()},
                                          'prim_paths':paths,'runtime_revision':backend.runtime_revision}
            backend.custom_actions[name]['source_sha256']['registration']=hashlib.sha256(
                Path(__file__).read_bytes()+json.dumps(entry,sort_keys=True).encode()).hexdigest()
        # Each native import replaces the custom-action scope. Restore bindings
        # for all earlier clips after the last import, before agents are created.
        for entry in backend.custom_actions.values():
            for path in entry.get('prim_paths',[]):
                backend.stage.GetPrimAtPath(path).CreateRelationship('animationSkelBinding:sourceSkeleton').SetTargets([Sdf.Path(library+'/Skeleton')])
    finally:
        settings.set(SETTING_USER_CUSTOM_ACTION_FOLDER,old or '')
    (directory/'registry.json').write_text(json.dumps(backend.custom_actions,ensure_ascii=False,indent=2))


def describe(backend, handle):
    actions=getattr(backend,'custom_actions',{})
    if not actions:return {'status':'unsupported','reason':'Custom clips are opt-in; no local registry loaded'}
    asset=backend.instances[handle]['asset_id']
    acceptance=backend.config_dir/'custom_action_acceptance.json'
    proofs=json.loads(acceptance.read_text()) if acceptance.is_file() else {}
    result={}
    for name,entry in actions.items():
        proof=proofs.get(name,{}).get(asset,{})
        verified=bool(entry['status']!='unsupported' and proof.get('source_sha256')==entry.get('source_sha256')
                      and proof.get('runtime_revision')==backend.runtime_revision
                      and proof.get('asset_sha256')==next(a['content_hash'] for a in backend.assets if a['asset_id']==asset))
        result[name]={**entry,'status':'verified' if verified else entry['status'],'evidence':proof.get('evidence') if verified else None}
    return {'status':'verified' if any(v['status']=='verified' for v in result.values()) else 'discovered','clips':result}
