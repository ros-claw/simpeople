import copy
import hashlib
from pathlib import Path

import pytest

from simpeople.core.custom_action_phases import annotation_arguments, source_plan


def inputs(tmp_path):
    files = {}
    for name in ('main', 'exit', 'rig78', 'rig81'):
        p = tmp_path/name; p.write_text(name); files['cache://'+name] = p
    def spec(clip, rig, frames, phases):
        return dict(clip='cache://'+clip, skeleton='cache://'+rig, frames=frames, phases=phases,
                    source_sha256={k: hashlib.sha256(files['cache://'+v].read_bytes()).hexdigest()
                                   for k, v in [('clip', clip), ('skeleton', rig)]})
    entry = dict(clip='cache://main', skeleton='cache://rig78', playback_mode='loop', experimental_phase_sources=[
        spec('main', 'rig78', 100, dict(ActionStart=[0, 0], ActionLoop=[0, 99], ActionEnd=None)),
        spec('exit', 'rig81', 20, dict(ActionStart=None, ActionLoop=None, ActionEnd=[0, 19]))])
    def inspect(rig, clip):
        n = 100 if Path(clip).name == 'main' else 20
        return dict(frames=n, first_frame=0, last_frame=n-1, fps=30, joint_layout_matches=True)
    return entry, files, inspect


def test_preserves_distinct_source_skeletons_and_empty_phases(tmp_path):
    entry, files, inspect = inputs(tmp_path)
    result = source_plan(entry, files.__getitem__, inspect)
    assert result[0]['skeleton'] != result[1]['skeleton']
    assert annotation_arguments(result[0]) == dict(action_start_ranges=[(0, 0)],
        action_loop_ranges=[(0, 99)], action_end_ranges=[()])
    assert annotation_arguments(result[1]) == dict(action_start_ranges=[()],
        action_loop_ranges=[()], action_end_ranges=[(0, 19)])


@pytest.mark.parametrize('fault', ['digest', 'duplicate', 'main_changed', 'missing_phase',
    'exit_loop', 'short_end', 'bad_frames', 'nan', 'outside', 'remote'])
def test_rejects_unbound_or_wrong_phase_inputs_before_import(tmp_path, fault):
    entry, files, inspect = inputs(tmp_path); specs = entry['experimental_phase_sources']
    if fault == 'digest': specs[1]['source_sha256']['clip'] = 'stale'
    if fault == 'duplicate': specs[1] = copy.deepcopy(specs[0])
    if fault == 'main_changed': entry['clip'] = 'cache://exit'
    if fault == 'missing_phase': del specs[1]['phases']['ActionEnd']
    if fault == 'exit_loop': specs[1]['phases']['ActionLoop'] = [0, 19]
    if fault == 'short_end': specs[1]['phases']['ActionEnd'] = [1, 19]
    if fault == 'bad_frames': specs[1]['frames'] = 19
    if fault == 'nan': specs[1]['phases']['ActionEnd'] = [0, float('nan')]
    if fault == 'outside': specs[0]['phases']['ActionStart'] = [0, 100]
    if fault == 'remote': specs[1]['clip'] = 'https://example.invalid/clip.usd'
    with pytest.raises(ValueError): source_plan(entry, files.__getitem__, inspect)


@pytest.mark.parametrize('fault', ['rate', 'layout', 'nonzero_first'])
def test_source_metadata_must_match_the_declared_animation(tmp_path, fault):
    entry, files, inspect = inputs(tmp_path)
    def bad(rig, clip):
        meta = inspect(rig, clip)
        meta[{'rate': 'fps', 'layout': 'joint_layout_matches', 'nonzero_first': 'first_frame'}[fault]] = {
            'rate': 60, 'layout': False, 'nonzero_first': 1}[fault]
        return meta
    with pytest.raises(ValueError): source_plan(entry, files.__getitem__, bad)
