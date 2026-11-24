"""Opt-in, local clip imports. Behavior remains the only live pose writer."""
import hashlib
import json
import math
import shutil
from pathlib import Path
import carb.settings
import omni.kit.commands
from pxr import Sdf, Usd, UsdSkel, Gf, Vt
from simpeople.core.asset_paths import resolve_asset_path
from simpeople.core.clip_quality import validate_native_sample,phase_ranges
from simpeople.core import clip_quality
from simpeople.core.gesture_profiles import implementation_revision
from simpeople.motion import entry as motion_entry
from simpeople.motion import startup as motion_startup


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
        package=Path(__file__).resolve().parents[2]
        runtime_implementation=implementation_revision(package)
        runtime_flags={'cooperative_finite_stop':getattr(backend,'cooperative_finite_stop_probe_enabled',False) is True}
        for name,entry in json.loads(registry.read_text())['actions'].items():
            reference=entry.get('canonical_entry') or {}
            if reference.get('native_startup_conditions') is not None:
                motion_startup.validate_domain(reference['native_startup_conditions'])
            source={k:resolve_asset_path(entry[k],backend.root) for k in ['skeleton','clip']}
            if not all(Path(v).is_file() for v in source.values()):
                backend.custom_actions[name]={**entry,'status':'unsupported','reason':'local source missing'};continue
            import_clip=source['clip'];declared_phases=None
            if entry.get('playback_mode')=='transition_then_hold':
                # Author the endpoint and phase metadata before the SDK imports
                # or compiles the clip. Never repair cached annotations later.
                prepared=directory/'prepared_sources';prepared.mkdir(exist_ok=True)
                import_clip=str(prepared/(name+'.usda'));shutil.copy2(source['clip'],import_clip)
                prepared_stage=Usd.Stage.Open(import_clip);prepared_animation=UsdSkel.Animation(prepared_stage.GetDefaultPrim())
                source_times=prepared_animation.GetRotationsAttr().GetTimeSamples();source_lo,source_hi=min(source_times),max(source_times)
                if source_lo!=0:raise ValueError('generated transition import currently requires zero-based samples')
                declared_phases=phase_ranges('transition_then_hold',source_lo,source_hi,entry.get('endpoint_hold_frames',1))
                source_end=declared_phases['ActionEnd'][1]
                for attr in [prepared_animation.GetTranslationsAttr(),prepared_animation.GetRotationsAttr(),prepared_animation.GetScalesAttr()]:
                    value=attr.Get(source_hi)
                    if value is not None:attr.Set(value,source_end)
                prepared_stage.SetEndTimeCode(source_end);prepared_stage.GetRootLayer().Save()
            elif entry.get('playback_mode')=='out_and_back':
                input_stage=Usd.Stage.Open(source['clip']);input_animation=UsdSkel.Animation(input_stage.GetDefaultPrim());input_times=input_animation.GetRotationsAttr().GetTimeSamples()
                declared_phases=phase_ranges('out_and_back',min(input_times),max(input_times),ranges=entry.get('native_phase_ranges'))
            annotation_args={} if declared_phases is None else {
                'action_start_ranges':[tuple(declared_phases['ActionStart'])],
                'action_loop_ranges':[tuple(declared_phases['ActionLoop'])],
                'action_end_ranges':[tuple(declared_phases['ActionEnd'])]}
            ok,paths=omni.kit.commands.execute('ImportCustomActionCommand',motion_library_prim_path=Sdf.Path(library),
                rig_name='Human',skeleton_asset=source['skeleton'],action_name=name,
                animation_asset_urls=[import_clip],action_type='Custom',**annotation_args)
            if not ok or not paths or not all(backend.stage.GetPrimAtPath(p).IsValid() for p in paths):
                raise RuntimeError('native custom action import failed: '+name)
            # Retarget output is zero based in this SDK, even when its input
            # stage starts at frame 1. Keep annotation bounds on actual samples.
            for file in (directory/'clips'/name).glob('*.usd'):
                clip=Usd.Stage.Open(str(file));animation=UsdSkel.Animation(clip.GetDefaultPrim())
                times=animation.GetRotationsAttr().GetTimeSamples()
                lo,hi=min(times),max(times)
                phases=declared_phases or phase_ranges(entry.get('playback_mode','loop'),lo,hi)
                endpoint=hi
                if declared_phases is not None and (lo!=0 or abs(hi-declared_phases['ActionEnd'][1])>1e-7):
                    raise ValueError('native retarget changed declared generated clip sample range')
                clip.SetStartTimeCode(lo);clip.SetEndTimeCode(endpoint)
                for child in animation.GetPrim().GetChildren():
                    tag=child.GetAttribute('tag').Get()
                    if tag==name:span=[lo,endpoint]
                    elif tag in phases:span=phases[tag]
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
                target=UsdSkel.Skeleton(backend.stage.GetPrimAtPath(library+'/Skeleton'))
                lengths={str(j):m.ExtractTranslation().GetLength() for j,m in zip(target.GetJointsAttr().Get(),target.GetRestTransformsAttr().Get())}
                joints=list(animation.GetJointsAttr().Get());worst=0.
                for t in times:
                    translations=animation.GetTranslationsAttr().Get(t);rotations=animation.GetRotationsAttr().Get(t)
                    worst=max(worst,validate_native_sample(joints,translations,
                        [[*q.GetImaginary(),q.GetReal()] for q in rotations],lengths))
                    scales=animation.GetScalesAttr().Get(t)
                    if scales and (len(scales)!=len(joints) or any(not math.isfinite(float(x)) or abs(float(x)-1)>.001 for s in scales for x in s)):
                        raise ValueError('native animation has invalid joint scales')
                (file.parent/(file.stem+'.quality.json')).write_text(json.dumps({'frames_checked':len(times),'max_long_bone_relative_error':worst,'passed':True},indent=2)+'\n')
            backend.custom_actions[name]={**entry,'status':'discovered','source_sha256':{k:digest(v) for k,v in source.items()},
                                          'prim_paths':paths,'runtime_revision':backend.runtime_revision}
            backend.custom_actions[name]['source_sha256']['runtime_implementation']=runtime_implementation
            backend.custom_actions[name]['execution_runtime_flags']=dict(runtime_flags)
            backend.custom_actions[name]['source_sha256']['registration']=hashlib.sha256(
                Path(__file__).read_bytes()+json.dumps(entry,sort_keys=True).encode()).hexdigest()
            backend.custom_actions[name]['source_sha256']['quality_contract']=digest(clip_quality.__file__)
            backend.custom_actions[name]['source_sha256']['imported_clip']=digest(import_clip)
            backend.custom_actions[name]['source_sha256']['entry_contract']=digest(motion_entry.__file__)
            backend.custom_actions[name]['source_sha256']['startup_contract']=digest(motion_startup.__file__)
            backend.custom_actions[name]['source_sha256']['native_adapter']=digest(Path(__file__).with_name('adapter.py'))
            package=Path(__file__).resolve().parents[2]
            backend.custom_actions[name]['source_sha256']['engine']=digest(package/'core/engine.py')
            backend.custom_actions[name]['source_sha256']['precise_facing_contract']=digest(package/'core/facing_runtime.py')
            backend.custom_actions[name]['source_sha256']['custom_stop_contract']=digest(Path(__file__).with_name('custom_stop.py'))
            backend.custom_actions[name]['source_sha256']['action_space']=digest(package/'core/action_space.py')
            backend.custom_actions[name]['source_sha256']['reservations']=digest(Path(__file__).with_name('reservations.py'))
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
    try:current_implementation=implementation_revision(Path(__file__).resolve().parents[2])
    except OSError:current_implementation=None
    current_flags={'cooperative_finite_stop':getattr(backend,'cooperative_finite_stop_probe_enabled',False) is True}
    result={}
    for name,entry in actions.items():
        proof=proofs.get(name,{}).get(asset,{})
        verified=bool(entry['status']!='unsupported' and current_implementation is not None
                      and entry.get('source_sha256',{}).get('runtime_implementation')==current_implementation
                      and proof.get('execution_runtime_flags')==entry.get('execution_runtime_flags')==current_flags
                      and (entry.get('cooperative_finite_cycle') is not True or current_flags['cooperative_finite_stop'])
                      and proof.get('source_sha256')==entry.get('source_sha256')
                      and proof.get('runtime_revision')==backend.runtime_revision
                      and proof.get('asset_sha256')==next(a['content_hash'] for a in backend.assets if a['asset_id']==asset))
        result[name]={**entry,'status':'verified' if verified else 'unsupported' if entry['status']=='unsupported' else 'discovered','evidence':proof.get('evidence') if verified else None}
    return {'status':'verified' if any(v['status']=='verified' for v in result.values()) else 'discovered','clips':result}
