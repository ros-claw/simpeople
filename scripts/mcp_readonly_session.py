"""Verify a clean controller environment against a live Kit bridge without writes."""
import argparse
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

p=argparse.ArgumentParser();p.add_argument('--endpoint',default='http://127.0.0.1:8770')
p.add_argument('--output',default='reports/clean_controller/mcp_readonly_acceptance.json');a=p.parse_args()

async def main():
    params=StdioServerParameters(command=sys.executable,args=['-m','simpeople.tools.mcp_server'],
                                env={**os.environ,'SIMPEOPLE_ENDPOINT':a.endpoint})
    calls=[]
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize();listing=await session.list_tools()
            for name in ['people_inspect_scene','people_list_assets','people_get_state']:
                response=await session.call_tool(name,{})
                if response.isError:raise RuntimeError(str(response.content))
                value=response.structuredContent or json.loads(response.content[0].text)
                calls.append({'tool':name,'result':value})
    state=calls[-1]['result']
    result={'passed':len(listing.tools)==20 and bool(state['actors']),
            'python':sys.version,'executable':sys.executable,'endpoint':a.endpoint,
            'tool_count':len(listing.tools),'actual_actors':state.get('total',len(state['actors'])),'returned_actor_page':len(state['actors']),
            'episode_id':state['episode_id'],'sim_time':state['sim_time'],
            'writes_performed':False,
            'versions':{name:importlib.metadata.version(name) for name in ['mcp','pytest','jsonschema','usd-core','rosclaw-simpeople']},
            'calls':calls}
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='calls'},indent=2))
    if not result['passed']:raise SystemExit(1)

asyncio.run(main())
