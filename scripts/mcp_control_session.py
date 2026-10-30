"""Exercise the actual stdio MCP server against the live Isaac bridge."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True)
parser.add_argument('--endpoint',default=os.environ.get('SIMPEOPLE_ENDPOINT','http://127.0.0.1:8768'));parser.add_argument('--camera-check',action='store_true');args=parser.parse_args()
root=Path(__file__).resolve().parents[1];directory=root/'runs'/args.run_id

async def main():
    calls=[]
    async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','simpeople.tools.mcp_server'],env={'SIMPEOPLE_ENDPOINT':args.endpoint})) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            listing=await session.list_tools()
            async def invoke(name,arguments):
                result=await session.call_tool(name,arguments)
                entry={'wall_time':time.time(),'name':name,'arguments':arguments,'result':result.model_dump(mode='json')}
                calls.append(entry)
                (directory/'agent_mcp_calls.json').write_text(json.dumps(calls,indent=2))
                if result.isError:raise RuntimeError(entry)
                return result.structuredContent or json.loads(result.content[0].text)
            await invoke('people_inspect_scene',{})
            await invoke('people_spawn',{'request_id':'mcp-spawn','actor_id':'mcp_actor','spawn_anchor':'entrance'})
            if args.camera_check:
                await invoke('people_record',{'request_id':'mcp-camera-follow','mode':'camera','view':'follow','actor_id':'mcp_actor'})
                inspection=await invoke('people_inspect_scene',{})
                assert inspection['recording']['focus_actor_id']=='mcp_actor'
            response=await invoke('people_signal_event',{'request_id':'mcp-event','kind':'robot_nearby','actor_ids':['mcp_actor'],'duration_s':.5})
            for _ in range(100):
                all_state=await invoke('people_get_state',{})
                event=next(x for x in all_state['events'] if x['event_id']==response['event_id'])
                if event['results'][0]['status']=='succeeded':break
                await asyncio.sleep(.15)
            assert event['results'][0]['status']=='succeeded'
            result=await invoke('people_move_to',{'request_id':'mcp-move','actor_id':'mcp_actor','target':'workbench_a'})
            tid=result['task_id']
            await asyncio.sleep(1.5)
            state=await invoke('people_get_state',{'task_id':tid})
            assert state['status']=='running'
            await invoke('people_cancel',{'request_id':'mcp-cancel','task_id':tid})
            for _ in range(100):
                state=await invoke('people_get_state',{'task_id':tid})
                if state['status']=='cancelled':break
                await asyncio.sleep(.15)
            assert state['status']=='cancelled'
            await invoke('people_despawn',{'request_id':'mcp-despawn','actor_id':'mcp_actor'})
            if args.camera_check:await invoke('people_record',{'request_id':'mcp-camera-overview','mode':'camera','view':'overview'})
            result={'passed':True,'tool_count':len(listing.tools),'tools':[t.name for t in listing.tools],
                    'actual_isaac_task_id':tid,'final_state':state['status'],'event_response_verified':True,'endpoint':args.endpoint,'camera_control_verified':args.camera_check}
            (directory/'agent_mcp_acceptance.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

asyncio.run(main())
