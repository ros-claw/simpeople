from scripts.check_master import validate_times


def test_middle_pts_shift_is_rejected_even_with_correct_count_and_endpoints():
    times=[i/30 for i in range(90)]
    assert not validate_times(times,30,90)
    times[41]+=.001
    assert validate_times(times,30,90)


def test_missing_frame_is_rejected():
    assert validate_times([i/30 for i in range(89)],30,90)
