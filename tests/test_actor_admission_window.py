import pytest

from simpeople.motion.admission_window import ActorAdmissionWindows


def test_each_actor_starts_on_its_own_four_frames_without_needing_a_shared_phase():
    windows = ActorAdmissionWindows(['first', 'second'], 0.)
    for tick in range(1, 9):
        for actor, passed in [('first', tick <= 4), ('second', tick >= 5)]:
            ready = windows.observe(actor, tick/30, tick, passed)
            assert ready == (tick >= (4 if actor == 'first' else 8))
    assert windows.ready['first'] == [(tick/30, tick) for tick in range(1, 5)]
    assert windows.ready['second'] == [(tick/30, tick) for tick in range(5, 9)]


def test_duplicate_reads_and_frame_gaps_cannot_fill_an_admission_window():
    w = ActorAdmissionWindows(['actor'], 0.)
    for _ in range(20): assert not w.observe('actor', 1/30, 1, True)
    assert len(w.windows['actor']) == 1
    assert not w.observe('actor', 3/30, 3, True)
    assert w.windows['actor'] == [(3/30, 3)]
    assert not w.observe('actor', 4/30, 4, False)
    assert not w.windows['actor']


@pytest.mark.parametrize('stamp,frame', [(0., 1), (8.1, 243), (float('nan'), 3), (1/30, True)])
def test_no_clock_or_budget_relaxation(stamp, frame):
    w = ActorAdmissionWindows(['actor'], 0.)
    with pytest.raises(ValueError): w.observe('actor', stamp, frame, True)
