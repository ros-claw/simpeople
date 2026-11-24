from simpeople.core.traffic import FairGate,WaitGraph,ReservationGrid

def test_old_infeasible_route_blocks_continuous_conflicting_newcomers():
    gate=FairGate(max_wait_sim_s=12);grid=ReservationGrid({(0,0),(1,0)},{});grid.claims['holder']={(0,0)}
    gate.request('old','old_actor',{(0,0),(1,0)},0,drainers=['holder_generation'])
    for now in range(1,10):
        key=f'new_{now}';gate.request(key,key,{(1,0)},now)
        # This candidate is physically feasible even while the older one is not.
        assert grid.can_reserve(key,{(1,0)},{})
        assert not gate.allowed(key,{(1,0)})
        gate.cancel(key)
    grid.release('holder')
    assert gate.allowed('old',{(0,0),(1,0)}) and grid.reserve('old',{(0,0),(1,0)},{})
    result=gate.grant('old',10)
    assert result['wait_sim_s']<=12 and result['conflicting_bypasses']==0

def test_preexisting_holder_can_drain_but_recreated_generation_cannot():
    gate=FairGate();gate.request('old','old',{(1,0)},1,drainers=['occupant_v1'])
    gate.request('occupant_v1','same_name',{(1,0)},2);gate.request('occupant_v2','same_name',{(1,0)},3)
    assert gate.allowed('occupant_v1',{(1,0)}) and not gate.allowed('occupant_v2',{(1,0)})

def test_unrelated_routes_run_in_parallel_and_cancel_clears_fence():
    gate=FairGate();gate.request('old','a',{(0,0)},0);gate.request('new','b',{(1,0)},0)
    assert gate.allowed('new',{(1,0)})
    gate.cancel('old');assert gate.allowed('new',{(0,0)})

def test_same_body_may_leave_after_route_change_but_may_not_enter_deeper():
    gate=FairGate();gate.request('waiting','waiter',{(0,0),(1,0)},1,drainers=['body_v1'])
    gate.request('new_route','occupant',{(0,0),(2,0)},2,occupant_token='body_v1',origin_cells={(0,0)})
    assert gate.allowed('new_route',{(0,0),(2,0)},exit_cells={(2,0)})
    assert not gate.allowed('new_route',{(0,0),(1,0)},exit_cells={(1,0)})
    gate.request('recreated','occupant',{(0,0),(2,0)},3,occupant_token='body_v2',origin_cells={(0,0)})
    assert not gate.allowed('recreated',{(0,0),(2,0)},exit_cells={(2,0)})

def test_partial_progress_preserves_old_route_priority_until_conflict_is_cleared():
    gate=FairGate();gate.request('old','west',{(0,0),(1,0)},0)
    gate.grant('old',1)  # only a short approach segment, not the full crossing
    gate.request('new','east',{(1,0)},2)
    assert not gate.allowed('new',{(1,0)})
    gate.request('old','west',{(0,0),(1,0)},3);gate.waiting('old',3)
    assert gate.pending['old']['since']==0 and gate.allowed('old',{(1,0)})
    gate.cancel('old');assert gate.allowed('new',{(1,0)})

def test_existing_goal_occupant_can_vacate_goal_without_exiting_the_entire_corridor():
    gate=FairGate()
    gate.request('old','waiter',{(0,0),(1,0),(2,0)},0,drainers=['body_v1'],goal_cells={(2,0)})
    gate.request('leave','occupant',{(2,0),(1,0)},1,occupant_token='body_v1',origin_cells={(2,0)})
    assert gate.allowed('leave',{(2,0),(1,0)},exit_cells={(1,0)})
    assert not gate.allowed('leave',{(2,0)},exit_cells={(2,0)})
    gate.request('new','newcomer',{(2,0),(1,0)},2,occupant_token='body_v2',origin_cells={(2,0)})
    assert not gate.allowed('new',{(2,0),(1,0)},exit_cells={(1,0)})

def test_verified_escape_allows_existing_occupants_initial_inside_segment():
    gate=FairGate()
    gate.request('old','waiter',{(0,0),(1,0)},0,drainers=['body'],goal_cells={(0,0)})
    gate.request('escape','occupant',{(0,0),(2,0)},1,occupant_token='body',origin_cells={(0,0)})
    # The first centering segment still ends inside the goal; without a full
    # escape proof it cannot bypass the guard. The physical claim is unchanged.
    assert not gate.allowed('escape',{(0,0)},exit_cells={(0,0)})
    assert gate.allowed('escape',{(0,0)},exit_cells={(2,0)})
    gate.request('outsider','new',{(0,0),(2,0)},2,occupant_token='new_body',origin_cells={(0,0)})
    assert not gate.allowed('outsider',{(0,0)},exit_cells={(2,0)})

def test_occupied_goal_fence_does_not_monopolize_unrelated_corridor_and_preserves_age():
    gate=FairGate()
    gate.request('old','a',{(2,0)},0,goal_cells={(2,0)},scope='occupied_goal')
    gate.request('new','b',{(0,0)},1)
    assert gate.allowed('new',{(0,0)}) and not gate.allowed('new',{(2,0)})
    # Goal holder has left. Already-present traffic can drain; new conflicting
    # arrivals must respect the original age, not the scope-change timestamp.
    gate.request('old','a',{(0,0),(1,0),(2,0)},2,drainers=['new'],goal_cells={(2,0)})
    assert gate.pending['old']['since']==0 and gate.allowed('new',{(0,0)})
    gate.request('later','c',{(1,0)},3)
    assert not gate.allowed('later',{(1,0)})

def test_wait_budget_violation_does_not_expire_a_live_reservation():
    gate=FairGate(max_wait_sim_s=2);gate.request('blocked','a',{(0,0)},0)
    assert gate.violations(3)[0]['max_wait_sim_s']==2 and 'blocked' in gate.pending
    assert not gate.violations(4)

def test_persistent_cycle_is_reported_once_and_can_be_detected_after_recurrence():
    graph=WaitGraph(3);cycle={'a':{'b'},'b':{'a'},'outside':{'b'}}
    assert not graph.update(cycle,0) and not graph.update(cycle,2)
    assert graph.update(cycle,3)[0]['members']==['a','b']
    assert not graph.update(cycle,4)
    graph.update({},5);assert not graph.update(cycle,6)
    assert graph.update(cycle,9)
