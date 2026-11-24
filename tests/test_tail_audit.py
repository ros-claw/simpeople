"""Audit recorded evidence, including falsified claims and missing execution."""
import importlib.util
import json
from pathlib import Path

SPEC=importlib.util.spec_from_file_location('tail_audit',Path(__file__).parents[1]/'scripts/audit_tail_release.py')
MODULE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(MODULE)


def fixture(folder):
    points=[[0,0,0],[10,0,0]]
    event={'kind':'traffic_tail_released','cursor':3,'sim_time':5.,'route_id':'route',
        'native_task_id':17,'agent':'/World/Actors/a/Character/SkelRoot','body_instance_id':'body',
        'actor_instance_id':'actor','position_m':[6,0,0],'original_points_m':points,
        'removed_cells':[[x,0] for x in range(3)],'remaining_cells':[[x,0] for x in range(3,9)],'trail_m':2.}
    events=[{'kind':'traffic_grid_ready','cursor':1,'cell_m':1.25,'footprint_margin_m':.45},
        {'kind':'traffic_native_started','cursor':2,'route_id':'route','native_task_id':17,
            'action':'continuous_corridor','points_m':points,'reserved_cells':9},event]
    for name,data in {'benchmark_done.json':{'event_cursor':3},
        'completed.json':{'functional_expected_matched':True},
        'runtime_contract.json':{'runtime_policy':{'tail_release_enabled':True}}}.items():
        (folder/name).write_text(json.dumps(data))
    sample={'sim_time':5.,'actor_id':'a','actor_instance_id':'actor','position_m':[6,0,0],
        'traffic':{'native_task_id':17}}
    (folder/'trajectories.jsonl').write_text(json.dumps(sample)+'\n')
    return events


def evaluate(folder,events):
    (folder/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    return MODULE.audit(folder)


def test_native_start_and_actual_root_evidence_required(tmp_path):
    events=fixture(tmp_path)
    assert evaluate(tmp_path,events)['execution_and_checks_passed']
    events[-1]['position_m'][0]=6.1
    result=evaluate(tmp_path,events)
    assert not result['proof_checks_passed']
    assert 'no_matching_actual_root' in {e['reason'] for e in result['errors']}


def test_first_removal_cannot_hide_unreported_claim_loss(tmp_path):
    events=fixture(tmp_path);events[-1]['remaining_cells'].remove([3,0])
    result=evaluate(tmp_path,events)
    assert 'initial_claim_count_changed' in {e['reason'] for e in result['errors']}


def test_goal_and_current_body_cannot_be_released(tmp_path):
    events=fixture(tmp_path)
    for cell in [[5,0],[8,0]]:
        events[-1]['remaining_cells'].remove(cell);events[-1]['removed_cells'].append(cell)
    result=evaluate(tmp_path,events);reasons={e['reason'] for e in result['errors']}
    assert {'body_footprint_not_retained','goal_footprint_not_retained','released_inside_trailing_plane'}<=reasons


def test_zero_releases_are_explicitly_unverified_and_shutdown_events_excluded(tmp_path):
    events=fixture(tmp_path);events[-1]['cursor']=4
    result=evaluate(tmp_path,events)
    assert result['proof_checks_passed'] and not result['execution_observed'] and not result['execution_and_checks_passed']


def test_incarnation_scoped_prim_path_still_uses_logical_actor_identity(tmp_path):
    events=fixture(tmp_path)
    events[-1]['agent']='/World/SimPeople/Actors/a/Instance_0123/Character/SkelRoot'
    result=evaluate(tmp_path,events)
    assert result['execution_and_checks_passed']
    assert result['checks'][0]['actor_id']=='a'
