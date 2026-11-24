"""Planner observations and control-equivalence; no fresh Native qualification."""
import ast
import copy
import heapq
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from simpeople.core.path_diagnostics import report_search_wait, select_candidate
from simpeople.core.traffic import ReservationGrid, FairGate, ClearanceEdges
from simpeople.core.candidate_paths import destination as candidate_destination
from simpeople.core.route_history import history_path
from simpeople.backends.native.arrival_recovery import ArrivalRecoveryMixin


@pytest.fixture
def observer():
    events=[]
    class Grid:
        nodes={(0,0),(1,0)}
        def point(self,n):return [n[0]*1.25,n[1]*1.25,0]
        def __getattr__(self,name):raise AssertionError('diagnostics must not call '+name)
    backend=SimpleNamespace(now=3.,grid=Grid(),instances={'a':{'traffic_instance_id':'body-a'}},
                            emit=lambda kind,**data:events.append((kind,copy.deepcopy(data))))
    job={'goals':[[5.,0.,0.]],'goal_index':0,'requested_sim_time':1.5,'native_task_id':None,
         'status':'running','step':{'action':'move_to','target':[5.,0.,0.],'timeout_s':240}}
    obs={'position_m':[0.,0.,0.],'native_task_id':14,'action':'Idle','observation_sim_time':3.,
         'position_source':'BehaviorAgent.get_world_translation'}
    return backend,job,obs,events


def report(fixture,phase='start_candidate_unavailable',**kwargs):
    b,j,o,_=fixture
    report_search_wait(b,'a','r',j,o,phase,j['goals'][0],[(0,0),(1,0)],{(1,0)},**kwargs)


def test_reports_only_known_branch_and_candidates_without_inventing_cause(observer):
    b,j,o,events=observer;before=copy.deepcopy((j,o,b.instances));report(observer)
    kind,payload=events[0]
    assert kind=='traffic_path_search_wait' and payload['goal_candidates'] is None
    assert payload['start_candidates'][1]=={'node':[1,0],'point_m':[1.25,0.,0], 'in_blocked_set':True}
    assert payload['start_candidates'][0]['in_blocked_set'] is False
    assert payload['blocker_ids'] is None and not payload['physical_feasibility_verified']
    assert not payload['causal_blocker_verified'] and not payload['connection_results_recorded']
    assert payload['observed_native_task_id']==14 and payload['route_native_task_id'] is None
    assert {k:v for k,v in j.items() if k!='_path_diagnostic_last'}==before[0]
    assert (o,b.instances)==before[1:] and payload['target_m']==[5.,0.,0.]
    payload['target_m'][0]=999;payload['origin_m'][0]=999
    assert j['goals'][0]==[5.,0.,0.] and o['position_m']==[0.,0.,0.]


def test_rate_limit_uses_sim_clock_with_new_phase_goal_and_reset_distinguished(observer):
    b,j,o,events=observer;report(observer);report(observer);b.now=4.9;report(observer)
    assert len(events)==1
    b.now=5.;report(observer);assert len(events)==2
    b.now=5.1;report(observer,'grid_path_unavailable',start=(0,0),ends=[(1,0)],end=(1,0));assert len(events)==3
    j['goals'][0]=[6.,0,0];report(observer,'grid_path_unavailable');assert len(events)==4
    b.now=0.;report(observer,'grid_path_unavailable');assert len(events)==5
    assert events[-1][1]['sample_sim_time']==0.


@pytest.mark.parametrize('fault',['nan_origin','invalid_goal','nan_clock','invalid_phase','bad_node'])
def test_bad_diagnostic_data_is_explicitly_unavailable_not_an_activity_change(observer,fault):
    b,j,o,events=observer
    if fault=='nan_origin':o['position_m'][0]=float('nan')
    elif fault=='invalid_goal':j['goals'][0]=None
    elif fault=='nan_clock':b.now=float('nan')
    before=copy.deepcopy(j['step'])
    if fault=='bad_node':report_search_wait(b,'a','r',j,o,'start_candidate_unavailable',[5.,0,0],[(True,0)],set())
    else:report(observer,'wrong_phase' if fault=='invalid_phase' else 'start_candidate_unavailable')
    assert events[0][0]=='traffic_path_search_diagnostic_unavailable' and j['step']==before
    json.dumps(events,allow_nan=False)


def test_goal_footprint_uses_supplied_result_and_does_not_query_again(observer):
    _,_,_,events=observer
    report(observer,'goal_footprint_blocked',start=(0,0),ends=[(0,0)],end=(0,0),goal_cells={(0,0),(1,0)})
    assert events[0][1]['goal_blocked_cells']==[[1,0]]


def test_sink_failure_stays_visible_and_cannot_create_a_successful_record(observer):
    b,j,_,_=observer
    def failed(*args,**kwargs):raise OSError('journal is unavailable')
    b.emit=failed
    with pytest.raises(OSError):report(observer)
    assert '_path_diagnostic_last' not in j


class NativeParent:
    def stop(self,handle):self.commands.append(('stop',handle))
    def start(self,handle,spec):self.commands.append(('start',handle,copy.deepcopy(spec)));return 55


class ReplayBase(ArrivalRecoveryMixin,NativeParent):
    def __init__(self,fault,dynamic=False):
        self.now=3.;self.commands=[];self.events=[];self.queries=[];self.fault=fault
        self.local_yield_stops={}
        self.corridor_profile=False;nodes={(0,0),(1,0),(2,0)}
        edges={} if fault=='no_path' else {(0,0):[(1,0)],(1,0):[(0,0),(2,0)],(2,0):[(1,0)]}
        self.grid=ReservationGrid(nodes,edges)
        original_reserve=self.grid.can_reserve
        def can_reserve(*args,**kwargs):
            self.queries.append(('can_reserve',copy.deepcopy(args),copy.deepcopy(kwargs)))
            return False if fault=='no_start' else original_reserve(*args,**kwargs)
        self.grid.can_reserve=can_reserve
        goal=[.34,0.,0.] if fault=='goal_cell_blocked' else [2.5,0.,0.]
        if fault=='goal_cell_blocked':self.grid.claims['witness']={(1,0)}
        self.job={'handle':'a','status':'running','phase':'travel','retry_at':0.,'native_task_id':None,
                  'goals':[goal],'goal_index':0,'requested_sim_time':1.5,'retry_actor_id':'a',
                  'step':{'action':'move_to','target':goal,'timeout_s':240}}
        self.routes={'r':self.job};self.positions={'a':[0.,0.,0.]};self.instances={'a':{'traffic_instance_id':'body-a'}}
        self.runtime_policy={'goal_claim_wait_enabled':False,'dynamic_edges_enabled':dynamic,'candidate_repair_enabled':False}
        self.fair_gate=FairGate();self.fair_gate.request('r','a',{(1,0),(2,0)},1.5)
        self.world={'session_id':'s','episode_id':'e','actor_instance_id':'i','control_epoch':7,'deadline':241.5}

    def grid_connection(self,a,b,node_is_start=False):
        self.queries.append(('nav_connector',copy.deepcopy(a),copy.deepcopy(b),node_is_start))
        return not (self.fault=='no_goal' and node_is_start)

    def admit_reservation(self,handle,rid,job,points,**kwargs):
        self.queries.append(('admit',copy.deepcopy(points),copy.deepcopy(kwargs)))
        return self.grid.reserve_polyline(handle,points,self.positions)

    def emit(self,kind,**payload):self.events.append((kind,copy.deepcopy(payload)))


def compiled_backend(path):
    tree=ast.parse(path.read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ReservationNativeBackend')
    methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {'tick_route','block'}]
    wrapper=ast.Module(body=[ast.ClassDef(name='Replay',bases=[ast.Name(id='ReplayBase',ctx=ast.Load())],
                                        keywords=[],body=methods,decorator_list=[])],type_ignores=[])
    ast.fix_missing_locations(wrapper)
    ns={'ReplayBase':ReplayBase,'math':math,'heapq':heapq,'report_search_wait':report_search_wait,'select_candidate':select_candidate,'ClearanceEdges':ClearanceEdges,
        'history_path':history_path,'candidate_destination':candidate_destination}
    exec(compile(wrapper,str(path),'exec'),ns)
    return ns['Replay']


@pytest.mark.parametrize('fault,expected_phase',[
    ('no_start','start_candidate_unavailable'),('no_goal','goal_candidate_unavailable'),
    ('no_path','grid_path_unavailable'),('goal_cell_blocked','goal_footprint_blocked'),('success',None)])
@pytest.mark.parametrize('dynamic',[False,True])
def test_exact_old_and_new_route_keep_commands_queries_claims_and_task_budgets_equal(fault,expected_phase,dynamic):
    root=Path(__file__).parents[1]
    frozen=root/'reports/evidence/iteration_20261114_baseline_cancel_followup/implementation/src/simpeople/backends/native/reservations.py'
    old=compiled_backend(frozen)(fault,dynamic);new=compiled_backend(root/'src/simpeople/backends/native/reservations.py')(fault,dynamic)
    obs={'ready':True,'position_m':[0.,0.,0.],'speed_mps':0.,'action':'Idle','native_task_id':14,
         'observation_sim_time':3.,'position_source':'BehaviorAgent.get_world_translation'}
    old.tick_route('a','r',copy.deepcopy(obs));new.tick_route('a','r',copy.deepcopy(obs))
    assert old.commands==new.commands and old.queries==new.queries
    assert old.grid.claims==new.grid.claims and old.fair_gate.pending==new.fair_gate.pending
    assert old.world==new.world
    assert old.job=={k:v for k,v in new.job.items() if k!='_path_diagnostic_last'}
    assert old.events==[(k,v) for k,v in new.events if not k.startswith('traffic_path_search_')]
    observed=[v['planner_phase'] for k,v in new.events if k=='traffic_path_search_wait']
    if dynamic and fault=='goal_cell_blocked':expected_phase='goal_candidate_unavailable'
    assert observed==([] if expected_phase is None else [expected_phase])
    for kind,payload in new.events:
        if kind=='traffic_path_search_wait':assert payload['connection_results_recorded']


@pytest.mark.parametrize('connector_first,required',[(False,True),(True,True),(True,False)])
def test_selector_preserves_short_circuit_order_and_distinguishes_skipped_checks(connector_first,required):
    calls=[]
    def clearance(n):calls.append(('clearance',n));return n!=(1,0)
    def connector(n):calls.append(('connector',n));return n!=(2,0)
    selected,checks=select_candidate([(0,0),(1,0),(2,0),(3,0)],{(0,0)},clearance,connector,
                                    connector_first=connector_first,clearance_required=required)
    assert checks[0]['connector'] is None and checks[0]['swept_clearance'] is None
    if connector_first and not required:
        assert selected==(1,0) and calls==[('connector',(1,0))]
        assert checks[-1]['swept_clearance'] is None and checks[-1]['accepted']
    elif connector_first:
        assert selected==(3,0)
        assert calls==[('connector',(1,0)),('clearance',(1,0)),('connector',(2,0)),('connector',(3,0)),('clearance',(3,0))]
        assert checks[1]['swept_clearance'] is False and checks[2]['swept_clearance'] is None
    else:
        assert selected==(3,0)
        assert calls==[('clearance',(1,0)),('clearance',(2,0)),('connector',(2,0)),('clearance',(3,0)),('connector',(3,0))]
        assert checks[1]['connector'] is None and checks[2]['connector'] is False
