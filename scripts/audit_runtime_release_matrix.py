"""Audit closed release inputs/results; never launches or changes a native run.

Baseline failures remain comparable observations. Missing runs, changed input,
unsubmitted dependent requests and incomplete captures cannot become successes.
This auditor does not grade MotionBench, CommandBench or performance improvement.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from simpeople.core.workloads import case_hash


def read(path):
    return json.loads(path.read_text())


def source_view(manifest):
    return {k: v for k, v in manifest.items()
            if k.startswith(('src/', 'configs/', 'schemas/')) or k == 'reports/capability_matrix.json'}


def audit_run(folder, spec, source_manifest):
    folder = Path(folder)
    case = read(folder / 'workload.json')
    outcomes = read(folder / 'outcomes.json')
    expected_ids = {r['request_case_id'] for r in case['requests']}
    rows = outcomes['requests']
    assert all(r.get('expected_outcome') == 'succeeded' for r in case['requests']), 'ordinary positive release inputs required'
    assert len(expected_ids) == len(case['requests']) == spec['requests']
    assert case['case_id'] == spec['case_id'] and case_hash(case) == spec['case_sha256'] == outcomes['case_sha256'], 'case changed'
    assert outcomes['scheduled'] == outcomes['denominator'] == len(rows) == len(expected_ids), 'denominator changed'
    assert len({r['request_case_id'] for r in rows}) == len(rows) and {r['request_case_id'] for r in rows} == expected_ids, 'request IDs lost or duplicated'
    counts = dict(Counter(r['state'] for r in rows))
    assert counts == outcomes['counts'] and outcomes['conservation_passed'], 'outcome conservation mismatch'
    assert outcomes['submitted'] == sum(r.get('submitted_at_s') is not None for r in rows), 'submission count mismatch'
    assert outcomes['admitted'] == sum(r.get('admitted_at_s') is not None for r in rows), 'admission count mismatch'
    done = read(folder / 'completed.json')
    assert done['harness_completed'] and abs(done['duration_s'] - 600) < 1e-5, 'measurement not closed at600s'
    recording = read(folder / 'recording_metrics.json')
    captured = (done['frames'] == recording['frames_written'] == 18000
                and recording['empty_rgb_frames'] == recording['dropped_frames'] == 0)
    manifest = read(folder / 'source_manifest.json')
    assert source_view(manifest) == source_view(source_manifest) and source_view(manifest), 'runtime source version changed'
    for relative, digest in manifest.items():
        assert hashlib.sha256((folder / 'source_snapshot' / relative).read_bytes()).hexdigest() == digest, 'source snapshot bytes changed: ' + relative
    runtime = read(folder / 'runtime_contract.json')
    runtime_audit = read(folder / 'runtime_audit.json')
    assert runtime_audit['planned_requests'] == len(expected_ids) and runtime_audit['outcome_counts'] == counts
    end = read(folder / 'measurement_end_state.json')
    actual = {a['actor_id']: a for a in end['actors']}
    expected_actors = {a['actor_id'] for a in case['actors']}
    assert set(actual) == expected_actors and len(end['actors']) == len(expected_actors), 'actors missing or duplicated'
    cycles = {aid: actual[aid]['completed_activities'] for aid in sorted(actual)}
    readback_ready = all(a.get('actor_instance_id') and a.get('observation', {}).get('ready')
        and a['observation'].get('position_source') == 'BehaviorAgent.get_world_translation'
        for a in actual.values())
    summary = read(folder / 'acceptance_summary.json')
    proxies = summary['trajectory_proxies']
    success = counts.get('succeeded', 0)
    return {'run_id': folder.name, 'case_id': case['case_id'], 'denominator': len(expected_ids),
            'submitted': outcomes['submitted'], 'admitted': outcomes['admitted'], 'counts': counts,
            'succeeded': success, 'unsuccessful': len(expected_ids) - success,
            'unsuccessful_fraction': (len(expected_ids) - success) / len(expected_ids),
            'within_2_percent_completion_target': (len(expected_ids) - success) / len(expected_ids) <= .02,
            'completed_cycles': cycles, 'every_actor_completed_two_cycles': all(v >= 2 for v in cycles.values()),
            'actual_pose_readback_ready': readback_ready,
            'complete_capture': captured, 'wait_budget_violations': runtime_audit['wait_budget_violations'],
            'harness_functional_expected_matched': done['functional_expected_matched'],
            'admission_bounds_passed': runtime_audit['admission_bounds_passed'],
            'sustained_root_overlaps': len(proxies['sustained_overlap_segments']),
            'root_discontinuities': len(proxies['root_discontinuities']),
            'compatibility_sha256': runtime['compatibility_sha256'],
            'shared_harness': {k: v for k, v in manifest.items() if k == 'bench_native_runtime.py' or k.startswith('harness/') and k != 'harness/case.json'},
            'idle_settings': read(folder / 'sdk_idle_settings.json')}


def audit_matrix(matrix, baseline, candidate, baseline_source, candidate_source):
    matrix = Path(matrix)
    manifest = read(matrix / 'matrix_manifest.json')
    assert len(manifest['cases']) == 18 and len({r['case_id'] for r in manifest['cases']}) == 18
    specs = {r['case_id']: r for r in manifest['cases']}
    for spec in specs.values():
        path = matrix / (spec['case_id'] + '.json')
        assert hashlib.sha256(path.read_bytes()).hexdigest() == spec['file_sha256'], 'frozen input file changed'
    results = {}
    errors = []
    for name, folders, source in [('baseline', baseline, baseline_source), ('candidate', candidate, candidate_source)]:
        rows = {}
        for folder in folders:
            try:
                case_id = read(Path(folder) / 'workload.json')['case_id']
                assert case_id in specs and case_id not in rows, 'unexpected or duplicate case'
                row = audit_run(folder, specs[case_id], source)
                rows[case_id] = row
            except (AssertionError, ValueError, KeyError, OSError, TypeError) as exc:
                errors.append({'version': name, 'run': str(folder), 'error': str(exc)})
        results[name] = {'cases': rows, 'missing_cases': sorted(set(specs) - set(rows)),
                         'planned_denominator': sum(s['requests'] for s in specs.values()),
                         'observed_denominator': sum(r['denominator'] for r in rows.values()),
                         'observed_succeeded': sum(r['succeeded'] for r in rows.values()),
                         'observed_unsuccessful': sum(r['unsuccessful'] for r in rows.values())}
    pairs = []
    for case_id in sorted(set(results['baseline']['cases']) & set(results['candidate']['cases'])):
        a, b = (results[v]['cases'][case_id] for v in ['baseline', 'candidate'])
        pairs.append({'case_id': case_id, 'same_runtime': a['compatibility_sha256'] == b['compatibility_sha256'],
                      'same_harness': a['shared_harness'] == b['shared_harness'] and bool(a['shared_harness']),
                      'candidate_overlaps_not_increased': b['sustained_root_overlaps'] <= a['sustained_root_overlaps'],
                      'candidate_discontinuities_not_increased': b['root_discontinuities'] <= a['root_discontinuities']})
    complete = not errors and all(not r['missing_cases'] for r in results.values())
    comparable = complete and len(pairs) == 18 and all(p['same_runtime'] and p['same_harness'] for p in pairs)
    candidate_checks = comparable and all(r['within_2_percent_completion_target'] and r['every_actor_completed_two_cycles']
        and r['actual_pose_readback_ready'] and r['complete_capture'] and r['harness_functional_expected_matched'] and r['admission_bounds_passed'] and r['wait_budget_violations'] == 0
        for r in results['candidate']['cases'].values()) and all(p['candidate_overlaps_not_increased'] and p['candidate_discontinuities_not_increased'] for p in pairs)
    return {'schema_version': 'simpeople.runtime-release-matrix-audit.v1',
            'matrix_manifest_sha256': hashlib.sha256((matrix / 'matrix_manifest.json').read_bytes()).hexdigest(),
            'source_bindings_sha256': {name: hashlib.sha256(json.dumps(source_view(source), sort_keys=True).encode()).hexdigest()
                                      for name, source in [('baseline', baseline_source), ('candidate', candidate_source)]},
            'evidence_complete': complete, 'paired_comparability_passed': comparable,
            'candidate_runtime_checks_passed': candidate_checks, 'versions': results, 'pairs': pairs, 'errors': errors,
            'performance_improvement_verified': False, 'full_project_release_verified': False,
            'limits': ['Baseline failures remain in the comparison; no baseline success requirement masks improvements.',
                       'Partial observed totals are not full-matrix success rates. Missing cases never pass.',
                       'Wait percentiles, individual worst waits and unserved lower bounds still require their separate paired analysis.',
                       'Each actor completing both frozen cycles is an additional conservative check; it is reported separately from the2% request completion target.',
                       'This consumes local closed-run artifacts; it does not replace native execution, MotionBench, CommandBench or visual review.']}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--matrix', required=True)
    p.add_argument('--baseline-source-manifest', required=True)
    p.add_argument('--candidate-source-manifest', required=True)
    p.add_argument('--baseline-runs', nargs='*', default=[])
    p.add_argument('--candidate-runs', nargs='*', default=[])
    p.add_argument('--output', required=True)
    args = p.parse_args()
    result = audit_matrix(args.matrix, args.baseline_runs, args.candidate_runs,
                          read(Path(args.baseline_source_manifest)), read(Path(args.candidate_source_manifest)))
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k not in {'versions', 'pairs'}}, indent=2))
    return 0 if result['candidate_runtime_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
