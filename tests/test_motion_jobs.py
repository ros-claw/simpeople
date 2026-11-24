import copy
import threading
import time
import pytest
from simpeople.core.errors import SimPeopleError
from simpeople.motion.contracts import validate_spec,digest,binding_matches
from simpeople.motion.jobs import MotionJobs

RIG={'rig_sha256':'a'*64,'joint_names':['Hips']}


def spec(name='one'):
    return {'schema_version':'simpeople.motion-spec.v1','request_id':name,'rig_sha256':RIG['rig_sha256'],
        'context':{'source':'authored_fixture','sample_times_s':[0,1/30,2/30,3/30],'local_poses':[[[0,0,1,0,0,0,1]]]*4},'target':{'local_poses':[[[0,0,1,0,0,0,1]]]}}


def until(test):
    deadline=time.monotonic()+3
    while not test():
        if time.monotonic()>deadline:raise AssertionError('bounded worker did not reach expected state')
        time.sleep(.005)


class Backend:
    def __init__(self):self.entered=threading.Event();self.release=threading.Event();self.calls=[]
    def generate(self,data,directory):
        self.calls.append(data['request_id']);self.entered.set();assert self.release.wait(2)
        return {'asset':'generated','request_id':data['request_id'],'spec_sha256':digest(data),'rig_sha256':data['rig_sha256'],'binding':data.get('binding'),'native_execution_verified':False}
    def close(self):pass


def test_duplicate_prepare_is_idempotent_and_changed_body_is_rejected(tmp_path):
    b=Backend();jobs=MotionJobs(lambda:b,RIG,tmp_path,capacity=2)
    try:
        first=jobs.prepare(spec());again=jobs.prepare(spec())
        assert first['job_id']==again['job_id'] and again['idempotent_replay']
        changed=spec();changed['target']['local_poses'][0][0][0]=.1
        with pytest.raises(SimPeopleError) as error:jobs.prepare(changed)
        assert error.value.code=='MOTION_REQUEST_CONFLICT'
        b.release.set();until(lambda:jobs.status(first['job_id'])['status']=='succeeded');assert b.calls==['one']
    finally:b.release.set();jobs.close()


def test_cancel_running_discards_late_result_and_does_not_cancel_other_slot(tmp_path):
    b=Backend();jobs=MotionJobs(lambda:b,RIG,tmp_path,capacity=2)
    try:
        first=jobs.prepare(spec('one'));assert b.entered.wait(1);second=jobs.prepare(spec('two'))
        receipt=jobs.cancel(first['job_id'],jobs.instance_id);assert receipt['actor_stop_verified'] is False
        b.release.set();until(lambda:jobs.status(second['job_id'])['status']=='succeeded')
        state=jobs.status(first['job_id']);assert state['status']=='cancelled' and state['artifact'] is None
        assert jobs.status(second['job_id'])['artifact']['native_execution_verified'] is False
    finally:b.release.set();jobs.close()


def test_queue_and_history_are_bounded_and_queued_cancel_never_generates(tmp_path):
    b=Backend();jobs=MotionJobs(lambda:b,RIG,tmp_path,capacity=2,max_jobs=2)
    try:
        first=jobs.prepare(spec('one'));assert b.entered.wait(1);second=jobs.prepare(spec('two'))
        with pytest.raises(SimPeopleError):jobs.prepare(spec('three'))
        jobs.cancel(second['job_id']);b.release.set();until(lambda:jobs.status(first['job_id'])['status']=='succeeded')
        assert b.calls==['one'] and jobs.status(second['job_id'])['status']=='cancelled'
        with pytest.raises(SimPeopleError) as error:jobs.prepare(spec('three'))
        assert error.value.code=='MOTION_HISTORY_FULL'
    finally:b.release.set();jobs.close()


def test_worker_restart_and_stale_context_fences_are_not_accepted(tmp_path):
    b=Backend();jobs=MotionJobs(lambda:b,RIG,tmp_path)
    try:
        with pytest.raises(SimPeopleError) as error:jobs.prepare(spec(),expected_worker='old-process')
        assert error.value.code=='MOTION_WORKER_RESTARTED' and not jobs.jobs
        assert not binding_matches({}, {})
        binding={'session_id':'s','episode_id':'e','actor_id':'a','actor_instance_id':'body1','control_epoch':1,'task_id':'t','context_revision':'c'}
        assert binding_matches(binding,{**binding,'controller_epoch':99})
        assert not binding_matches(binding,{**binding,'actor_instance_id':'body2'})
    finally:b.release.set();jobs.close()


@pytest.mark.parametrize('bad',['prediction','bad_times','nan','zero_quaternion','missing_fence'])
def test_invalid_context_is_rejected_before_generation(bad):
    data=copy.deepcopy(spec())
    if bad=='prediction':data['context']['source']='predicted_future'
    if bad=='bad_times':data['context']['sample_times_s'][2]+=.01
    if bad=='nan':data['context']['local_poses'][0][0][0]=float('nan')
    if bad=='zero_quaternion':data['target']['local_poses'][0][0][3:]=[0,0,0,0]
    if bad=='missing_fence':data['context']['source']='executed_history'
    with pytest.raises(SimPeopleError):validate_spec(data,RIG)


def test_executed_history_fence_digest_must_match_the_samples():
    data=spec();data['context']['source']='executed_history'
    data['binding']={'session_id':'s','episode_id':'e','actor_id':'a','actor_instance_id':'b','control_epoch':2,'task_id':'t','context_revision':digest(data['context'])}
    validate_spec(data,RIG)
    data['context']['local_poses'][0][0][0]=.01
    with pytest.raises(SimPeopleError):validate_spec(data,RIG)


def test_active_cancellation_does_not_free_admission_before_model_result_returns(tmp_path):
    b=Backend();jobs=MotionJobs(lambda:b,RIG,tmp_path,capacity=1,max_jobs=2)
    try:
        first=jobs.prepare(spec());assert b.entered.wait(1);jobs.cancel(first['job_id'])
        with pytest.raises(SimPeopleError) as error:jobs.prepare(spec('two'))
        assert error.value.code=='MOTION_QUEUE_FULL'
        b.release.set();until(lambda:jobs.status(first['job_id'])['status']=='cancelled')
        next_job=jobs.prepare(spec('two'));until(lambda:jobs.status(next_job['job_id'])['status']=='succeeded')
    finally:b.release.set();jobs.close()


def test_mismatched_result_cannot_be_attached_to_another_request(tmp_path):
    class Wrong(Backend):
        def generate(self,data,directory):
            result=super().generate(data,directory);result['request_id']='another';return result
    b=Wrong();jobs=MotionJobs(lambda:b,RIG,tmp_path)
    try:
        row=jobs.prepare(spec());b.release.set();until(lambda:jobs.status(row['job_id'])['status']=='failed')
        failed=jobs.status(row['job_id']);assert failed['error']['code']=='MOTION_RESULT_MISMATCH' and failed['artifact'] is None
    finally:b.release.set();jobs.close()


def test_cancelled_pending_slots_cannot_create_orphan_admissions(tmp_path):
    gate=threading.Event();b=Backend()
    def start():
        assert gate.wait(2)
        return b
    jobs=MotionJobs(start,RIG,tmp_path,capacity=1)
    try:
        first=jobs.prepare(spec('pending'));jobs.cancel(first['job_id'])
        with pytest.raises(SimPeopleError) as error:jobs.prepare(spec('replacement'))
        assert error.value.code=='MOTION_QUEUE_FULL'
        assert len(jobs.jobs)==1 and 'replacement' not in jobs.requests
        gate.set();b.release.set();until(lambda:jobs.ready and jobs.queue.empty())
        row=jobs.prepare(spec('replacement'));until(lambda:jobs.status(row['job_id'])['status']=='succeeded')
        assert b.calls==['replacement']
    finally:gate.set();b.release.set();jobs.close()
