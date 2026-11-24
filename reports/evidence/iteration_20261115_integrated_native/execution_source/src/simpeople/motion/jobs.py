"""Bounded asynchronous generation. Worker cancellation never means actor stop."""
import copy
from pathlib import Path
from queue import Queue,Full,Empty
import threading
import time
import uuid
from simpeople.core.errors import SimPeopleError
from .contracts import validate_spec,digest

TERMINAL={'succeeded','failed','cancelled'}


class MotionJobs:
    def __init__(self,backend_factory,rig,workspace,capacity=8,max_jobs=256):
        if not 1<=capacity<=128 or not capacity<=max_jobs<=4096:raise ValueError('invalid motion admission limits')
        self.instance_id=uuid.uuid4().hex;self.rig=copy.deepcopy(rig);self.workspace=Path(workspace);self.workspace.mkdir(parents=True,exist_ok=True)
        self.capacity=capacity;self.max_jobs=max_jobs;self.jobs={};self.requests={};self.lock=threading.RLock();self.queue=Queue(maxsize=capacity)
        self.ready=False;self.startup_error=None;self.closed=False;self.backend_factory=backend_factory
        self.thread=threading.Thread(target=self._run,name='motion-generation',daemon=True);self.thread.start()

    def fence(self,expected):
        if expected is not None and expected!=self.instance_id:raise SimPeopleError('MOTION_WORKER_RESTARTED','worker instance changed',stage='generation')

    def public(self,job):
        return copy.deepcopy({k:v for k,v in job.items() if k not in {'spec','digest'}})

    def prepare(self,spec,expected_worker=None):
        clean=validate_spec(spec,self.rig);key=clean['request_id'];revision=digest(clean)
        with self.lock:
            self.fence(expected_worker)
            if self.closed:raise SimPeopleError('MOTION_WORKER_CLOSED','worker is shutting down',stage='generation')
            if self.startup_error:raise SimPeopleError('MOTION_WORKER_UNAVAILABLE',self.startup_error,stage='generation')
            if key in self.requests:
                job=self.jobs[self.requests[key]]
                if job['digest']!=revision:raise SimPeopleError('MOTION_REQUEST_CONFLICT','request ID was used with different motion data',stage='validation')
                return {**self.public(job),'idempotent_replay':True}
            if len(self.jobs)>=self.max_jobs:raise SimPeopleError('MOTION_HISTORY_FULL','bounded worker history is full; archive before creating a new session',stage='admission')
            if sum(j['status'] not in TERMINAL for j in self.jobs.values())>=self.capacity:raise SimPeopleError('MOTION_QUEUE_FULL','generation admission limit reached',stage='admission')
            jid=uuid.uuid4().hex;job={'job_id':jid,'request_id':key,'worker_instance_id':self.instance_id,'status':'queued','spec':clean,'digest':revision,
                'binding':clean.get('binding'),'rig_sha256':self.rig['rig_sha256'],'submitted_wall_monotonic_s':time.monotonic(),'cancel_requested':False,'artifact':None,'error':None}
            # Cancelled queued entries retain their physical slot until drained.
            # Reject before publishing a job if that queue is temporarily full.
            try:self.queue.put_nowait(jid)
            except Full:raise SimPeopleError('MOTION_QUEUE_FULL','generation queue is awaiting cancellation drain',stage='admission') from None
            self.jobs[jid]=job;self.requests[key]=jid
            return self.public(job)

    def status(self,job_id,expected_worker=None):
        with self.lock:
            self.fence(expected_worker)
            if job_id not in self.jobs:raise SimPeopleError('MOTION_JOB_NOT_FOUND','unknown motion job',stage='validation')
            return self.public(self.jobs[job_id])

    def cancel(self,job_id,expected_worker=None):
        with self.lock:
            self.fence(expected_worker);job=self.jobs.get(job_id)
            if job is None:raise SimPeopleError('MOTION_JOB_NOT_FOUND','unknown motion job',stage='validation')
            if job['status'] not in TERMINAL:
                job['cancel_requested']=True
                job['status']='cancelled' if job['status']=='queued' else 'cancelling'
            return {**self.public(job),'actor_stop_verified':False}

    def _run(self):
        backend=None
        try:
            backend=self.backend_factory()
            with self.lock:self.ready=True
            while True:
                try:jid=self.queue.get(timeout=.2)
                except Empty:
                    if self.closed:break
                    continue
                if jid is None:break
                with self.lock:
                    job=self.jobs[jid]
                    if job['status']=='cancelled':continue
                    job.update(status='running',started_wall_monotonic_s=time.monotonic())
                try:
                    artifact=backend.generate(copy.deepcopy(job['spec']),self.workspace/jid)
                    if (artifact.get('request_id')!=job['request_id'] or artifact.get('spec_sha256')!=job['digest'] or
                        artifact.get('rig_sha256')!=job['rig_sha256'] or artifact.get('binding')!=job['binding']):
                        raise SimPeopleError('MOTION_RESULT_MISMATCH','worker result does not match its immutable request',stage='generation')
                    with self.lock:
                        if job['cancel_requested']:job['status']='cancelled'
                        else:job.update(status='succeeded',artifact=copy.deepcopy(artifact))
                except Exception as error:
                    with self.lock:
                        if job['cancel_requested']:job['status']='cancelled'
                        else:job.update(status='failed',error=error.as_dict() if isinstance(error,SimPeopleError) else {'code':'MOTION_GENERATION_FAILED','message':str(error),'stage':'generation'})
                with self.lock:job['finished_wall_monotonic_s']=time.monotonic()
        except Exception as error:
            with self.lock:
                self.startup_error=str(error)
                for job in self.jobs.values():
                    if job['status'] not in TERMINAL:job.update(status='failed',error={'code':'MOTION_WORKER_UNAVAILABLE','message':str(error),'stage':'generation'})
        finally:
            if backend:backend.close()

    def close(self):
        with self.lock:
            self.closed=True
            for job in self.jobs.values():
                if job['status'] not in TERMINAL:
                    job['cancel_requested']=True
                    if job['status']=='queued':job['status']='cancelled'
        # Queued cancelled jobs are drained by the generator. No model thread
        # writes to Kit; an interrupted generator cannot apply a native pose.
        try:self.queue.put(None,timeout=5)
        except Full:return
        self.thread.join(timeout=5)
