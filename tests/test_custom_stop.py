import copy
from types import SimpleNamespace

import pytest

from simpeople.backends.native.custom_stop import needs_settlement, ready


@pytest.mark.parametrize('entry,wanted', [
    ({'playback_mode':'out_and_back'},True),
    ({'playback_mode':'loop','canonical_entry':{'world_pose':'reference'}},True),
    ({'playback_mode':'transition_then_hold','canonical_entry':{'world_pose':'reference'}},True),
    ({'playback_mode':'loop'},False), ({'canonical_entry':{}},False),
    ({'canonical_entry':'invalid'},False), ({},False), (None,False),
])
def test_only_phased_or_canonical_actions_need_the_extra_exit_gate(entry,wanted):
    assert needs_settlement(entry) is wanted


class Backend:
    def __init__(self):
        self.now=0.; self.current=38; self.states={35:'failed',38:'running'};self.events=[]
        self.record={'retired_native_task_id':35,'idle_request_native_task_id':38,
                     'requested_sim_time':0.,'actual_idle_times':[]}
        self.instances={'actor':{'custom_stop':self.record}}
        self.api=SimpleNamespace(get_agent=lambda handle:self)
        self.timeline=SimpleNamespace(get_current_time=lambda:self.now)
        self.on_event=lambda kind,**payload:self.events.append((kind,payload))
    def assert_thread(self):pass
    def get_action_task_id(self):return self.current
    def task_state(self,handle,tid):return self.states[tid]
    def observation(self,tick):
        self.now=tick/30
        return {'ready':True,'action':'Idle','native_task_id':38,'speed_mps':0.,'observation_sim_time':self.now}


def test_fourteen_idle_frames_are_not_a_half_second_window():
    b=Backend()
    for tick in range(1,15):assert not ready(b,'actor',b.observation(tick),True)
    assert len(b.record['actual_idle_times'])==14 and not b.events
    assert not ready(b,'actor',b.observation(15),True)
    assert ready(b,'actor',b.observation(16),True)
    assert len(b.events)==1 and b.events[0][1]['actual_idle_samples']==16


@pytest.mark.parametrize('fault',['foreign_idle','retired_running','idle_failed','stale',
                                  'same_tick','speed','not_ready','old_action','missing_receipt'])
def test_unowned_stale_or_unsettled_samples_never_accrue_an_idle_window(fault):
    b=Backend()
    for tick in range(1,32):
        obs=b.observation(tick)
        if fault=='foreign_idle':b.current=39;b.states[39]='running';obs['native_task_id']=39
        elif fault=='retired_running':b.states[35]='running'
        elif fault=='idle_failed':b.states[38]='failed'
        elif fault=='stale':obs['observation_sim_time']-=1/30
        elif fault=='same_tick':obs['observation_sim_time']=0.;b.now=0.
        elif fault=='speed':obs['speed_mps']=.15
        elif fault=='not_ready':obs['ready']=False
        elif fault=='old_action':obs['action']='canonical_operator__left_low';obs['native_task_id']=35
        elif fault=='missing_receipt':b.record.pop('idle_request_native_task_id',None)
        assert not ready(b,'actor',obs,True)
    assert not b.record['actual_idle_times'] and not b.events


def test_duplicate_reads_cannot_add_samples_and_a_missing_frame_resets_the_window():
    b=Backend()
    for tick in range(1,10):
        obs=b.observation(tick)
        for _ in range(4):assert not ready(b,'actor',obs,True)
    assert len(b.record['actual_idle_times'])==9
    assert not ready(b,'actor',b.observation(11),True)
    assert b.record['actual_idle_times']==[11/30]


def test_absent_stop_record_is_readonly_and_needs_no_native_api():
    b=SimpleNamespace(instances={'actor':{}});before=copy.deepcopy(b.instances)
    assert ready(b,'actor',require_window=True)
    assert b.instances==before
