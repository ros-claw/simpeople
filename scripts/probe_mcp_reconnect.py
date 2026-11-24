"""Real stdio MCP subprocesses -> HTTP bridge -> actual native actor.

Run with .venv-controller/bin/python after the lifecycle measurement window.
This checks transport/tool behavior, not a language-model host acceptance test.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]

async def probe(args):
    out=ROOT/'runs'/args.run_id
    ready=json.loads((out/'ready.json').read_text())
    assert (out/'benchmark_done.json').exists(),'wait for the native measurement window to end'
    env={**os.environ,'PYTHONPATH':str(out/'source_snapshot/src'),
         'SIMPEOPLE_CONTROLLER_ID':'runtimebench','SIMPEOPLE_ENDPOINT':ready['endpoint']}
    server=StdioServerParameters(command=sys.executable,args=['-m','simpeople.tools.mcp_server'],cwd=str(ROOT),env=env)
    rows=[];first=None;code=1;scope=None

    async def call(session,name,params):
        start=time.monotonic();result=await session.call_tool(name,params)
        rows.append({'tool':name,'params':params,'round_trip_wall_s':time.monotonic()-start,
                     'result':result.model_dump(mode='json',exclude_none=True)})
        return result

    def body(result):
        assert not result.isError,result
        if result.structuredContent is not None:return result.structuredContent
        return json.loads(result.content[0].text)

    try:
        for connection in range(2):
            async with stdio_client(server) as (read,write):
                async with ClientSession(read,write) as session:
                    await session.initialize()
                    current=body(await call(session,'people_session',{'action':'info'}))
                    if scope is None:scope={k:current[k] for k in ['session_id','episode_id']}
                    spawn=body(await call(session,'people_spawn',{'request_id':'reconnect_spawn',
                        'actor_id':'mcp_witness','spawn_anchor':[-7,-3,0],
                        'command_id':'mcp_native_probe','attempt_id':'same_attempt',**scope}))
                    if connection==0:
                        first=spawn
                        assert not spawn.get('idempotent_replay')
                    else:
                        assert spawn.get('idempotent_replay') and spawn['actor_instance_id']==first['actor_instance_id']
                        invalid=await call(session,'people_run_activity',{'request_id':'invalid_actor','actor_id':'missing',
                            'steps':[{'action':'wait','duration_s':1}],'command_id':'mcp_native_probe','attempt_id':'bad_attempt'})
                        assert invalid.isError
                        error=invalid.structuredContent['error']
                        assert error['code']=='ACTOR_NOT_FOUND' and error['stage']=='validation'
                        assert error['details']['command_id']=='mcp_native_probe' and error['details']['attempt_id']=='bad_attempt'
                        # Spawn readiness is deliberately read from the running native actor.
                        for _ in range(200):
                            state=body(await call(session,'people_get_state',{'actor_id':'mcp_witness'}))
                            if state['actors'][0]['observation']['ready']:break
                            await asyncio.sleep(.1)
                        else:raise AssertionError('native actor did not become ready')
                        receipt=body(await call(session,'people_run_activity',{'request_id':'native_walk','actor_id':'mcp_witness',
                            'steps':[{'action':'move_to','target':[-7,0,0],'timeout_s':20}],
                            'command_id':'mcp_native_probe','attempt_id':'walk_attempt','if_busy':'reject'}))
                        task=None
                        for _ in range(600):
                            task=body(await call(session,'people_get_state',{'task_id':receipt['task_id']}))
                            if task['status'] in {'succeeded','failed','cancelled'}:break
                            await asyncio.sleep(.1)
                        assert task['status']=='succeeded',task
                        events=[];cursor=0
                        for _ in range(30):
                            page=body(await call(session,'people_crowd',{'operation':'events','after':cursor,'limit':100}))
                            events.extend(page['events']);cursor=page['next_cursor']
                            if not page['events']:break
                        assert any(e['kind']=='native_task_bound' and e.get('task_id')==receipt['task_id'] for e in events),events
                        actors=body(await call(session,'people_get_state',{}))['actors']
                        assert len([a for a in actors if a['actor_id']=='mcp_witness'])==1
        code=0
    finally:
        (out/'mcp_reconnect_probe.json').write_text(json.dumps({'passed':code==0,'connections':2,
            'scope':'actual MCP stdio reconnection and native movement, no Codex/Claude natural-language inference',
            'calls':rows},indent=2)+'\n')
        (out/'host_probe.done').write_text(str(code)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True)
    asyncio.run(probe(parser.parse_args()))
