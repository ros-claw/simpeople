"""Fabricated offline audit counterexamples, never native acceptance evidence."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from audit_runtime_release_matrix import audit_matrix, case_hash


def dump(path, value):
    path.write_text(json.dumps(value))


@pytest.fixture
def matrix(tmp_path):
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    specs = []
    for n in range(18):
        case = {'case_id': 'offline_case_' + str(n), 'actors': [{'actor_id': 'a'}],
                'requests': [{'request_case_id': 'first', 'expected_outcome': 'succeeded'},
                             {'request_case_id': 'dependent', 'expected_outcome': 'succeeded'}]}
        path = inputs / (case['case_id'] + '.json')
        dump(path, case)
        specs.append({'case_id': case['case_id'], 'requests': 2, 'case_sha256': case_hash(case),
                      'file_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    dump(inputs / 'matrix_manifest.json', {'cases': specs})
    return inputs


def run(tmp_path, matrix, index, version, failed=False):
    folder = tmp_path / (version + str(index))
    folder.mkdir()
    case = json.loads((matrix / ('offline_case_' + str(index) + '.json')).read_text())
    states = ['failed', 'not_submitted_dependency_failed'] if failed else ['succeeded', 'succeeded']
    rows = [{'request_case_id': r['request_case_id'], 'state': state,
             'submitted_at_s': None if state == 'not_submitted_dependency_failed' else 0,
             'admitted_at_s': None if state == 'not_submitted_dependency_failed' else 0}
            for r, state in zip(case['requests'], states)]
    counts = {state: states.count(state) for state in set(states)}
    snapshot = folder / 'source_snapshot'
    (snapshot / 'src').mkdir(parents=True)
    contents = {'src/fixture.py': version, 'bench_native_runtime.py': 'same harness'}
    manifest = {}
    for name, text in contents.items():
        path = snapshot / name
        path.write_text(text)
        manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    records = {'workload.json': case,
               'outcomes.json': {'case_sha256': case_hash(case), 'scheduled': 2, 'denominator': 2,
                                 'submitted': 1 if failed else 2, 'admitted': 1 if failed else 2,
                                 'requests': rows, 'counts': counts, 'conservation_passed': True},
               'completed.json': {'harness_completed': True, 'duration_s': 600, 'frames': 18000,
                                  'functional_expected_matched': not failed},
               'recording_metrics.json': {'frames_written': 18000, 'empty_rgb_frames': 0, 'dropped_frames': 0},
               'source_manifest.json': manifest, 'runtime_contract.json': {'compatibility_sha256': 'OFFLINE_FIXTURE_ONLY'},
               'runtime_audit.json': {'planned_requests': 2, 'outcome_counts': counts,
                                      'admission_bounds_passed': True, 'wait_budget_violations': 0},
               'measurement_end_state.json': {'actors': [{'actor_id': 'a', 'actor_instance_id': 'offline_instance',
                   'observation': {'ready': True, 'position_source': 'BehaviorAgent.get_world_translation'},
                   'completed_activities': 0 if failed else 2}]},
               'acceptance_summary.json': {'trajectory_proxies': {'sustained_overlap_segments': [], 'root_discontinuities': []}},
               'sdk_idle_settings.json': {'mode': 'offline_fixture'}}
    for name, value in records.items():
        dump(folder / name, value)
    return folder, manifest


def test_missing_cases_never_pass_and_unsubmitted_dependency_stays_in_denominator(tmp_path, matrix):
    b, bm = run(tmp_path, matrix, 0, 'baseline', failed=True)
    c, cm = run(tmp_path, matrix, 0, 'candidate', failed=True)
    report = audit_matrix(matrix, [b], [c], bm, cm)
    assert not report['evidence_complete'] and not report['candidate_runtime_checks_passed']
    result = report['versions']['candidate']
    assert result['observed_denominator'] == 2 and result['observed_unsuccessful'] == 2
    assert len(result['missing_cases']) == 17 and len(report['pairs']) == 1


def test_baseline_failures_do_not_block_a_complete_improved_candidate(tmp_path, matrix):
    baseline, candidate = [], []
    for n in range(18):
        b, bm = run(tmp_path, matrix, n, 'baseline', failed=True)
        c, cm = run(tmp_path, matrix, n, 'candidate')
        baseline.append(b)
        candidate.append(c)
    report = audit_matrix(matrix, baseline, candidate, bm, cm)
    assert report['evidence_complete'] and report['paired_comparability_passed']
    assert report['candidate_runtime_checks_passed']
    assert report['versions']['baseline']['observed_unsuccessful'] == 36
    assert not report['performance_improvement_verified'] and not report['full_project_release_verified']
    end = json.loads((candidate[0] / 'measurement_end_state.json').read_text())
    end['actors'][0]['observation']['ready'] = False
    dump(candidate[0] / 'measurement_end_state.json', end)
    assert not audit_matrix(matrix, baseline, candidate, bm, cm)['candidate_runtime_checks_passed']
    end['actors'][0]['observation']['ready'] = True
    dump(candidate[0] / 'measurement_end_state.json', end)
    # A completed file cannot override a missing frame or a source changed later.
    dump(candidate[0] / 'recording_metrics.json', {'frames_written': 17999, 'empty_rgb_frames': 0, 'dropped_frames': 1})
    assert not audit_matrix(matrix, baseline, candidate, bm, cm)['candidate_runtime_checks_passed']
    (candidate[0] / 'source_snapshot/src/fixture.py').write_text('changed after snapshot')
    report = audit_matrix(matrix, baseline, candidate, bm, cm)
    assert not report['evidence_complete'] and any('snapshot bytes' in e['error'] for e in report['errors'])


def test_duplicate_case_and_falsified_conservation_are_rejected(tmp_path, matrix):
    b, bm = run(tmp_path, matrix, 0, 'baseline')
    c, cm = run(tmp_path, matrix, 0, 'candidate')
    report = audit_matrix(matrix, [b], [c, c], bm, cm)
    assert any('duplicate case' in e['error'] for e in report['errors'])
    path = c / 'outcomes.json'
    outcomes = json.loads(path.read_text())
    outcomes['requests'][1]['request_case_id'] = 'first'
    dump(path, outcomes)
    report = audit_matrix(matrix, [b], [c], bm, cm)
    assert any('IDs lost or duplicated' in e['error'] for e in report['errors'])
