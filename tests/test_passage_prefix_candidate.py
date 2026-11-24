import ast
import importlib.util
import json
from pathlib import Path

import pytest

from simpeople.core.passage_prefix import zone_from_approaches
from simpeople.core.traffic import polyline_prefix, simplify_polyline

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('passage_candidate', ROOT/'scripts/prepare_passage_prefix_candidate.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


def method():
    code = (ROOT/'src/simpeople/backends/native/reservations.py').read_text()
    # The controlled experiment isolates the previously measured 4m horizon;
    # product defaults retain 12m and are never silently changed by the helper.
    old = "horizon=(18. if job['step'].get('gait')=='run' else 12.) if len(self.instances)>12 else None"
    assert code.count(old) == 1
    code = code.replace(old, "horizon=(18. if job['step'].get('gait')=='run' else 4.) if len(self.instances)>12 else None")
    tree = ast.parse(code)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    body = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'start_continuous_corridor')
    node = ast.ClassDef(name='Candidate', bases=[ast.Name(id='Parent', ctx=ast.Load())], keywords=[], body=[body], decorator_list=[])
    class Parent:
        def start(self, handle, spec):
            self.calls.append(spec)
            return 7
    scope = dict(Parent=Parent, polyline_prefix=polyline_prefix, simplify_polyline=simplify_polyline)
    import math
    scope['math'] = math
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), 'actual_candidate_method', 'exec'), scope)
    return scope['Candidate']


@pytest.mark.parametrize('admit', [True, False])
def test_actual_native_method_reserves_the_whole_exit_before_submitting_any_command(admit):
    b = method()()
    b.instances = {str(i): {} for i in range(13)}
    b.segment = lambda start, goal: [list(start), list(goal)]
    b.passage_no_stop_probe_zones = [zone_from_approaches('door', [-2., -10., 0.], [2., -10., 0.], 1.25)]
    b.calls = []; b.events = []; b.checked = []
    b.emit = lambda kind, **p: b.events.append((kind, p))
    b.grid = type('Grid', (), {'claims': {'actor': {1, 2}}})()
    def admission(handle, rid, job, points, **kw):
        b.checked.append((points, kw))
        return admit
    b.admit_reservation = admission
    b.runtime_policy = {'tail_release_enabled': False}
    job = dict(goal_index=0, goals=[[5.25, -10., 0.]], step={'gait': 'walk'},
               status='running', requested_sim_time=0.)
    result = b.start_continuous_corridor('actor', 'route', job, {'position_m': [-5.25, -10., 0.]})
    assert result is admit
    assert b.checked[0][0][-1] == pytest.approx([2.1, -10., 0.])
    assert b.checked[0][1] == {'polyline': True}
    assert job['requested_sim_time'] == 0. and job['goals'] == [[5.25, -10., 0.]]
    assert len(b.calls) == int(admit)
    if admit:
        assert b.calls[0]['target'] == pytest.approx([2.1, -10., 0.])
        assert job['continuous_next_goal_index'] == 0


def test_new_source_fingerprint_covers_the_helper_and_does_not_inherit_qualification(tmp_path):
    base = ROOT/'reports/evidence/iteration_20261115_integrated_native/execution_source'
    result = builder.prepare(base, builder.sha(base/'source_manifest.json'), tmp_path/'source')
    assert not result['production_source_installed'] and not result['previous_native_proof_transferred']
    manifest = json.loads((tmp_path/'source/source_manifest.json').read_text())
    assert manifest[builder.MODULE] == builder.sha(ROOT/builder.MODULE)
    assert 'core/passage_prefix.py' in (tmp_path/'source/src/simpeople/core/gesture_profiles.py').read_text()
    assert set(result['changed_files']) == {
        builder.MODULE, 'src/simpeople/backends/native/reservations.py',
        'src/simpeople/core/gesture_profiles.py', 'configs/native_gesture_catalog.json'}
    with pytest.raises(ValueError):
        builder.integrate(builder.integrate((base/'src/simpeople/backends/native/reservations.py').read_text()))
