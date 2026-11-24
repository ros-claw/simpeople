"""Real stdio MCP gestures and cancellation, with actual native task outcomes."""
import argparse,asyncio,json,math,os,sys,time
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]


def body(result):
    assert not result.isError,result
    return result.structuredContent if result.structuredContent is not None else json.loads(result.content[0].text)


async def main(args):
    folder=ROOT/'runs'/args.run_id;until=time.monotonic()+1200
    while not (folder/'host_ready.json').exists():
        if (folder/'failed.txt').exists() or time.monotonic()>until:raise RuntimeError('native gesture probe did not reach host phase')
        await asyncio.sleep(1)
    ready=json.loads((folder/'host_ready.json').read_text());rows=[]
    server=StdioServerParameters(command=sys.executable,args=['-m','simpeople.tools.mcp_server'],cwd=str(ROOT),
        env={**os.environ,'PYTHONPATH':str(folder/'source_snapshot/src'),'SIMPEOPLE_CONTROLLER_ID':'gesture-probe','SIMPEOPLE_ENDPOINT':ready['endpoint']})
    async with stdio_client(server) as (read,write):
        async with ClientSession(read,write) as session:
            await session.initialize()
            async def call(name,params):
                result=await session.call_tool(name,params)
                rows.append({'tool':name,'params':params,'result':result.model_dump(mode='json',exclude_none=True)})
                return result
            async def wait(tid,expected):
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    state=body(await call('people_get_state',{'task_id':tid}))
                    if state['status'] in {'succeeded','failed','cancelled'}:
                        assert state['status']==expected,state
                        return state
                    await asyncio.sleep(.1)
                raise RuntimeError('MCP gesture did not finish')
            actions=body(await call('people_list_actions',{'actor_id':'operator'}))
            capabilities=actions.get('actions',actions)
            assert all(capabilities[k]['status']=='verified' for k in ['head_look','reach_hand']),actions
            obs=body(await call('people_get_state',{'actor_id':'operator'}))['actors'][0]['observation']
            f=obs['facing_direction'];head=obs['joints_m']['Head'];target=[head[i]+f[i] for i in range(3)]
            head_task=body(await call('people_perform',{'request_id':'mcp_head','actor_id':'operator','action':'head_look','target':target,'duration_s':.6}))
            completed_head=await wait(head_task['task_id'],'succeeded')
            obs=body(await call('people_get_state',{'actor_id':'operator'}))['actors'][0]['observation']
            shoulder=obs['joints_m']['RightArm'];f=obs['facing_direction'];target=[shoulder[0]+f[0]*.3,shoulder[1]+f[1]*.3,obs['position_m'][2]+1.2]
            params={'request_id':'mcp_reach','actor_id':'operator','action':'reach_hand','hand':'right','target':target,'duration_s':.6}
            reach=body(await call('people_perform',params));replay=body(await call('people_perform',params))
            assert replay['idempotent_replay'] and replay['task_id']==reach['task_id']
            bad=await call('people_run_activity',{'request_id':'mcp_invalid','actor_id':'operator','steps':[{'action':'reach_hand','hand':'right','target':[100,100,1.2],'duration_s':.6}]})
            assert bad.isError and bad.structuredContent['error']['code']=='TARGET_UNREACHABLE',bad
            state=body(await call('people_get_state',{'actor_id':'operator'}))['actors'][0]
            assert state['task']['task_id']==reach['task_id']
            await call('people_cancel',{'request_id':'mcp_cancel','task_id':reach['task_id']})
            cancelled=await wait(reach['task_id'],'cancelled');assert cancelled['physical_stop_verified']
    (folder/'mcp_gesture_probe.json').write_text(json.dumps({'passed':True,'scope':'actual stdio MCP transport and native outcomes; no natural-language host benchmark','head_task':completed_head,'cancelled_task':cancelled,'calls':rows},indent=2)+'\n')
    print('MCP_GESTURE_PROBE_PASSED')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);asyncio.run(main(p.parse_args()))
