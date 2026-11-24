"""Closed graph cuts on synthetic receipts; no Native or contact qualification."""
import copy
import importlib.util
from pathlib import Path
import sys

import pytest

from simpeople.core import traffic

SCRIPTS=Path(__file__).parents[1]/'scripts'
spec=importlib.util.spec_from_file_location('cut_audit',SCRIPTS/'audit_cached_search_cut.py')
audit=importlib.util.module_from_spec(spec)
sys.path.insert(0,str(SCRIPTS))
try:spec.loader.exec_module(audit)
finally:sys.path.pop(0)


@pytest.fixture
def event():
    return {'actor_id':'person_020','source_tick':90,'sim_time':3.,
        'payload':{'planner_phase':'grid_path_unavailable','node_count':4,'agent':'/a',
                   'selected_start':[0,0],'selected_goal':[3,0],'blocked_cell_count':1},
        'cached_grid_graph':{'kind':'verified_lazy_cache','nodes':[[0,0],[1,0],[2,0],[3,0]],
            'adjacency':[{'node':[0,0],'neighbors':[[1,0]]}],
            'unqueried_nodes_are_unknown':True,'additional_navmesh_queries':0},
        'planner_inputs':{'cell_m':1.25,'margin_m':.45,
                          'positions_m':{'/a':[0.,0.,0.],'/body':[1.25,0.,0.]}},
        'claims':{'/lease':[[1,0]]}}


def test_actual_frontier_can_have_both_body_and_claim_contributors(event):
    result=audit.verify_cut(event,traffic,False)
    assert result['reachable_component_verified']
    assert result['reachable_nodes']==[[0,0]]
    assert result['frontier_contributors']==[{'cell':[1,0],'body_owners':['/body'],'reservation_owners':['/lease']}]
    assert result['individual_causal_blocker_verified'] is False
    assert result['physical_feasibility_verified'] is False


def test_graph_without_outgoing_edges_proves_only_a_sampled_closed_component(event):
    event['cached_grid_graph']['adjacency'][0]['neighbors']=[]
    result=audit.verify_cut(event,traffic,False)
    assert result['reachable_component_verified'] and result['blocked_frontier']==[]


def test_missing_explicit_adjacency_is_empty_not_an_unqueried_lazy_node(event):
    graph=event['cached_grid_graph'];graph.update(kind='explicit_adjacency',unqueried_nodes_are_unknown=False,adjacency=[])
    assert audit.verify_cut(event,traffic,False)['reachable_node_count']==1


@pytest.mark.parametrize('fault',['dynamic','phase','denominator','float_node','duplicate_node','foreign_neighbor',
                                 'duplicate_adjacency','diagonal','extra_query','unknown_disguised','uncached_reachable',
                                 'free_path','blocked_start','blocked_goal','blocked_denominator'])
def test_incomplete_or_inconsistent_cuts_are_not_accepted(event,fault):
    graph=event['cached_grid_graph'];payload=event['payload']
    if fault=='phase':payload['planner_phase']='start_candidate_unavailable'
    elif fault=='denominator':payload['node_count']=9
    elif fault=='float_node':graph['nodes'][0][0]=0.
    elif fault=='duplicate_node':graph['nodes'].append([0,0])
    elif fault=='foreign_neighbor':graph['adjacency'][0]['neighbors']=[[9,0]]
    elif fault=='duplicate_adjacency':graph['adjacency']*=2
    elif fault=='diagonal':graph['adjacency'][0]['neighbors']=[[2,0]]
    elif fault=='extra_query':graph['additional_navmesh_queries']=1
    elif fault=='unknown_disguised':graph['unqueried_nodes_are_unknown']=False
    elif fault in {'uncached_reachable','free_path'}:
        event['planner_inputs']['positions_m'].pop('/body');event['claims']={};payload['blocked_cell_count']=0
        if fault=='free_path':graph['adjacency'] += [{'node':[1,0],'neighbors':[[2,0]]},{'node':[2,0],'neighbors':[[3,0]]}]
    elif fault=='blocked_start':event['claims']['/lease']=[[0,0]];payload['blocked_cell_count']=2
    elif fault=='blocked_goal':event['claims']['/lease']=[[3,0]];payload['blocked_cell_count']=2
    elif fault=='blocked_denominator':payload['blocked_cell_count']=2
    with pytest.raises((ValueError,KeyError,TypeError)):
        audit.verify_cut(event,traffic,fault=='dynamic')


def test_receipt_audit_does_not_mutate_observed_inputs(event):
    before=copy.deepcopy(event)
    audit.verify_cut(event,traffic,False)
    assert event==before


def test_missing_run_or_old_trace_cannot_acquire_new_native_credit(tmp_path):
    result=audit.audit(tmp_path,tmp_path,tmp_path/'case',tmp_path/'probe',tmp_path/'trace',tmp_path)
    assert not result['measurement_verified'] and not result['cached_search_cut_verified']
