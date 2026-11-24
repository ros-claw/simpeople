"""Offline extraction invariants; no native snapshot claimed by these fixtures."""
import copy
import json

from simpeople.core.traffic import FairGate, ReservationGrid, VerifiedLazyEdges
from simpeople.core.wait_snapshot import capture_wait_snapshot


def fixture():
    def forbidden(*_):
        raise AssertionError('observer may not query or modify NavMesh cache')
    grid=ReservationGrid({(0,0),(1,0)},VerifiedLazyEdges({(0,0),(1,0)},forbidden))
    grid.edges.cache[(0,0)]=[(1,0)];grid.claims['a']={(0,0)}
    gate=FairGate();gate.request('route-a','a',{(0,0),(1,0)},1,
                                drainers=['old-route','body-b','stale-body'],occupant_token='body-a')
    routes={'route-a':{'handle':'a','status':'blocked','phase':'travel','native_task_id':7,
                      'grid_visits':{(0,0):2},'goals':[[3,0,0]],'blocked_details':{'blocker_ids':['b']}},
            'old-route':{'handle':'b','status':'cancelled'}}
    return (grid,gate,routes,{'a':'route-a'},
            {'a':{'actor_id':'a','traffic_instance_id':'body-a'},'b':{'actor_id':'b','traffic_instance_id':'body-b'}},
            {'a':[0,0,0],'b':[2,0,0]},
            {'a':{'ready':True,'position_m':[0,0,0],'native_task_id':6,'observation_sim_time':3}},
            3,{'members':['a','b'],'since_sim_time':0},[],{})


def test_capture_does_not_query_lazy_edges_or_mutate_claims_age_and_routes():
    args=fixture();grid,gate,routes=args[:3]
    before=copy.deepcopy((grid.claims,grid.edges.cache,gate.pending,routes))
    result=capture_wait_snapshot(*args)
    assert result['complete_serialization']
    assert (grid.claims,grid.edges.cache,gate.pending,routes)==before
    assert result['active_route_state']['route-a']['native_task_id']==7
    assert result['actors']['a']['observation_at_tick_start']['native_task_id']==6
    assert result['actors']['a']['traffic_body_instance_id']=='body-a'
    assert 'actor_instance_id' not in result['actors']['a']
    assert result['grid']['edges_already_cached']['map_entries']==[[[0,0],[[1,0]]]]
    json.dumps(result,allow_nan=False)


def test_archived_snapshot_is_detached_from_later_live_mutations():
    args=fixture();result=capture_wait_snapshot(*args);before=copy.deepcopy(result)
    args[0].claims['a'].add((1,0));args[1].pending['route-a']['since']=99
    args[2]['route-a']['goals'][0][0]=99;args[5]['a'][0]=99
    args[6]['a']['position_m'][0]=99
    assert result==before


def test_route_and_body_tokens_are_distinct_and_reused_names_do_not_rebind_old_generation():
    args=fixture();args[4]['b']['traffic_instance_id']='recreated-body-b'
    result=capture_wait_snapshot(*args);refs=result['fair_gate']['drainer_token_references']
    assert refs['old-route']['status']=='cancelled'
    assert refs['body-b']['kind']=='not_in_current_instance_or_registered_route_maps'
    assert refs['stale-body']['kind']=='not_in_current_instance_or_registered_route_maps'


def test_bad_observations_are_explicit_not_nonstandard_json_or_silently_dropped():
    args=fixture();args[6]['a']['position_m'][0]=float('nan')
    args[2]['route-a']['blocked_details']['unexpected']=object()
    result=capture_wait_snapshot(*args)
    assert not result['complete_serialization']
    assert result['nonfinite_value_paths'] and result['unsupported_value_paths']
    json.dumps(result,allow_nan=False)
