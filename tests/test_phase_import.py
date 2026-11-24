import hashlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from simpeople.backends.native import phase_import


def package(monkeypatch, name):
    module = ModuleType(name); module.__path__ = []
    monkeypatch.setitem(sys.modules, name, module)
    if '.' in name:
        parent, attr = name.rsplit('.', 1)
        setattr(sys.modules[parent], attr, module)
    return module


@pytest.mark.parametrize('fault', [False, True])
def test_each_variant_keeps_its_source_rig_and_sdk_class_is_restored(monkeypatch, tmp_path, fault):
    for name in ['omni', 'omni.kit', 'omni.kit.commands', 'omni.anim', 'omni.anim.behavior',
                 'omni.anim.behavior.core', 'omni.anim.behavior.core.scripts', 'omni.anim.behavior.core.scripts.command']:
        package(monkeypatch, name)
    files = {}
    for name in ['main', 'exit', 'rig78', 'rig81']:
        p = tmp_path/name; p.write_text(name); files['cache://'+name] = p
    entry = dict(clip='cache://main', skeleton='cache://rig78', playback_mode='loop', experimental_phase_sources=[])
    for clip, rig, phases in [('main', 'rig78', dict(ActionStart=[0, 0], ActionLoop=[0, 9], ActionEnd=None)),
                              ('exit', 'rig81', dict(ActionStart=None, ActionLoop=None, ActionEnd=[0, 9]))]:
        entry['experimental_phase_sources'].append(dict(clip='cache://'+clip, skeleton='cache://'+rig,
            frames=10, phases=phases, source_sha256={key: hashlib.sha256(files['cache://'+value].read_bytes()).hexdigest()
                                                    for key, value in [('clip', clip), ('skeleton', rig)]}))
    from simpeople.core import asset_paths
    monkeypatch.setattr(asset_paths, 'resolve_asset_path', lambda uri, _: str(files[uri]))
    monkeypatch.setattr(phase_import, 'inspect_source', lambda *_: dict(frames=10, first_frame=0,
        last_frame=9, fps=30, joint_layout_matches=True))
    calls = []; annotations = []; prims = {}; directory = tmp_path/'import'; directory.mkdir()
    def original(command, stage, parent, span, tag, track=None):
        if not span: raise IndexError('installed empty range behavior')
        annotations.append((tag, span))
    class SDK:
        create_annotation = original
    sys.modules['omni.anim.behavior.core.scripts.command'].ImportCustomActionCommand = SDK
    def execute(command, **kwargs):
        calls.append(kwargs)
        for field, tag in [('action_start_ranges', 'ActionStart'), ('action_loop_ranges', 'ActionLoop'), ('action_end_ranges', 'ActionEnd')]:
            SDK.create_annotation(None, None, None, kwargs[field][0], tag)
        if fault and len(calls) == 2: raise RuntimeError('injected import failure')
        # Deliberately unlike both source basename and action name.
        p = directory/'clips'/'action'/f'unexpected_{len(calls)}.usd'
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text('retarget output')
        path = '/Library/Variant'+str(len(calls))
        prims[path] = SimpleNamespace(IsValid=lambda: True,
            GetPrimStack=lambda: [SimpleNamespace(layer=SimpleNamespace(realPath=str(p)))])
        return True, [path]
    sys.modules['omni.kit.commands'].execute = execute
    b = SimpleNamespace(assert_thread=lambda: None, root=tmp_path, instances={},
                        timeline=SimpleNamespace(is_playing=lambda: False),
                        stage=SimpleNamespace(GetPrimAtPath=lambda p: prims[str(p)]))
    if fault:
        with pytest.raises(RuntimeError): phase_import.import_variants(b, directory, '/Library', 'action', entry)
        assert not (directory/'action_phase_import.json').exists()
    else:
        ok, paths, outputs, digest = phase_import.import_variants(b, directory, '/Library', 'action', entry)
        assert ok and len(paths) == 2 and len(digest) == 64
        assert outputs['unexpected_1.usd']['phases']['ActionEnd'] is None
        assert outputs['unexpected_2.usd']['phases']['ActionEnd'] == [0, 9]
        assert [Path(c['skeleton_asset']).name for c in calls] == ['rig78', 'rig81']
        assert (directory/'action_phase_import.json').exists()
    assert SDK.create_annotation is original
    assert annotations == [('ActionStart', (0, 0)), ('ActionLoop', (0, 9)), ('ActionEnd', (0, 9))]


@pytest.mark.parametrize('playing,actors', [(True, {}), (False, {'live': {}})])
def test_import_refuses_live_or_populated_runtime_before_loading_sdk(playing, actors):
    b = SimpleNamespace(assert_thread=lambda: None, instances=actors,
                        timeline=SimpleNamespace(is_playing=lambda: playing))
    with pytest.raises(ValueError, match='startup-only'):
        phase_import.import_variants(b, '/not/created', '/Library', 'action', {})


def test_output_binding_rejects_an_unrelated_or_ambiguous_layer(tmp_path):
    folder = tmp_path/'outputs'; folder.mkdir()
    for files in [[tmp_path/'foreign.usd'], [folder/'one.usd', folder/'two.usd']]:
        prim = SimpleNamespace(GetPrimStack=lambda: [SimpleNamespace(layer=SimpleNamespace(realPath=str(p))) for p in files])
        stage = SimpleNamespace(GetPrimAtPath=lambda _: prim)
        with pytest.raises(ValueError): phase_import.output_file(stage, '/Root', folder)
