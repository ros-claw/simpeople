"""Bounded local MotionBricks service. No Kit imports and no pose application."""
import argparse,json,os,signal,socketserver,sys,threading,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from simpeople.core.errors import SimPeopleError
from simpeople.motion.jobs import MotionJobs


class ArtifactBackend:
    def __init__(self,args):
        from backend import SomaBackend
        self.backend=SomaBackend(args.upstream,args.rig,args.device,args.cache_dir);self.delay=args.fault_before_publish_s
    def generate(self,spec,directory):
        import numpy as np
        from backend import sha256
        from simpeople.motion.contracts import digest
        directory.mkdir(exist_ok=False);result=self.backend.generate(spec['context']['local_poses'],spec['target']['local_poses'])
        raw=directory/'raw_decoded.npz';corrected=directory/'motion.npz';network=directory/'raw_network.npz'
        np.savez(raw,local_poses=result['raw_local_poses']);np.savez(corrected,local_poses=result['local_poses'],foot_contacts=result['foot_contacts'])
        np.savez(network,features=result['raw_network_features'],num_tokens=result['raw_num_tokens'])
        if self.delay:time.sleep(self.delay)
        artifact={'schema_version':'simpeople.motion-asset.v1','request_id':spec['request_id'],'spec_sha256':digest(spec),'rig_sha256':spec['rig_sha256'],'binding':spec.get('binding'),'sample_rate':30,'frames':len(result['local_poses']),
            'corrected':{'path':str(corrected),'sha256':sha256(corrected)},'raw_decoded':{'path':str(raw),'sha256':sha256(raw)},'raw_network':{'path':str(network),'sha256':sha256(network)},
            'model_provenance':self.backend.provenance,'generation_wall_s':result['wall_s'],'engine_stage_ms':result['engine_stage_ms'],'fault_before_publish_s':self.delay,
            'native_execution_verified':False,'retarget_verified':False}
        (directory/'artifact.json').write_text(json.dumps(artifact,indent=2)+'\n');return artifact
    def close(self):self.backend.close()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            data=self.rfile.readline(2_000_001)
            if not data or len(data)>2_000_000:raise SimPeopleError('MOTION_REQUEST_TOO_LARGE','IPC request exceeds limit')
            request=json.loads(data);jobs=self.server.jobs;op=request.get('op')
            fields={'ping':{'op'},'prepare':{'op','spec','expected_worker'},'status':{'op','job_id','expected_worker'},'cancel':{'op','job_id','expected_worker'}}
            if op not in fields or set(request)-fields[op]:raise SimPeopleError('MOTION_INVALID_REQUEST','unsupported worker operation or field')
            if op=='ping':result={'worker_instance_id':jobs.instance_id,'ready':jobs.ready,'startup_error':jobs.startup_error,'queue_capacity':jobs.capacity,'max_jobs':jobs.max_jobs,'provider':'motionbricks','execution_backend':'asset_production_only'}
            elif op=='prepare':result=jobs.prepare(request.get('spec'),request.get('expected_worker'))
            else:result=getattr(jobs,op)(request.get('job_id'),request.get('expected_worker'))
            response={'result':result}
        except SimPeopleError as error:response={'error':error.as_dict()}
        except Exception as error:response={'error':{'code':'MOTION_INVALID_REQUEST','message':str(error),'stage':'validation'}}
        self.wfile.write(json.dumps(response,allow_nan=False).encode()+b'\n')


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads=True
    request_queue_size=16


def main():
    p=argparse.ArgumentParser();p.add_argument('--endpoint',required=True);p.add_argument('--workspace',required=True);p.add_argument('--rig',required=True);p.add_argument('--upstream',required=True)
    p.add_argument('--device',default='cuda:3');p.add_argument('--cache-dir');p.add_argument('--capacity',type=int,default=8);p.add_argument('--max-jobs',type=int,default=256);p.add_argument('--fault-before-publish-s',type=float,default=0)
    args=p.parse_args()
    if not 0<=args.fault_before_publish_s<=5:p.error('fault delay must be 0..5 s')
    endpoint=Path(args.endpoint).resolve();endpoint.parent.mkdir(parents=True,exist_ok=True)
    server=Server(str(endpoint),Handler);os.chmod(endpoint,0o600)
    rig=json.loads(Path(args.rig).read_text());jobs=MotionJobs(lambda:ArtifactBackend(args),rig,args.workspace,args.capacity,args.max_jobs);server.jobs=jobs
    def shutdown(*_):threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGINT,shutdown);signal.signal(signal.SIGTERM,shutdown)
    print(json.dumps({'worker_instance_id':jobs.instance_id,'endpoint':str(endpoint)}),flush=True)
    try:server.serve_forever(poll_interval=.1)
    finally:
        jobs.close();server.server_close();endpoint.unlink(missing_ok=True)


if __name__=='__main__':main()
