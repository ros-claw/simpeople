"""Audit saved Native poses independently of the SDK/export/probe math.

This is a static export diagnostic, not generated motion or cancel acceptance.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

OWNER = ('session_id', 'episode_id', 'actor_id', 'actor_instance_id', 'control_epoch', 'task_id')
PACKAGING_METADATA = {'src/rosclaw_simpeople.egg-info/'+name for name in (
    'PKG-INFO','SOURCES.txt','dependency_links.txt','entry_points.txt','requires.txt','top_level.txt')}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def body_pose(values, facing):
    values = np.asarray(values, dtype=float)
    facing = np.asarray(facing, dtype=float)
    if (values.ndim != 2 or values.shape[1] != 7 or not np.isfinite(values).all()
            or facing.shape != (3,) or not np.isfinite(facing).all()
            or np.linalg.norm(facing[:2]) < .9
            or np.max(abs(np.linalg.norm(values[:, 3:], axis=-1)-1)) > 1e-3):
        raise ValueError('invalid actual pose or heading')
    yaw = math.atan2(facing[0], -facing[1])
    rotation = Rotation.from_rotvec([0, 0, -yaw])
    return rotation.apply(values[:, :3]-values[0, :3]), rotation * Rotation.from_quat(values[:, 3:])


def compare(reference, row):
    if row['joint_paths'] != reference['joint_paths'] or len(set(row['joint_paths'])) != len(row['joint_paths']):
        raise ValueError('actual/reference joint order differs')
    wanted, wanted_rotation = body_pose(reference['world_pose'], reference['actual_observation']['facing_direction'])
    actual, actual_rotation = body_pose(row['world_pose'], row['actual_observation']['facing_direction'])
    if wanted.shape != actual.shape or len(wanted) != len(row['joint_paths']):
        raise ValueError('joint array shape differs')
    distance = np.linalg.norm(wanted-actual, axis=-1)
    angle = np.degrees((wanted_rotation.inv()*actual_rotation).magnitude())
    return {'max_position_m':float(distance.max()), 'max_angle_deg':float(angle.max()),
            'worst_position_joint':row['joint_paths'][int(distance.argmax())],
            'worst_angle_joint':row['joint_paths'][int(angle.argmax())]}


def audit(folder, plan_path):
    folder, plan_path = Path(folder), Path(plan_path)
    errors, measurements, inputs = [], [], {}
    lifecycle_reported = False
    try:
        read = lambda name: json.loads((folder/name).read_text())
        lines = lambda name: [json.loads(x) for x in (folder/name).open()]
        plan = json.loads(plan_path.read_text())
        if folder.name != plan['run_id'] or plan['model_requests_added'] != 0:
            raise ValueError('wrong static diagnostic plan')
        for name, expected in plan['frozen_files'].items():
            if sha(name) != expected:
                raise ValueError('frozen experiment input changed: '+name)
        original = Path(plan['source'])/'source_manifest.json'
        if sha(original) != plan['source_manifests'][plan['source']]:
            raise ValueError('original source manifest changed')
        original = json.loads(original.read_text())
        manifest = read('source_manifest.json')
        bundle = Path(plan['inputs'])
        expected_source={n:h for n,h in original.items()
                         if n.split('/')[0] in {'src','configs','schemas'} and n not in PACKAGING_METADATA}
        # The frozen probe replaces precisely these two configuration files
        # before import. Diagnostic actions are tied to the frozen export bundle.
        for name,value in [('configs/custom_actions.json',sha(bundle/'actions.json')),
                           ('configs/custom_action_acceptance.json',hashlib.sha256(b'{}\n').hexdigest())]:
            if name in expected_source:
                expected_source[name]=value
        if ({n:h for n,h in manifest.items() if n.split('/')[0] in {'src','configs','schemas'}}
                != expected_source):
            raise ValueError('actual snapshot omitted or replaced execution source')
        if ('reports/capability_matrix.json' in original
                and manifest.get('reports/capability_matrix.json')!=original['reports/capability_matrix.json']):
            raise ValueError('capability input changed')
        if manifest['probe.py'] != sha(plan['argv'][1]):
            raise ValueError('actual probe differs from frozen probe')
        for name, expected in manifest.items():
            path = folder/'source_snapshot'/name
            if not path.resolve().is_relative_to((folder/'source_snapshot').resolve()) or sha(path) != expected:
                raise ValueError('run source snapshot changed: '+name)
        for name, expected in json.loads((bundle/'bundle_manifest.json').read_text())['files_sha256'].items():
            if sha(bundle/name) != expected:
                raise ValueError('exported diagnostic asset changed: '+name)
        registry = json.loads((bundle/'actions.json').read_text())
        done, metrics = read('completed.json'), read('recording_metrics.json')
        stamps = lines('video_timestamps.jsonl')
        if (not done['harness_completed']
                or len(stamps) != done['frames'] or metrics['frames_written'] != len(stamps)
                or metrics['empty_rgb_frames'] or metrics['dropped_frames']):
            raise ValueError('incomplete native diagnostic or RGB capture')
        for i, stamp in enumerate(stamps):
            if stamp['frame'] != i or stamp['frame_identity']['source_tick'] != i or (i and abs(stamp['sim_time']-stamps[i-1]['sim_time']-1/30) > 1e-7):
                raise ValueError('RGB source frame/clock mismatch')
        poses = lines('native_pose_history.jsonl'); trajectories = lines('trajectories.jsonl'); events = lines('events.jsonl')
        actual = {(r['actor_id'], r['frame_identity']['source_tick']):r for r in trajectories}
        if len(actual) != len(trajectories):
            raise ValueError('duplicate actual body frame')
        acceptance = read('generated_native_acceptance.json')
        lifecycle_reported = bool(done['functional_expected_matched'] and acceptance['passed'])
        phases = {p['name']:p for p in acceptance['phases']}
        expected_phases = {'rt_'+case+'_'+variant for case in plan['native_cases'] for variant in ('full','reference')}
        if {p for p in phases if p.startswith('rt_')} != expected_phases:
            raise ValueError('missing declared static comparison phase')
        actors={t['actor_id'] for t in phases[sorted(expected_phases)[0]]['tasks']}
        if len(actors)!=2 or any(len(phases[p]['tasks'])!=2 or
                {t['actor_id'] for t in phases[p]['tasks']}!=actors for p in expected_phases):
            raise ValueError('both declared actors required in every static phase')
        bodies, prims = {}, {}
        for phase in sorted(expected_phases):
            for task in phases[phase]['tasks']:
                aid = task['actor_id']; target = task['steps'][0]['target']
                if task['status'] != 'succeeded' or task['steps'] != [{'action':'custom_action','target':target,'duration_s':3.,'timeout_s':10.}]:
                    raise ValueError('static custom task or original budget changed')
                binding = [e for e in events if e['kind']=='native_task_bound' and e.get('task_id')==task['task_id']]
                if len(binding)!=1 or type(binding[0].get('native_task_id')) is not int or any(binding[0].get(k)!=task[k] for k in OWNER):
                    raise ValueError('one same-owner native custom binding required')
                sdk = binding[0]['native_task_id']
                reference = registry['roundtrip_sources'][registry['actions'][target]['actor_source']]
                selected = [r for r in poses if r['phase']==phase and r['actor_id']==aid and .5 <= r['phase_time_s'] <= 2.5]
                if len(selected)<59 or selected[-1]['sim_time']-selected[0]['sim_time']<1.9:
                    raise ValueError('continuous static diagnostic window missing')
                measured = []
                for i, row in enumerate(selected):
                    # This frozen probe writes pose rows AFTER journal.sample increments
                    # its counter. RGB and trajectory source_tick remain zero based.
                    index = row['source_tick']-1
                    stamp = stamps[index]; body = actual[aid,index]; obs = row['actual_observation']
                    if (row['sim_time'] != stamp['sim_time'] or body['frame_identity'] != stamp['frame_identity']
                            or body['sim_time'] != row['sim_time'] or row['activity_task_id'] != task['task_id']
                            or any(row['task'].get(k)!=task[k] or body.get(k)!=task[k] for k in OWNER)
                            or row['task']['status']!='running' or row['actor_instance_id']!=task['actor_instance_id']
                            or obs != {k:body[k] for k in obs if k in body}
                            or not obs['ready'] or obs['observation_sim_time'] != row['sim_time']
                            or obs['position_source']!='BehaviorAgent.get_world_translation'
                            or obs['native_task_id']!=sdk or obs['action']!=target
                            or obs['sim_paused'] or obs['root_changed_without_sim_time']
                            or np.linalg.norm(np.asarray(row['world_pose'])[0,:3]-obs['position_m'])>1e-5):
                        raise ValueError('pose/SDK/body/owner/RGB identity mismatch')
                    if i and (row['source_tick']!=selected[i-1]['source_tick']+1 or abs(row['sim_time']-selected[i-1]['sim_time']-1/30)>1e-7):
                        raise ValueError('static pose stream is not continuous 30Hz')
                    generation, prim = body['traffic_body_instance_id'], body['native_actor_prim_path']
                    if not generation or not prim or bodies.setdefault(aid,generation)!=generation or prims.setdefault(aid,prim)!=prim:
                        raise ValueError('physical body changed during comparison')
                    measured.append(compare(reference,row))
                position=max(x['max_position_m'] for x in measured); angle=max(x['max_angle_deg'] for x in measured)
                measurements.append({'actor_id':aid,'phase':phase,'samples':len(selected),
                    'actual_span_s':selected[-1]['sim_time']-selected[0]['sim_time'],
                    'max_joint_position_error_m':position,'max_joint_angle_error_deg':angle,
                    'within_2cm_2deg':position<=.02 and angle<=2})
        if len(bodies)!=2 or len(set(bodies.values()))!=2 or len(set(prims.values()))!=2:
            raise ValueError('two distinct Native bodies required')
        if not all(m['within_2cm_2deg'] for m in measurements):
            raise ValueError('actual static roundtrip exceeds original pose tolerance')
        for name in ['native_pose_history.jsonl','trajectories.jsonl','events.jsonl','video_timestamps.jsonl',
                     'source_manifest.json','completed.json','generated_native_acceptance.json']:
            inputs[name]=sha(folder/name)
    except (ValueError, OSError, KeyError, TypeError, IndexError) as error:
        errors.append(str(error))
    return {'run_id':folder.name,'static_pose_measurements_verified':not errors,'errors':errors,
            'native_lifecycle_reported_passed':lifecycle_reported,
            'measurements':measurements,'inputs_sha256':inputs,'plan_sha256':sha(plan_path),
            'qualified_generated_native_rigs':[],'model_requests_added':0,
            'scope':'Static Human81 SDK export diagnostic only. Frame-counter offset is checked against actual clocks. No generated motion, contact, cancellation or general rig qualification.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--plan',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();result=audit(a.run,a.plan);Path(a.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'verified':result['static_pose_measurements_verified'],'errors':result['errors']}))
    raise SystemExit(0 if result['static_pose_measurements_verified'] else 2)
