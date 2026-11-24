"""Synthetic verifier faults, not a Native diagnostic acceptance."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from simpeople.core import traffic
from simpeople.core.path_diagnostics import report_search_wait,select_candidate

spec=importlib.util.spec_from_file_location('path_audit',Path(__file__).parents[1]/'scripts/audit_path_search_prefix.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


@pytest.fixture
def event():
    grid=traffic.ReservationGrid({(0,0),(2,0)},{})
    grid.claims={'/a':{(0,0)}};positions={'/a':[0.,0.,0.],'/witness':[10.,10.,0.]};events=[]
    b=SimpleNamespace(grid=grid,now=3.,instances={'/a':{'traffic_instance_id':'body'}},
                      emit=lambda kind,**data:events.append((kind,copy.deepcopy(data))))
    obs={'position_m':[0.,0.,0.],'native_task_id':14,'action':'Idle','observation_sim_time':3.,
         'position_source':'BehaviorAgent.get_world_translation'}
    job={'goals':[[2.5,0.,0.]],'goal_index':0,'requested_sim_time':1.5,'native_task_id':None,'status':'running'}
    blocked=grid.blocked('/a',positions)
    start,sc=select_candidate([(0,0)],blocked,lambda n:True,lambda n:True)
    end,gc=select_candidate([(2,0)],blocked,lambda n:True,lambda n:False,connector_first=True,clearance_required=True)
    report_search_wait(b,'/a','r',job,obs,'goal_candidate_unavailable',job['goals'][0],[(0,0)],blocked,
                       start=start,ends=[(2,0)],end=end,start_checks=sc,goal_checks=gc)
    kind,payload=events[0]
    return {'kind':kind,'payload':payload,'sim_time':3.,'source_tick':89,'actor_id':'person_020',
            'actor':{'binding':{'traffic_body_instance_id':'body','native_actor_prim_path':'/a'},
                     'observation':obs,'route':job,'route_id':'r'},
            'planner_inputs':{'cell_m':1.25,'margin_m':.45,'positions_m':positions},
            'claims':{h:sorted(cells) for h,cells in grid.claims.items()}}


def test_valid_telemetry_is_bound_without_claiming_a_navmesh_requery(event):
    result=audit.verify_event(event,traffic,True)
    assert result['phase']=='goal_candidate_unavailable'
    assert result['connector_requery_performed'] is False and result['causal_blocker_verified'] is False


@pytest.mark.parametrize('fault',['body','clock','task','origin','blocked','point','clearance','goal_clearance',
                                 'denominator','selection','unknown_phase','false_cause','node_count','policy'])
def test_inconsistent_or_overstated_planner_evidence_is_rejected(event,fault):
    p=event['payload']
    if fault=='body':p['body_instance_id']='foreign'
    elif fault=='clock':p['observation_sim_time']=2.
    elif fault=='task':p['observed_native_task_id']=999
    elif fault=='origin':event['planner_inputs']['positions_m']['/a']=[1.,0.,0.]
    elif fault=='blocked':p['start_candidates'][0]['in_blocked_set']=True
    elif fault=='point':p['start_candidates'][0]['point_m'][0]+=.01
    elif fault=='clearance':p['start_checks'][0]['swept_clearance']=False
    elif fault=='goal_clearance':p['goal_checks'][0]['swept_clearance']=True
    elif fault=='denominator':p['goal_checks']=[]
    elif fault=='selection':p['selected_goal']=[2,0]
    elif fault=='unknown_phase':p['planner_phase']='unreachable'
    elif fault=='false_cause':p['blocker_ids']=['guessed actor']
    elif fault=='node_count':p['node_count']=0
    else:p['goal_checks'][0]['clearance_required']=False
    with pytest.raises((ValueError,KeyError,TypeError,IndexError)):audit.verify_event(event,traffic,True)


def test_missing_run_or_unexercised_diagnostics_never_qualify(tmp_path):
    result=audit.audit(tmp_path,tmp_path,tmp_path/'case',tmp_path/'probe',tmp_path/'trace',tmp_path)
    assert not result['measurement_verified'] and not result['planner_diagnostics_verified']
