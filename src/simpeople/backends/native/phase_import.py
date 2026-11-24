"""Import explicit variants of ONE action, before agents/Play, on Kit thread."""
import hashlib
import json
from pathlib import Path


def inspect_source(skeleton, clip):
    from pxr import Usd, UsdSkel
    rig_stage = Usd.Stage.Open(skeleton)
    rig = next(UsdSkel.Skeleton(p) for p in rig_stage.Traverse() if p.IsA(UsdSkel.Skeleton))
    stage = Usd.Stage.Open(clip); animation = UsdSkel.Animation(stage.GetDefaultPrim())
    times = animation.GetRotationsAttr().GetTimeSamples()
    if times != list(range(len(times))):
        raise ValueError('dense zero-based phase samples required')
    return dict(frames=len(times), first_frame=times[0], last_frame=times[-1],
                fps=stage.GetTimeCodesPerSecond(),
                joint_layout_matches=list(rig.GetJointsAttr().Get()) == list(animation.GetJointsAttr().Get()))


def output_file(stage, path, folder):
    """Bind the returned prim to its actual USD layer, without guessing names."""
    folder = Path(folder).resolve()
    files = {Path(spec.layer.realPath).resolve() for spec in stage.GetPrimAtPath(path).GetPrimStack()
             if spec.layer.realPath and Path(spec.layer.realPath).resolve().parent == folder}
    if len(files) != 1:
        raise ValueError('returned phase prim has no unique output layer')
    return next(iter(files))


def import_variants(backend, directory, library, name, entry):
    backend.assert_thread()
    if backend.instances or backend.timeline.is_playing():
        raise ValueError('phase variants are startup-only, before actors and Play')
    from pxr import Sdf
    import omni.kit.commands
    from omni.anim.behavior.core.scripts.command import ImportCustomActionCommand
    from simpeople.core.asset_paths import resolve_asset_path
    from simpeople.core.custom_action_phases import source_plan, annotation_arguments
    plan = source_plan(entry, lambda uri: resolve_asset_path(uri, backend.root), inspect_source)
    folder = Path(directory)/'clips'/name
    if folder.exists():
        raise ValueError('phase destination must be new')
    outputs = {}; all_paths = []; omission_records = []
    original = ImportCustomActionCommand.create_annotation
    # The installed version documents empty tuples but indexes them. A temporary
    # process-local adapter implements that documented omission and is restored
    # after EVERY command, including a transport exception, before any actor.
    try:
        for spec in plan:
            omitted = []
            def annotate(command, stage, parent_path, span, tag, track=None):
                if span == ():
                    omitted.append(str(tag)); return
                return original(command, stage, parent_path, span, tag, track)
            ImportCustomActionCommand.create_annotation = annotate
            try:
                ok, paths = omni.kit.commands.execute('ImportCustomActionCommand',
                    motion_library_prim_path=Sdf.Path(library), rig_name='Human',
                    skeleton_asset=spec['skeleton'], action_name=name,
                    animation_asset_urls=[spec['clip']], action_type='Custom', **annotation_arguments(spec))
            finally:
                ImportCustomActionCommand.create_annotation = original
            if not ok or not paths or len(paths) != 1:
                raise ValueError('phase import did not return exactly its own variant')
            expected = [tag for tag, span in spec['phases'].items() if span is None]
            if sorted(omitted) != sorted(expected):
                raise ValueError('SDK did not omit exactly the declared empty phases')
            file = output_file(backend.stage, paths[0], folder)
            if file.name in outputs:
                raise ValueError('phase import overwrote an earlier output')
            outputs[file.name] = dict(spec, output=str(file))
            all_paths.extend(paths); omission_records.append(omitted)
    finally:
        ImportCustomActionCommand.create_annotation = original
    if len(set(map(str, all_paths))) != len(plan) or set(outputs) != {p.name for p in folder.glob('*.usd')}:
        raise ValueError('phase outputs are incomplete or duplicated')
    if not all(backend.stage.GetPrimAtPath(p).IsValid() for p in all_paths):
        raise ValueError('later phase import retired an earlier variant')
    result = dict(outputs=outputs, omitted=omission_records,
                  sdk_class_restored_before_agents=ImportCustomActionCommand.create_annotation is original,
                  installed_sdk_files_modified=False, live_pose_writes=False)
    (Path(directory)/(name+'_phase_import.json')).write_text(json.dumps(result, indent=2)+'\n')
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return True, all_paths, outputs, digest
