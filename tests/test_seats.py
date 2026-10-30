import math
from simpeople.core.seats import SeatProfile

def test_oriented_backrest_and_revision_invalidation():
    chair=SeatProfile('chair',(3,4,0),yaw_rad=math.pi/2)
    assert chair.clearance([2.75,4,.78])<0
    assert chair.clearance([3.5,4,.78])>.5
    assert chair.clearance([2.75,4,1.4],.085)>0
    assert chair.signature('asset1','motion1')!=chair.signature('asset1','motion2')
    assert chair.signature('asset1','motion1')!=SeatProfile('chair',(3,4,0),yaw_rad=math.pi/2,revision='new').signature('asset1','motion1')

def test_head_clearance_is_separate_from_allowed_back_contact():
    chair=SeatProfile('chair',(0,0,0))
    tests=chair.proxy_clearances({'Head':[0,.25,1.15],'Neck1':[0,.25,1.0],'Chest':[0,.2,.9]})
    assert tests['Head']<0 and tests['Neck1']<0 and tests['chest_back_capsule']<0


def test_reclined_back_local_box():
    angle=math.radians(15)
    profile=SeatProfile('reclined',(0,0,0),back_center_local_m=(0,.35,.78),back_tilt_rad=angle)
    p=[0,.35+math.sin(angle)*.3,.78+math.cos(angle)*.3]
    assert profile.clearance(p)<0
    assert profile.clearance([0,-.2,1.1],.05)>0
