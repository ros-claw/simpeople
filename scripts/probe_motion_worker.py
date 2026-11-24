"""Actual official-model IPC, overload, cancellation, late discard and restart."""
import argparse,asyncio,hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simpeople.motion.providers.motionbricks import MotionBricksProvider
from simpeople.core.errors import SimPeopleError
from simpeople.motion.rig import validate_poses
from simpeople.motion.validation import validate_artifact
from jsonschema import Draft202012Validator
import numpy as np

p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--python',required=True);p.add_argument('--upstream',required=True);p.add_argument('--fixtures',required=True);p.add_argument('--model-cases',required=True);p.add_argument('--mcp',action='store_true');args=p.parse_args()
out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir()
for name in ['src','workers','schemas']:shutil.copytree(ROOT/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copy2(__file__,snap/Path(__file__).name)
(out/'source_manifest.json').write_text(json.dumps({str(f.relative_to(snap)):hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(snap.rglob('*')) if f.is_file()},indent=2)+'\n')
rig=json.loads(Path(args.fixtures,'rig.json').read_text());case=Path(args.model_cases)/'case_00'
with np.load(case/'context.npz',allow_pickle=False) as a:context=a['local_poses'].tolist()
with np.load(case/'target.npz',allow_pickle=False) as a:target=a['local_poses'].tolist()
provider=MotionBricksProvider(out/'worker.sock');process=None;logs=[];records=[]


def start(number):
    global process
    log=(out/f'worker_{number}.log').open('w');logs.append(log)
    child=subprocess.Popen([args.python,str(snap/'workers/motionbricks/worker.py'),'--endpoint',str(out/'worker.sock'),'--workspace',str(out/f'artifacts_{number}'),
        '--rig',str(Path(args.fixtures,'rig.json').resolve()),'--upstream',str(Path(args.upstream).resolve()),'--device','cuda:3','--cache-dir',str(Path(args.upstream,'.trt-cache').resolve()),'--capacity','2','--max-jobs','16','--fault-before-publish-s','.5'],stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
    process=child
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        if child.poll() is not None:raise RuntimeError('worker exited during startup')
        try:
            info=provider.ping()
            if info['startup_error']:raise RuntimeError(info['startup_error'])
            if info['ready']:return child,info
        except SimPeopleError:pass
        time.sleep(.1)
    raise RuntimeError('worker cold startup timeout')


def spec(name):return {'schema_version':'simpeople.motion-spec.v1','request_id':name,'rig_sha256':rig['rig_sha256'],
    'context':{'source':'authored_fixture','sample_times_s':[.9,.9+1/30,.9+2/30,1.0],'local_poses':context},'target':{'local_poses':target}}


def expect_error(code,action):
    try:action()
    except SimPeopleError as error:
        assert error.code==code,error.as_dict();records.append({'expected_error':code,'actual_error':error.as_dict()})
    else:raise AssertionError('expected '+code)


def wait(jid,worker,statuses):
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        row=provider.status(jid,worker)
        if row['status'] in statuses:return row
        if row['status']=='failed':raise RuntimeError(row)
        time.sleep(.01)
    raise RuntimeError('worker did not reach '+str(statuses))


def verify_artifact(row):
    artifact=row['artifact'];assert not artifact['native_execution_verified'] and not artifact['retarget_verified']
    Draft202012Validator(json.loads((snap/'schemas/motion-asset.schema.json').read_text())).validate(artifact)
    report=validate_artifact(artifact,rig,out)
    (out/(row['request_id']+'_validation.json')).write_text(json.dumps(report,indent=2)+'\n')
    for field in ['corrected','raw_decoded','raw_network']:
        ref=artifact[field];assert hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest()==ref['sha256']
    with np.load(artifact['corrected']['path'],allow_pickle=False) as values:validate_poses(values['local_poses'],len(rig['joint_names']))
    return artifact


async def mcp_probe(worker):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    calls=[]
    env={**os.environ,'PYTHONPATH':str(snap/'src'),'SIMPEOPLE_MOTION_ENDPOINT':str(out/'worker.sock'),'SIMPEOPLE_CONTROLLER_ID':'motion-mcp-probe'}
    async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','simpeople.tools.mcp_server'],env=env)) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize();available=await session.list_tools();assert 'people_motion' in {t.name for t in available.tools}
            async def invoke(params):
                reply=await session.call_tool('people_motion',params);calls.append({'params':params,'reply':reply.model_dump(mode='json')})
                assert not reply.isError,reply
                return reply.structuredContent or json.loads(reply.content[0].text)
            request={'op':'prepare','spec':spec('mcp_generated'),'expected_worker':worker}
            receipt=await invoke(request);again=await invoke(request)
            assert receipt['job_id']==again['job_id'] and again['idempotent_replay']
            for _ in range(300):
                state=await invoke({'op':'status','job_id':receipt['job_id'],'expected_worker':worker})
                if state['status'] in {'succeeded','failed','cancelled'}:break
                await asyncio.sleep(.01)
            assert state['status']=='succeeded';verify_artifact(state)
            pending=await invoke({'op':'prepare','spec':spec('mcp_cancel'),'expected_worker':worker})
            cancelled=await invoke({'op':'cancel','job_id':pending['job_id'],'expected_worker':worker});assert cancelled['actor_stop_verified'] is False
            for _ in range(300):
                state=await invoke({'op':'status','job_id':pending['job_id'],'expected_worker':worker})
                if state['status']=='cancelled':break
                await asyncio.sleep(.01)
            assert state['status']=='cancelled' and state['artifact'] is None
    (out/'mcp_motion_acceptance.json').write_text(json.dumps({'passed':True,'transport':'actual MCP stdio -> private Unix worker -> official FP32/N=1 engine','calls':calls,'limits':'Tool integration, not natural-language Codex/Claude host acceptance; no native actor execution.'},indent=2)+'\n')


try:
    request=spec('one');Draft202012Validator(json.loads((snap/'schemas/motion-spec.schema.json').read_text())).validate(request)
    (out/'submitted_spec.json').write_text(json.dumps(request,indent=2)+'\n')
    process,first=start(1);worker=first['worker_instance_id'];a=provider.prepare(spec('one'),worker);again=provider.prepare(spec('one'),worker)
    assert again['idempotent_replay'] and again['job_id']==a['job_id']
    changed=spec('one');changed['target']={'local_poses':json.loads(json.dumps(target))};changed['target']['local_poses'][0][0][0]+=.01
    expect_error('MOTION_REQUEST_CONFLICT',lambda:provider.prepare(changed,worker))
    wait(a['job_id'],worker,{'running'});b=provider.prepare(spec('two'),worker)
    expect_error('MOTION_QUEUE_FULL',lambda:provider.prepare(spec('three'),worker))
    cancellation=provider.cancel(a['job_id'],worker);assert not cancellation['actor_stop_verified']
    a_end=wait(a['job_id'],worker,{'cancelled'});b_end=wait(b['job_id'],worker,{'succeeded'})
    assert a_end['artifact'] is None;artifact=verify_artifact(b_end)
    expect_error('MOTION_WORKER_RESTARTED',lambda:provider.status(b['job_id'],'stale-worker'))
    invalid=spec('invalid');invalid['target']['local_poses']=[[[0,0,0,0,0,0,0]]]*len(rig['joint_names'])
    expect_error('MOTION_INVALID_REQUEST',lambda:provider.prepare(invalid,worker))
    process.terminate();process.wait(timeout=20);process=None
    expect_error('MOTION_WORKER_UNAVAILABLE',provider.ping)
    process,second=start(2);assert second['worker_instance_id']!=worker
    expect_error('MOTION_WORKER_RESTARTED',lambda:provider.status(b['job_id'],worker))
    fresh=provider.prepare(spec('after_restart'),second['worker_instance_id']);fresh_end=wait(fresh['job_id'],second['worker_instance_id'],{'succeeded'});verify_artifact(fresh_end)
    if args.mcp:asyncio.run(mcp_probe(second['worker_instance_id']))
    result={'passed':True,'provider':'actual MotionBricks FP32/N=1','first_worker':first,'second_worker':second,'cancelled_job':a_end,'completed_job':b_end,'after_restart':fresh_end,
        'expected_rejections':records,'fault_before_publish_s':.5,'limits':'Fault-injected publication delay; not a latency benchmark. Worker cancellation is not a native actor stop. No artifact was applied to a character.'}
    (out/'worker_acceptance.json').write_text(json.dumps(result,indent=2)+'\n');print('MOTION_WORKER_IPC_PASSED')
finally:
    if process and process.poll() is None:process.terminate();process.wait(timeout=20)
    for log in logs:log.close()
