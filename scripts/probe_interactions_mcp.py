"""Read native registry tools through real stdio MCP without acquiring control."""
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
        if (folder/'failed.txt').exists() or time.monotonic()>until:raise RuntimeError('native registry probe did not become ready')
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
            target_id=ready.get('interaction_target','work_00')
            listing=body(await call('people_list_interactions',{'target':target_id}))
            target=listing['interactions'][0]
            assert target['kind']=='workstation' and not listing['reservation_acquired']
            response=await call('people_validate_interaction',{'actor_id':'operator','action':'wait','target':target_id,'revision':target['geometry_revision']})
            if response.isError:
                assert response.structuredContent['error']['code']=='TARGET_STALE'
                target=body(await call('people_list_interactions',{'target':target_id}))['interactions'][0]
                response=await call('people_validate_interaction',{'actor_id':'operator','action':'wait','target':target_id,'revision':target['geometry_revision']})
            validation=body(response)
            assert validation['advisory'] and not validation['reservation_acquired'] and validation['actor_id']=='operator'
            after=body(await call('people_session',{'action':'info'}))
            assert (after['controller_id'],after['controller_epoch'])==(info['controller_id'],info['controller_epoch'])
    (folder/'mcp_registry_probe.json').write_text(json.dumps({'passed':True,'scope':'real MCP registry/preflight reads; no LLM inference and no session ownership change','calls':rows},indent=2)+'\n')
    print('MCP_REGISTRY_PROBE_PASSED')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);asyncio.run(main(parser.parse_args()))
