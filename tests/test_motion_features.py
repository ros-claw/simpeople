import hashlib
from types import SimpleNamespace

import pytest
from pxr import Sdf, Usd, UsdSkel, Vt

from simpeople.backends.native.motion_features import configure_wrists


def backend(tmp_path):
    path = tmp_path/'library.usda'; source = Usd.Stage.CreateNew(str(path))
    root = source.DefinePrim('/Library'); source.SetDefaultPrim(root)
    for name, value, kind in [('joints', ['L_Ankle', 'R_Ankle', 'Pelvis'], Sdf.ValueTypeNames.TokenArray),
        ('jointPositionWeights', [.75, .75, 0.], Sdf.ValueTypeNames.FloatArray),
        ('jointVelocityWeights', [1., 1., 1.], Sdf.ValueTypeNames.FloatArray)]:
        root.CreateAttribute(name, kind).Set(value)
    rig = UsdSkel.Skeleton.Define(source, '/Library/Skeleton')
    rig.CreateJointsAttr(Vt.TokenArray(['Root', 'Root/L_Wrist', 'Root/R_Wrist']))
    source.GetRootLayer().Save()
    return SimpleNamespace(assert_thread=lambda: None, instances={}, namespace='/Owned',
        timeline=SimpleNamespace(is_playing=lambda: False), stage=Usd.Stage.CreateInMemory(),
        assets=[{'motion_library': str(path)}]), path


def test_authors_only_owned_feature_metadata_and_preserves_source_bytes(tmp_path):
    b, path = backend(tmp_path); before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = configure_wrists(b)
    assert result['after']['joints'] == ['L_Ankle', 'R_Ankle', 'Pelvis', 'L_Wrist', 'R_Wrist']
    assert result['after']['jointVelocityWeights'] == [1., 1., 1., 0., 0.]
    assert before == hashlib.sha256(path.read_bytes()).hexdigest() == result['source_library_sha256']
    assert not result['live_pose_writes'] and not result['original_asset_modified']
    # Applying twice must not silently change or duplicate a feature vector.
    with pytest.raises(ValueError): configure_wrists(b)


@pytest.mark.parametrize('fault', ['playing', 'actors'])
def test_rejects_live_changes_before_creating_a_library(tmp_path, fault):
    b, _ = backend(tmp_path)
    if fault == 'playing': b.timeline.is_playing = lambda: True
    else: b.instances = {'live': {}}
    with pytest.raises(ValueError): configure_wrists(b)
    assert not b.stage.GetPrimAtPath('/Owned/HumanMotionLibrary')
