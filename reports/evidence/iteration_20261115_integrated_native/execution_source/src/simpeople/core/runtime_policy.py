"""Versioned local scheduling budgets; no Kit or model dependencies."""
import json
from pathlib import Path

DEFAULT_POLICY={'schema_version':'simpeople.runtime-policy.v1','queue_outside_capacity':8,
    'resource_waiter_capacity':32,'traffic_fairness_enabled':True,'dynamic_edges_enabled':False,'tail_release_enabled':False,'diagonal_tail_release_enabled':False,'candidate_repair_enabled':False,'goal_claim_wait_enabled':False,'seat_egress_selection_enabled':False,'cycle_drainage_enabled':False,'max_conflicting_bypasses':0,
    'max_wait_sim_s':30.,'cycle_detection_sim_s':3.,'recovery_after_wait_sim_s':8.,'max_recovery_attempts':2}

def load_policy(directory=None):
    path=Path(directory)/'runtime_policy.json' if directory else None
    supplied=json.loads(path.read_text()) if path and path.exists() else {}
    if set(supplied)-set(DEFAULT_POLICY):raise ValueError('unknown runtime policy field')
    value={**DEFAULT_POLICY,**supplied}
    if set(value)!=set(DEFAULT_POLICY) or value['schema_version']!=DEFAULT_POLICY['schema_version']:raise ValueError('unsupported runtime policy')
    for key in ['queue_outside_capacity','resource_waiter_capacity','max_conflicting_bypasses','max_recovery_attempts']:
        if isinstance(value[key],bool) or not isinstance(value[key],int) or not 0<=value[key]<=100:raise ValueError('invalid '+key)
    for key in ['max_wait_sim_s','cycle_detection_sim_s','recovery_after_wait_sim_s']:
        from .protocol import number
        number(value[key],key,.1,600)
    if not isinstance(value['traffic_fairness_enabled'],bool):raise ValueError('invalid fairness flag')
    if not isinstance(value['dynamic_edges_enabled'],bool):raise ValueError('invalid dynamic edge flag')
    if not isinstance(value['tail_release_enabled'],bool):raise ValueError('invalid tail release flag')
    if not isinstance(value['candidate_repair_enabled'],bool):raise ValueError('invalid candidate repair flag')
    if not isinstance(value['goal_claim_wait_enabled'],bool):raise ValueError('invalid goal claim wait flag')
    if not isinstance(value['seat_egress_selection_enabled'],bool):raise ValueError('invalid seat egress selection flag')
    if not isinstance(value['cycle_drainage_enabled'],bool):raise ValueError('invalid cycle drainage flag')
    if not isinstance(value['diagonal_tail_release_enabled'],bool):raise ValueError('invalid diagonal tail flag')
    if value['diagonal_tail_release_enabled'] and not value['tail_release_enabled']:raise ValueError('diagonal tail requires tail release')
    if value['max_conflicting_bypasses']!=0 or value['max_recovery_attempts']!=2:raise ValueError('this policy version supports zero bypasses and two recovery attempts')
    return value
