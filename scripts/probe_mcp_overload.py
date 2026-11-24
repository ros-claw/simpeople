"""Read a live overload run over real stdio MCP; reject an unowned write."""
import argparse,asyncio,json,os,sys,time
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]

def body(result):
    """FastMCP success dictionaries may be JSON text; errors stay structured."""
    assert not result.isError,result
    return result.structuredContent if result.structuredContent is not None else json.loads(result.content[0].text)

async def main(args):
    folder=ROOT/'runs'/args.run_id;until=time.monotonic()+1800
    while not (folder/'ready.json').exists():
        if (folder/'failed.txt').exists() or time.monotonic()>until:raise RuntimeError('native overload run did not become ready')
        await asyncio.sleep(1)
    ready=json.loads((folder/'ready.json').read_text());await asyncio.sleep(2)
    server=StdioServerParameters(command=sys.executable,args=['-m','simpeople.tools.mcp_server'],cwd=str(ROOT),
        env={**os.environ,'PYTHONPATH':str(folder/'source_snapshot/src'),'SIMPEOPLE_CONTROLLER_ID':'t2-readonly-probe','SIMPEOPLE_ENDPOINT':ready['endpoint']})
    rows=[]
    async with stdio_client(server) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            async def call(name,params):
                start=time.monotonic();result=await session.call_tool(name,params)
                rows.append({'tool':name,'round_trip_wall_s':time.monotonic()-start,'result':result.model_dump(mode='json',exclude_none=True)})
                return result
            info=body(await call('people_session',{'action':'info'}))
            crowd=await call('people_crowd',{'operation':'state','limit':100,'details':True})
            assert not crowd.isError
            failed=[a for a in body(crowd)['actors'] if (a.get('error') or {}).get('code')=='ADMISSION_FULL']
            assert len(failed)==4 and all(a['error']['stage']=='admission' for a in failed)
            scene=await call('people_inspect_scene',{})
            group=body(scene)['queues']['queue_0']
            assert len(group['tickets'])<=6 and group['outside_capacity']==2
            rejected=await call('people_run_activity',{'request_id':'must_not_take_control','actor_id':'q_00','steps':[{'action':'wait','duration_s':1}],
                'session_id':info['session_id'],'episode_id':info['episode_id'],'command_id':'t2_mcp_read_probe'})
            assert rejected.isError and rejected.structuredContent['error']['code']=='CONTROLLER_BUSY'
            after=body(await call('people_session',{'action':'info'}))
            assert (after['controller_id'],after['controller_epoch'])==(info['controller_id'],info['controller_epoch'])
    (folder/'mcp_overload_probe.json').write_text(json.dumps({'passed':True,'scope':'real MCP transport under overload; no LLM inference, no accepted writes','calls':rows},indent=2)+'\n')
    print('MCP_OVERLOAD_PROBE_PASSED')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);asyncio.run(main(parser.parse_args()))
