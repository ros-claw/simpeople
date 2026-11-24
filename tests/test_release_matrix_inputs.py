import copy
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from freeze_runtime_release_cases import blocked,matrix_cases
from freeze_workloads import freeze_population


def scenes():
    wide={f'work_{i:02}':{'position_m':[7 if i%2 else -7,5.7+i,0]} for i in range(8)}
    wide.update({f'queue_{i}':{'kind':'queue','slots_m':[[-15+i*5,-15,0]],
                            'egress_targets':[[-14+i*5,-15,0],[-16+i*5,-15,0]]} for i in range(3)})
    wide.update({f'event_station_{i}':{'position_m':[-13+i*12,3,0]} for i in range(3)})
    wide.update({f'seat_{i:02}':{'kind':'seat','approach':[7+i,-8,0],
                              'egress_targets':[[7+i,-9,0],[8+i,-9,0]]} for i in range(6)})
    narrow=copy.deepcopy(wide);narrow['t2_narrow_layout']={'revision':'floor_spanning_door_v1','wall_boxes':[
        {'position':[0,6.4,1],'size':[.3,31.2,2]}, {'position':[0,-16.4,1],'size':[.3,11.2,2]}]}
    return wide,narrow


def test_complete_matrix_is_deterministic_and_preserves_all_required_requests():
    wide,narrow=scenes();original=copy.deepcopy((wide,narrow));a=matrix_cases(wide,narrow)
    assert a==matrix_cases(wide,narrow) and (wide,narrow)==original
    assert len(a)==18 and len({r['case']['case_id'] for r in a})==18
    for row in a:
        case=row['case'];assert len(case['requests'])==2*row['people']
        assert case['duration_s']==600 and case['finite'] and 'stop_when_complete' not in case
        assert all(r['deadline_s']==600 and r['expected_outcome']=='succeeded' for r in case['requests'])
        assert row['native_fixture_preflight_required'] and not row['nominal_feasibility_verified']


def test_wide_trace_is_unchanged_and_narrow_inputs_are_explicit_not_runtime_edits():
    wide,narrow=scenes();rows=matrix_cases(wide,narrow)
    for row in rows:
        case=row['case']
        if row['layout']=='wide':
            original=freeze_population(wide,row['people'],seed=row['seed'])
            assert case['actors']==original['actors']
            assert [r['steps'] for r in case['requests']]==[r['steps'] for r in original['requests']]
            assert not row['input_adjustments']
        else:
            boxes=narrow['t2_narrow_layout']['wall_boxes']
            assert all(not blocked(a['spawn_anchor'],boxes) for a in case['actors'])
            assert all(not blocked(s['target'],boxes) for r in case['requests'] for s in r['steps'] if isinstance(s.get('target'),list))
            if row['people']>=30:assert row['input_adjustments']
    assert not blocked([0,-10,0],narrow['t2_narrow_layout']['wall_boxes'])


def test_an_unsafe_semantic_target_requires_a_scene_revision():
    wide,narrow=scenes();narrow['event_station_0']['position_m']=[0,3,0]
    with pytest.raises(ValueError,match='revised scene'):matrix_cases(wide,narrow)


def test_the_observed_queue_exit_inside_the_wall_is_not_hidden_by_safe_slots():
    wide,narrow=scenes();narrow['queue_2']['egress_targets'][0]=[0,-15,0]
    with pytest.raises(ValueError,match='queue_exit0'):matrix_cases(wide,narrow)


def test_revised_scene_and_cases_are_new_inputs_without_overwriting_v1():
    wide,narrow=scenes();before=copy.deepcopy(narrow)
    narrow['t2_narrow_layout']['revision']='floor_spanning_door_release_v2'
    rows=matrix_cases(wide,narrow)
    assert all(r['case']['case_id'].endswith('_v2') for r in rows)
    assert all(r['case']['scene']['id']=='industrial_narrow_release_v2' for r in rows if r['layout']=='narrow')
    assert before['t2_narrow_layout']['revision']=='floor_spanning_door_v1'
