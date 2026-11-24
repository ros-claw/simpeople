"""Audit a closed raw SDK counterfactual; never certify the public runtime.

Two actors are deliberately outside Engine tasks. Source, actual body/RGB
correspondence, observed stop and continuous motion receive separate grades.
"""
import argparse
import hashlib
import json
from pathlib import Path

from simpeople.motion.entry import entry_error
from simpeople.motion.executed_quality import angles
from simpeople.motion.recovery_quality import IDENTITY, fixed_heading_error, review_actor


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def lines(path):
    return [json.loads(line) for line in Path(path).open()]


def source_review(plan, run):
    source = Path(plan['source']); snap = run/'source_snapshot'
    assert sha(source/'source_manifest.json') == plan['source_manifest_sha256']
    original = read(source/'source_manifest.json'); actual = read(run/'source_manifest.json')
    for name, digest in original.items():
        rel = Path(name)
        assert not rel.is_absolute() and '..' not in rel.parts
        assert str(rel) == name and (source/rel).resolve().is_relative_to(source.resolve())
        assert sha(source/name) == digest, name
    for name, digest in actual.items():
        rel = Path(name)
        assert not rel.is_absolute() and '..' not in rel.parts and str(rel) == name
        assert (snap/rel).resolve().is_relative_to(snap.resolve())
        assert sha(snap/rel) == digest, name
    spec = read(snap/'spec.json')
    replacements = {'configs/custom_action_acceptance.json': sha_bytes(b'{}\n'),
        'configs/custom_actions.json': sha_bytes((json.dumps({'actions': spec['actions']}, indent=2)+'\n').encode())}
    expected = {n for n in original if n.split('/')[0] in {'src', 'configs', 'schemas', 'reports'}}
    assert set(actual) == expected | {'probe.py', 'spec.json'}, 'snapshot member set differs'
    for name in expected:
        assert actual[name] == replacements.get(name, original[name]), name
    # probe_v2.py was intentionally snapshotted under probe.py, not its basename.
    probe = Path(plan['argv'][1]); declared = plan['frozen_files'][str(probe)]
    assert sha(probe) == declared == actual['probe.py']
    assert actual['spec.json'] == plan['frozen_files'][plan['argv'][plan['argv'].index('--spec')+1]]
    for path, digest in {**plan['frozen_files'], **plan['external_inputs']}.items():
        assert sha(path) == digest, path
    for key in ['source_registry', 'atlas_registry']:
        assert sha(spec[key]) == spec[key+'_sha256']
    inputs = read(run/'sdk_settings.json')['source_inputs_sha256']
    assert inputs == plan['external_inputs'], 'actual loaded asset manifest differs'
    assert {str(p.relative_to(snap)) for p in snap.rglob('*') if p.is_file()
            and '__pycache__' not in p.parts} == set(actual)
    return spec, {'execution_source_verified': True, 'snapshot_members': len(actual),
                  'source_manifest_sha256': plan['source_manifest_sha256'],
                  'executed_probe_sha256': declared, 'asset_files_verified': len(inputs)}


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def compare_entry(spec, incoming, reference):
    mode = spec.get('recovery_entry_alignment', 'body_facing')
    if mode == 'fixed_declared_heading':
        # This dedicated raw probe explicitly starts both actors facing +Y.
        # No arbitrary-heading qualification follows from this diagnostic.
        if (spec.get('declared_placement_facing') != [0, 1, 0]
                or reference.get('declared_placement_facing') != [0, 1, 0]):
            raise ValueError('fixed-heading diagnostic placement differs')
        return fixed_heading_error(incoming['world_pose'], reference['entry']['world_pose'])
    if mode != 'body_facing':
        raise ValueError('unknown diagnostic entry alignment')
    entry = reference['entry']
    return entry_error(incoming['world_pose'], incoming['actual_observation']['facing_direction'],
        {'world_pose': entry['world_pose'], 'facing_direction': entry['actual_observation']['facing_direction']})


def audit(plan_path, folder):
    import numpy as np
    run = Path(folder); plan = read(plan_path)
    assert run.name == plan['run_id']
    spec, source = source_review(plan, run)
    completed = read(run/'completed.json'); trial = read(run/'recovery_trial.json')
    assert completed['harness_completed'] and completed['raw_sdk_diagnostic_only']
    assert spec['cancel_budget_s'] == 15 and spec['cancel_elapsed_s'] == 13
    assert abs(trial['cancel_sim_time']-trial['started_sim_time']-13) < 1e-7
    video = lines(run/'video_timestamps.jsonl'); roots = lines(run/'trajectories.jsonl')
    history = lines(run/'recovery_history.jsonl'); count = completed['frames']
    assert count == len(video) and all(v['frame'] == i for i, v in enumerate(video))
    assert all(abs(video[i]['sim_time']-video[i-1]['sim_time']-1/30) < 1e-7 for i in range(1, count))
    assert abs(completed['duration_s']-count/30) < 1e-7
    capture = read(run/'recording_metrics.json')
    assert capture['frames_written'] == count and capture['dropped_frames'] == capture['empty_rgb_frames'] == 0
    rgb = {r['frame_identity']['source_tick']: r for r in video}
    journal = {(r['actor_id'], r['frame_identity']['source_tick']): r for r in roots}
    assert len(rgb) == count and len(journal) == len(roots) == 3*count
    actors = ['baseline', 'recovery']; streams = {a: [] for a in actors}
    assert len(history) == count*2
    for row in history:
        aid = row['actor_id']; assert aid in streams
        frame = row['frame_identity']['source_tick']; image = rgb[frame]; root = journal[aid, frame]
        assert row['frame_identity'] == root['frame_identity'] == image['frame_identity']
        assert row['sim_time'] == root['sim_time'] == image['sim_time']
        assert root['task_id'] is None, 'diagnostic actor acquired an Engine task'
        assert all(row[k] == root[k] for k in IDENTITY)
        obs = row['actual_observation']
        for key in ['ready', 'action', 'native_task_id', 'position_source', 'position_m',
                    'speed_mps', 'observation_sim_time', 'facing_direction']:
            assert obs[key] == root[key], key
        pose = np.asarray(row['world_pose'])
        for alias, index in root['quality_joint_indices'].items():
            assert np.linalg.norm(pose[index, :3]-root['joints_m'][alias]) < 1e-6
            assert angles(pose[index, 3:], np.asarray(root['joint_rotations_xyzw_stage'][alias])) < .001
        streams[aid].append(row)
    results = []
    for aid in actors:
        rows = streams[aid]; assert len(rows) == count
        selected = [r for r in rows if r['sim_time'] >= trial['cancel_sim_time']-1e-7]
        assert selected[0] == trial['before_cancel'][aid]
        assert selected[-1]['sim_time'] == trial['end_sim_time']
        anchor = next(r for r in rows if r['sim_time'] == trial['anchors'][aid]['sim_time'])
        assert anchor == trial['anchors'][aid]
        result = review_actor(selected, cancel_time=trial['cancel_sim_time'],
            idle_requested_time=trial['cancel_sim_time'] if aid == 'baseline' else trial['idle_requested_time'],
            retired_id=trial['retired_native_ids'][aid], expected_idle_id=trial['idle_request_native_ids'].get(aid),
            recovery_id=trial['recovery_native_task_id'] if aid == 'recovery' else None)
        a, b = np.asarray(anchor['world_pose']), np.asarray(selected[0]['world_pose'])
        result['gap_from_own_preclip_m'] = float(np.linalg.norm(a[:, :3]-b[:, :3], axis=-1).max())
        result['gap_from_own_preclip_deg'] = float(angles(a[:, 3:], b[:, 3:]).max())
        result['non_neutral_at_cancel'] = result['gap_from_own_preclip_m'] > .05 or result['gap_from_own_preclip_deg'] > 10
        results.append(result)
    chosen = trial['chosen_recovery']; incoming = trial['before_cancel']['recovery']
    entry = spec['references'][chosen]['entry']
    assert entry['joint_paths'] == incoming['joint_paths']
    quality = compare_entry(spec, incoming, spec['references'][chosen])
    assert quality == trial['entry_quality'] and quality['passed']
    witness = [r for r in roots if r['actor_id'] == 'witness']
    assert len(witness) == count and all(r['task_id'] == trial['witness_task']['task_id'] for r in witness)
    witness_distance = sum(np.linalg.norm(np.asarray(a['position_m'])-b['position_m']) for a, b in zip(witness[1:], witness[:-1]))
    assert witness_distance > 1
    return {'measurement_verified': True, 'source': source, 'run_id': run.name,
            'actual_frames': count, 'actual_entry_quality': quality, 'actors': results,
            'entry_alignment': spec.get('recovery_entry_alignment', 'body_facing'),
            'witness_actual_distance_m': float(witness_distance),
            'raw_sdk_recovery_quality_verified': results[1]['sdk_stop_quality_verified'],
            'plugin_cancel_verified': False, 'qualified_generated_native_rigs': [],
            'full_project_release_verified': False,
            'inputs_sha256': {n: sha(run/n) for n in ['source_manifest.json', 'recovery_trial.json',
                'recovery_history.jsonl', 'trajectories.jsonl', 'video_timestamps.jsonl', 'recording_metrics.json']},
            'scope': 'One raw SDK13s non-neutral counterfactual. Body/world/source/RGB clocks checked; root speed and a matched entry do not override any failed joint continuity pair. No public cancellation, sole contact, hotload, streaming or generated rig certificate.'}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for key in ['plan', 'run', 'output']: p.add_argument('--'+key, required=True)
    a = p.parse_args(); result = audit(a.plan, a.run)
    with Path(a.output).open('x') as stream:
        stream.write(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: result[k] for k in ['measurement_verified', 'actual_frames',
          'raw_sdk_recovery_quality_verified', 'plugin_cancel_verified']}))
    raise SystemExit(0 if result['raw_sdk_recovery_quality_verified'] else 2)
