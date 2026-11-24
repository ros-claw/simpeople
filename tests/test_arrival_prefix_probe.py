"""Probe bootstrap/observer contracts, without Kit or a simulated acceptance."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import signal
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/(name+'.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('mode', ['off', 'on'])
def test_prefix_bootstrap_preserves_600s_case_and_freezes_actual_trace(tmp_path, monkeypatch, mode):
    builder = load('prepare_arrival_prefix_probe'); shared = tmp_path/'shared'
    (shared/'scripts').mkdir(parents=True); (shared/'runs').mkdir()
    frozen = ROOT/'reports/evidence/iteration_20261114_fixture_motion_screens/implementation/scripts/bench_native_runtime.py'
    (shared/'scripts/bench_native_runtime.py').write_bytes(frozen.read_bytes())
    for name in ['src/simpeople/core/workloads.py', 'src/simpeople/tools/runtime_contract.py',
                 'src/simpeople/backends/native/probe_scenes.py', 'src/simpeople/backends/native/idle_profile.py',
                 'src/simpeople/core/release_scene.py']:
        p = shared/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('# snapshot-only fixture\n')
    source = tmp_path/'source'
    for folder in ['src', 'configs', 'schemas', 'reports']:
        (source/folder).mkdir(parents=True)
    (source/'reports/capability_matrix.json').write_text('{}')
    original = {'case_id': 'release_narrow_30_seed17_v2', 'duration_s': 600,
                'actors': [{'actor_id': 'a'+str(i)} for i in range(30)],
                'requests': [{'request_case_id': 'r'+str(i), 'deadline_s': 600} for i in range(60)]}
    case = tmp_path/'case.json'; case.write_text(json.dumps(original))
    trace = ROOT/'scripts/arrival_prefix_trace.py'; script = tmp_path/'probe.py'
    code = builder.generate(shared, trace); script.write_text(code)
    tree = ast.parse(code)
    cut = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.ImportFrom) and n.module == 'isaacsim')
    prefix = ast.Module(body=tree.body[:cut], type_ignores=[])
    monkeypatch.setattr(sys, 'argv', [str(script), '--run-id', 'unit', '--case', str(case),
                                      '--source-root', str(source), '--arrival-recovery', mode])
    monkeypatch.setattr(signal, 'signal', lambda *args: None)
    exec(compile(prefix, str(script), 'exec'), {'__file__': str(script), '__name__': 'bootstrap_test'})
    output = shared/'runs/unit'
    assert json.loads((output/'source_snapshot/harness/case.json').read_text()) == original
    assert json.loads(case.read_text()) == original
    assert json.loads((output/'bootstrap.json').read_text())['arrival_recovery'] == mode
    manifest = json.loads((output/'source_manifest.json').read_text())
    assert manifest['harness/arrival_prefix_trace.py'] == hashlib.sha256(trace.read_bytes()).hexdigest()
    assert 'isaacsim' not in sys.modules


def test_unreviewed_harness_cannot_silently_change_prefix(tmp_path):
    shared = tmp_path/'shared'; (shared/'scripts').mkdir(parents=True)
    (shared/'scripts/bench_native_runtime.py').write_text('print("not the frozen benchmark")')
    with pytest.raises(ValueError): load('prepare_arrival_prefix_probe').generate(shared, ROOT/'scripts/arrival_prefix_trace.py')


def trace_fixture():
    class Agent:
        def get_action_task_id(self): return 11
        def get_task_name(self, tid): return 'Idle'
        def get_world_translation(self): return [0., 0., 0.]
        def is_enabled(self): return True
        def get_task_elapsed_time(self, tid): return .6
    actor = lambda aid: {'handle': aid, 'actor_instance_id': 'instance_'+aid, 'control_epoch': 1,
                         'task_id': 'task_'+aid, 'seat': None}
    engine = SimpleNamespace(actors={aid: actor(aid) for aid in ['person_020', 'person_001']},
        tasks={'task_'+aid: {'task_id': 'task_'+aid, 'status': 'running'} for aid in ['person_020', 'person_001']},
        public=copy.deepcopy, sim_time=2., session_id='s', episode_id='e',
        journal=SimpleNamespace(frames=0), event_sequence=0,
        resources=SimpleNamespace(snapshot=lambda: {'owners': {'seat': 'another'}}),
        queues=SimpleNamespace(snapshot=lambda: {'queue': []}))
    backend = SimpleNamespace(assert_thread=lambda: None, agent=lambda _: Agent(),
        on_event=lambda *args, **kwargs: None, observations={},
        observe=lambda _: {'ready': True, 'native_task_id': 0, 'position_m': [0., 0., 0.],
                           'observation_sim_time': 2., 'position_source': 'BehaviorAgent.get_world_translation'},
        instances={aid: {'traffic_instance_id': 'body_'+aid} for aid in engine.actors},
        owner_routes={'person_020': 'r'}, routes={'r': {'native_task_id': 12, 'arrival_stop_id': 11,
                        'arrival_identity': ['person_020', 'body_person_020', 'r', 12, [12, 0, 0]]}},
        task_state=lambda handle, tid: 'running' if tid == 11 else 'succeeded',
        to_public=lambda p: list(p), fair_gate=SimpleNamespace(pending={}),
        grid=SimpleNamespace(claims={'person_020': {(0, 0), (1, 0)}, 'another': {(8, 0)}}),
        timeline=SimpleNamespace(is_playing=lambda: True), arrival_recovery_probe_enabled=True)
    return backend, engine


def test_observer_keeps_cached_and_actual_sdk_ids_separate_without_mutation(tmp_path):
    backend, engine = trace_fixture(); before = copy.deepcopy((engine.actors, engine.tasks, backend.routes, backend.grid.claims))
    observer = load('arrival_prefix_trace').ArrivalPrefixTrace(backend, engine, tmp_path)
    observer.sample({'source_tick': 0}); observer.close()
    assert (engine.actors, engine.tasks, backend.routes, backend.grid.claims) == before
    row = json.loads((tmp_path/'arrival_recovery_frames.jsonl').read_text())
    actual = row['actors']['person_020']
    assert actual['observation']['native_task_id'] == 0 and actual['binding']['actual_sdk_task_id'] == 11
    assert actual['native_status'] == {'11': 'running', '12': 'succeeded'}
    assert row['claims']['another'] == [[8, 0]]
    assert json.loads((tmp_path/'arrival_trace_metrics.json').read_text())['read_errors'] == 0


def test_sdk_read_failure_is_recorded_and_never_replaced_with_success(tmp_path):
    backend, engine = trace_fixture()
    def failed(*args): raise RuntimeError('actual SDK status unavailable')
    backend.task_state = failed
    observer = load('arrival_prefix_trace').ArrivalPrefixTrace(backend, engine, tmp_path)
    observer.sample({'source_tick': 0}); observer.close()
    row = json.loads((tmp_path/'arrival_recovery_frames.jsonl').read_text())
    assert row['actors']['person_020']['native_status']['12'] is None
    assert row['actors']['person_020']['binding']['read_errors']
    assert json.loads((tmp_path/'arrival_trace_metrics.json').read_text())['read_errors'] > 0


def test_critical_event_reads_before_forwarding_and_restores_original_sink(tmp_path):
    backend, engine = trace_fixture(); forwarded = []
    def original(kind, **payload):
        forwarded.append((kind, copy.deepcopy(payload))); engine.event_sequence += 1
    backend.on_event = original
    backend.observations['person_020'] = (2., backend.observe('person_020'))
    observer = load('arrival_prefix_trace').ArrivalPrefixTrace(backend, engine, tmp_path)
    before = copy.deepcopy((backend.routes, backend.grid.claims, engine.actors))
    payload = {'agent': 'person_020', 'route_id': 'r', 'retired_native_task_id': 12}
    backend.on_event('traffic_arrival_shortfall', **payload)
    observer.close()
    assert backend.on_event is original and forwarded == [('traffic_arrival_shortfall', payload)]
    assert (backend.routes, backend.grid.claims, engine.actors) == before
    direct = json.loads((tmp_path/'arrival_recovery_direct_events.jsonl').read_text())
    assert direct['event_cursor_after'] == 1 and direct['source_tick'] == 0
    assert direct['actor']['binding']['actual_sdk_task_id'] == 11
    assert direct['actor']['observation']['native_task_id'] == 0


def test_event_reader_failure_still_forwards_original_runtime_event(tmp_path):
    backend, engine = trace_fixture(); forwarded = []
    backend.on_event = lambda kind, **payload: forwarded.append(kind)
    observer = load('arrival_prefix_trace').ArrivalPrefixTrace(backend, engine, tmp_path)
    backend.on_event('traffic_arrival_shortfall', agent='unknown-body', route_id='r')
    observer.close()
    assert forwarded == ['traffic_arrival_shortfall']
    assert json.loads((tmp_path/'arrival_recovery_direct_events.jsonl').read_text())['capture_error']


def test_path_failure_snapshot_captures_existing_inputs_without_requery_or_stop(tmp_path):
    backend,engine=trace_fixture();forwarded=[]
    backend.on_event=lambda kind,**payload:forwarded.append((kind,copy.deepcopy(payload)))
    backend.positions={'person_020':[0.,0.,0.],'person_001':[8.,0.,0.]}
    backend.grid.cell=1.25;backend.grid.margin=.45
    backend.grid.nodes={(0,0),(1,0)};backend.grid.edges={(0,0):[(1,0)]}
    backend.observations['person_020']=(2.,backend.observe('person_020'))
    before=copy.deepcopy((backend.positions,backend.grid.claims,engine.actors,backend.routes))
    observer=load('arrival_prefix_trace').ArrivalPrefixTrace(backend,engine,tmp_path)
    payload={'agent':'person_020','route_id':'r','planner_phase':'grid_path_unavailable'}
    backend.on_event('traffic_path_search_wait',**payload);observer.close()
    assert (backend.positions,backend.grid.claims,engine.actors,backend.routes)==before
    assert forwarded==[('traffic_path_search_wait',payload)]
    event=json.loads((tmp_path/'arrival_recovery_direct_events.jsonl').read_text())
    assert event['planner_inputs']=={'positions_m':before[0],'cell_m':1.25,'margin_m':.45}
    assert event['claims']['another']==[[8,0]]
    assert event['cached_grid_graph']['adjacency']==[{'node':[0,0],'neighbors':[[1,0]]}]


def test_graph_observer_never_materializes_unqueried_lazy_edges():
    from simpeople.core.traffic import ReservationGrid, VerifiedLazyEdges
    def forbidden(*args):raise AssertionError('observer issued a NavMesh query')
    edges=VerifiedLazyEdges({(0,0),(1,0),(2,0)},forbidden)
    edges.cache={(0,0):[(1,0)]}
    grid=ReservationGrid(edges.nodes,edges)
    before=copy.deepcopy(edges.cache)
    receipt=load('arrival_prefix_trace').cached_graph_snapshot(grid)
    assert edges.cache==before
    assert receipt['unqueried_nodes_are_unknown'] is True
    assert receipt['adjacency']==[{'node':[0,0],'neighbors':[[1,0]]}]
    receipt['adjacency'][0]['neighbors'].clear()
    assert edges.cache==before


def test_unknown_graph_reader_refuses_to_guess():
    with pytest.raises(ValueError):
        load('arrival_prefix_trace').cached_graph_snapshot(SimpleNamespace(nodes={(0,0)},edges=SimpleNamespace()))
