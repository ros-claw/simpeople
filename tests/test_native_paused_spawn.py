"""Execute actual Native methods: a refused birth must precede every mutation."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from simpeople.core.errors import SimPeopleError


def methods():
    path = Path(__file__).resolve().parents[1] / 'src/simpeople/backends/native/adapter.py'
    cls = next(n for n in ast.parse(path.read_text()).body
               if isinstance(n, ast.ClassDef) and n.name == 'NativeBackend')
    nodes = [n for n in cls.body if isinstance(n, ast.FunctionDef)
             and n.name in {'spawn', 'pause', 'resume'}]
    scope = {'SimPeopleError': SimPeopleError}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)
    return scope


class AssetLookupReached(Exception):
    pass


class NoSceneAccess:
    def __iter__(self):
        raise AssetLookupReached('positive cases proceed to ordinary asset validation')


def backend(playing, stopped, pending=False):
    calls = []
    timeline = SimpleNamespace(is_playing=lambda: playing, is_stopped=lambda: stopped)
    def pause():
        calls.append('pause'); timeline.is_playing = lambda: False
        timeline.is_stopped = lambda: False
    def play():
        calls.append('play'); timeline.is_playing = lambda: True
        timeline.is_stopped = lambda: False
    timeline.pause = pause; timeline.play = play
    return SimpleNamespace(timeline=timeline, assert_thread=lambda: calls.append('owner_thread'),
                           native_seed_sealed=False, assets=NoSceneAccess(),
                           _spawn_pause_requested=pending, calls=calls)


@pytest.mark.parametrize('playing,stopped,pending', [
    (False, False, False), (False, False, True), (True, False, True),
    (False, True, True),
])
def test_paused_or_pending_pause_refuses_before_seed_or_scene_access(playing, stopped, pending):
    b = backend(playing, stopped, pending)
    with pytest.raises(SimPeopleError) as error:
        methods()['spawn'](b, 'actor', 'default', [0, 0, 0])
    assert error.value.code == 'POLICY_UNSUPPORTED'
    assert error.value.as_dict()['stage'] == 'admission'
    assert error.value.details['supported_states'] == ['stopped', 'playing']
    assert b.calls == ['owner_thread'] and b.native_seed_sealed is False


@pytest.mark.parametrize('playing,stopped', [(False, True), (True, False)])
def test_preplay_and_live_birth_keep_ordinary_asset_validation(playing, stopped):
    b = backend(playing, stopped)
    with pytest.raises(AssetLookupReached):
        methods()['spawn'](b, 'actor', 'default', [0, 0, 0])
    assert b.native_seed_sealed is True


def test_real_pause_resume_methods_fence_pending_birth_and_allow_retry():
    b = backend(True, False); m = methods()
    m['pause'](b)
    with pytest.raises(SimPeopleError): m['spawn'](b, 'actor', 'default', [0, 0, 0])
    assert b.native_seed_sealed is False
    m['resume'](b)
    with pytest.raises(AssetLookupReached): m['spawn'](b, 'actor', 'default', [0, 0, 0])
    assert b.calls == ['pause', 'owner_thread', 'play', 'owner_thread']
