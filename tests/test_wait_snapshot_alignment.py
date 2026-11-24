"""Independent auditor counterexamples; synthetic, not native acceptance."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from audit_wait_snapshot_alignment import review
from simpeople.core.journal import Journal


def fixture():
    world = {'session_id': 's', 'episode_id': 'e'}
    frame = {'source_tick': 29, 'relative_sim_time': 1}
    roots = {}; spawns = {}; tasks = {}; bindings = {}; actors = {}; routes = {}; pending = {}
    for i, name in enumerate(['a', 'b']):
        handle = '/'+name; rid = name+'-route'; tid = name+'-task'
        task = {**world, 'actor_id': name, 'actor_instance_id': name+'-instance', 'task_id': tid, 'control_epoch': 1}
        obs = dict(ready=True, position_m=[i*2, 0, 0], facing_direction=[0, -1, 0], native_task_id=i,
                   action='Idle', speed_mps=0, observation_sim_time=1, sample_frame_id=29)
        roots[name] = {**task, **obs, 'sim_time': 1, 'frame_identity': frame,
                      'position_source': 'BehaviorAgent.get_world_translation',
                      'traffic_body_instance_id': name+'-body', 'native_actor_prim_path': handle}
        spawns[handle] = {**task, 'prim_path': handle}
        tasks[tid] = task; bindings[rid] = task
        actors[handle] = dict(actor_id=name, traffic_body_instance_id=name+'-body', cached_position_m=[i*2, 0, 0],
                              observation_at_tick_start=copy.deepcopy(obs), current_route_id=rid)
        routes[rid] = dict(handle=handle, status='blocked', native_task_id=None,
                           blocked_details={'blocker_handles': ['/b' if name == 'a' else '/a']})
        pending[rid] = dict(key=rid, actor=handle, occupant_token=name+'-body', since=0, sequence=i+1,
                            wait_since=.5, state='waiting', scope='corridor', drainers=[], origin_cells=[[i, 0]], goal_cells=[[i+1, 0]])
    cycle = dict(members=['/a', '/b'], since_sim_time=0, duration_sim_s=1)
    event = {**world, 'cursor': 20, 'sim_time': 1, 'snapshot': dict(
        schema_version='simpeople.wait-cycle-snapshot.v1', complete_serialization=True, sim_time=1,
        nonfinite_value_paths=[], unsupported_value_paths=[], cycle=cycle, actors=actors,
        active_owner_routes={'/a': 'a-route', '/b': 'b-route'}, active_route_state=routes,
        fair_gate=dict(pending=pending, drainer_token_references={}))}
    video = dict(sim_time=1, frame=29, frame_identity=frame)
    report = {**world, 'cursor': 19, 'sim_time': 1, **cycle}
    return event, roots, video, spawns, tasks, bindings, report


def test_tick_start_sdk_and_post_decision_native_ids_are_not_falsely_equated():
    result = review(*fixture())
    assert result['snapshot_alignment_verified'] and not result['errors']
    assert result['actors'][0]['observed_native_task_id_at_tick_start'] == 0
    assert result['actors'][0]['route_native_task_id_after_decisions'] is None


@pytest.mark.parametrize('mutation', [
    lambda a: a[1]['a'].update(actor_instance_id='recreated'),
    lambda a: a[1]['a'].update(episode_id='old'),
    lambda a: a[1]['a'].update(control_epoch=3),
    lambda a: a[1]['a'].update(traffic_body_instance_id='recreated-body'),
    lambda a: a[1]['a'].update(native_actor_prim_path='/wrong'),
    lambda a: a[1]['a'].update(position_m=[.01, 0, 0]),
    lambda a: a[1]['a'].update(position_m=[float('nan'), 0, 0]),
    lambda a: a[1]['a'].update(speed_mps=float('nan')),
    lambda a: a[1]['a'].update(native_task_id=99),
    lambda a: a[1]['a'].update(action='Move'),
    lambda a: a[1]['a'].update(frame_identity={'source_tick': 28}),
    lambda a: a[2].update(sim_time=.9),
    lambda a: a[0]['snapshot']['actors']['/a']['observation_at_tick_start'].update(observation_sim_time=.9),
    lambda a: a[0]['snapshot']['actors']['/a']['observation_at_tick_start'].update(observation_sim_time=float('nan')),
    lambda a: a[0]['snapshot']['fair_gate']['pending']['a-route'].update(occupant_token='old-body'),
    lambda a: a[0]['snapshot']['fair_gate']['pending']['a-route'].update(since=2),
    lambda a: a[0]['snapshot']['fair_gate']['pending']['a-route'].update(sequence=2),
    lambda a: a[0]['snapshot']['active_route_state']['a-route']['blocked_details'].update(blocker_handles=[]),
    lambda a: a[5].pop('a-route'),
    lambda a: a[6].update(cursor=21),
    lambda a: a[0]['snapshot'].update(complete_serialization=False),
])
def test_wrong_generation_clock_identity_graph_or_memory_never_passes(mutation):
    args = copy.deepcopy(fixture()); mutation(args); result = review(*args)
    assert result['errors'] and not result['snapshot_alignment_verified']


def test_old_root_format_can_align_observations_but_cannot_certify_body_generation():
    args = fixture()
    del args[1]['a']['traffic_body_instance_id']
    result = review(*args)
    assert result['actual_observations_and_engine_identity_aligned']
    assert result['independent_body_generation_fields_missing'] == ['a']
    assert not result['snapshot_alignment_verified']


def test_generation_refs_cannot_be_silently_rebound():
    args = fixture(); snap = args[0]['snapshot']
    snap['fair_gate']['pending']['a-route']['drainers'] = ['b-body']
    snap['fair_gate']['drainer_token_references'] = {'b-body': {'kind': 'current_traffic_body_generation', 'handle': '/a'}}
    result = review(*args)
    assert result['errors'] and not result['snapshot_alignment_verified']


def test_quality_journal_copies_body_generation_without_mutating_sdk_observation(tmp_path):
    obs = dict(ready=True, position_m=[0, 0, 0], native_task_id=0)
    original = copy.deepcopy(obs)
    backend = SimpleNamespace(quality_sampling=True, instances={'/a': {'traffic_instance_id': 'body'}},
                              observe=lambda handle: obs)
    engine = SimpleNamespace(sim_time=1, session_id='s', episode_id='e', backend=backend,
        actors={'a': {'handle': '/a', 'actor_instance_id': 'engine-instance', 'task_id': None, 'control_epoch': 0}}, tasks={})
    journal = Journal(tmp_path, {})
    journal.sample(engine, {'source_tick': 0})
    for stream in [journal.trajectory, journal.events, journal.performance]: stream.close()
    row = json.loads((tmp_path/'trajectories.jsonl').read_text())
    assert row['actor_instance_id'] == 'engine-instance'
    assert row['traffic_body_instance_id'] == 'body' and row['native_actor_prim_path'] == '/a'
    assert obs == original
