from simpeople.core.cinema import CinematicCamera, rail


def test_core_camera_is_fixed_across_actual_actor_motion_and_pause():
    camera=CinematicCamera('master')
    first=camera.pose(44*30, {'patrol_orange':[1,2,0]})
    assert camera.pose(44*30, {'patrol_orange':[10,20,0]})==first
    last=camera.pose(68*30-1, {'patrol_orange':[30,10,0]})
    assert first['eye_m']==last['eye_m'] and first['look_at_m']==last['look_at_m']


def test_rail_eases_into_and_out_of_endpoints():
    keys=[(0,[0,0,3],[0,1,1]),(10,[10,0,3],[10,1,1])]
    assert rail(0,keys)[0]==[0,0,3]
    assert rail(10,keys)[0]==[10,0,3]
    assert rail(.01,keys)[0][0] < .000001
    assert 10-rail(9.99,keys)[0][0] < .000001


def test_follow_uses_root_planar_position_not_head_bob():
    camera=CinematicCamera('master')
    low=camera.pose(10*30,{'patrol_orange':[0,0,0]})
    high=camera.pose(10*30+1,{'patrol_orange':[0,0,.3]})
    assert low['look_at_m'][2]==high['look_at_m'][2]==1


def test_continuous_handoffs_do_not_jump_lens_or_pose():
    camera=CinematicCamera('master')
    before=camera.pose(40*30-1,{'jogger':[18,-6.25,0]})
    after=camera.pose(40*30,{'jogger':[18,-6.25,0]})
    assert before['eye_m']==after['eye_m'] and before['focal_mm']==after['focal_mm']
    before=camera.pose(80*30-1,{})
    after=camera.pose(80*30,{})
    assert max(abs(a-b) for a,b in zip(before['look_at_m'],after['look_at_m']))<1e-4
    assert before['focal_mm']==after['focal_mm']
