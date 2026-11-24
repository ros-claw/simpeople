"""Geometry and ownership invariants; these rows are not native motion proof."""
import math
import pytest
from simpeople.core.traffic import ReservationGrid,FairGate
from simpeople.core.tail_release import StraightTail


def make(points=None,speed=1.2):
    points=points or [[0,0,0],[15,0,0]]
    grid=ReservationGrid({(x,y) for x in range(-5,20) for y in range(-5,20)},{})
    cells=set().union(*(grid.sweep(a,b) for a,b in zip(points,points[1:])))
    return grid,StraightTail(grid,points,cells,0,speed)


def move(tail,end,seconds):
    start=tail.last_position;first=tail.last_time;result=None
    steps=math.ceil(seconds*30)
    for i in range(1,steps+1):
        p=[start[j]+(end[j]-start[j])*i/steps for j in range(3)]
        result=tail.observe(p,first+seconds*i/steps)
        if result['remove']:tail.commit(result['remove'])
    return result


def test_only_wholly_passed_cells_removed_body_and_future_retained():
    grid,tail=make();move(tail,[6,0,0],5)
    assert tail.released and grid.footprint([0,0,0])<=tail.released
    assert not tail.released & grid.footprint([6,0,0])
    assert not tail.released & grid.sweep([4,0,0],[15,0,0])
    assert tail.original-tail.released >= grid.footprint([15,0,0])


def test_negative_direction_uses_cell_bounds_not_centres():
    grid,tail=make([[10,10,0],[-5,10,0]]);move(tail,[5,10,0],6)
    assert tail.released
    for cell in tail.released:
        center=grid.point(cell);half=grid.cell/2
        corners=[[center[0]+dx*half,center[1]+dy*half,0] for dx in [-1,1] for dy in [-1,1]]
        assert max(tail.project(p)[0] for p in corners)<tail.project([5,5,0])[0]-2


@pytest.mark.parametrize('points,speed',[
    ([[0,0,0],[5,0,0],[5,5,0]],1.2),
    ([[0,0,0],[8,0,0],[5,0,0]],1.2),
    ([[0,0,0],[15,0,0]],5),
    ([[0,0,0],[2,0,0]],1.2)])
def test_turns_reversals_fast_and_short_segments_keep_entire_claim(points,speed):
    grid,tail=make(points,speed)
    assert tail.disabled and not tail.observe([1,0,0],1)['remove'] and not tail.released


@pytest.mark.parametrize('position,delta,reason',[
    ([6,.4,0],.05,'off_path'),([5.8,0,0],1/30,'observed_speed'),
    ([6,0,0],.2,'sample_gap'),([5.7,0,0],.1,'regression'),([6,0,.2],1/30,'vertical_deviation')])
def test_anomaly_after_reclamation_requires_brake(position,delta,reason):
    _,tail=make();move(tail,[6,0,0],5)
    result=tail.observe(position,5+delta)
    assert result['brake']==reason and not result['remove']


def test_forward_spike_freezes_removals_but_does_not_disable_retreat_monitoring():
    _,tail=make();move(tail,[6,0,0],5)
    before=tail.released.copy();result=tail.observe([6.14,0,0],5+1/30)
    assert result['frozen']=='forward_sample_spike' and not result['remove'] and not result.get('brake')
    assert tail.observe([6.18,0,0],5+2/30)['frozen'] and tail.released==before
    result=tail.observe([5.88,0,0],5+2/30+.1)
    assert result['brake']=='regression' and tail.released==before


def test_same_tick_does_not_advance_progress_or_release_by_wallclock():
    _,tail=make();result=tail.observe([10,0,0],0)
    assert not result['remove'] and tail.peak==0 and not tail.released


def test_small_diagonal_deviation_cannot_reclaim_without_full_body_coverage():
    grid,tail=make([[-2.4232218265533447,-9.991792678833008,0],[-8.720002174377441,-7.557377815246582,0],[-8.75,-7.5,0]])
    # Recorded native root: only 4.3 cm off the line, but a grid corner is
    # outside the original swept cells. Disable before the first removal.
    tail.last_position=[-5.15,-8.96,0];tail.last_time=6.73
    result=tail.observe([-5.175839900970459,-8.953604698181152,0],6.766666666666652)
    assert result['disabled']=='grid_lane_change' and not result.get('brake') and not result['remove']
    assert not tail.released


def test_body_coverage_loss_before_any_reclamation_disables_without_braking():
    _,tail=make();tail.last_position=[.1,.1,0];tail.last_time=.1
    result=tail.observe([.2,.18,0],.2)
    assert result['disabled']=='body_outside_claim' and not result['brake'] and not result['remove']


def test_body_coverage_loss_after_reclamation_requires_stop_even_with_small_lateral_error():
    _,tail=make();move(tail,[6,0,0],5)
    # At 18 cm lateral deviation the .45m footprint reaches the next grid row.
    tail.observe([6,.09,0],5.05)
    result=tail.observe([6,.18,0],5.1)
    assert result['brake']=='body_outside_claim' and not result['remove']


def test_guard_trim_fences_generation_keeps_age_and_future_conflict():
    gate=FairGate();gate.request('old','a',{(0,0),(1,0),(2,0)},0,occupant_token='body-a');gate.grant('old',1)
    assert not gate.trim_active('old',{(0,0)},'recreated-body')
    assert gate.trim_active('old',{(0,0)},'body-a')
    gate.request('new','b',{(0,0),(2,0)},2)
    assert gate.allowed('new',{(0,0)}) and not gate.allowed('new',{(2,0)})
    assert gate.pending['old']['since']==0
    gate.waiting('old',3);assert not gate.trim_active('old',{(1,0)},'body-a')
