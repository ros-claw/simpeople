"""Use thin-package environments to verify ownership across real stdio reconnects.

This tests MCP transports, not either host's natural-language model acceptance.
It changes only a previously unowned session lease, never actor activities.
"""
import argparse,asyncio,hashlib,json,os,time,uuid
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--endpoint',default='http://127.0.0.1:8781');a=p.parse_args();d=ROOT/'runs'/a.run_id
async def main():
 calls=[];owner=None;epoch=None;trial=uuid.uuid4().hex
 async def connect(host,phase,fn):
  server=json.loads((ROOT/'plugins'/host/('mcp.json' if host=='codex' else '.mcp.json')).read_text())['mcpServers']['simpeople']
  params=StdioServerParameters(command=server['command'],args=server['args'],env={**os.environ,**server.get('env',{}),'SIMPEOPLE_ENDPOINT':a.endpoint})
  async with stdio_client(params) as (reader,writer):
   async with ClientSession(reader,writer) as session:
    await session.initialize();listing=await session.list_tools();assert len(listing.tools)==20
    async def call(arguments,error=False):
     r=await session.call_tool('people_session',arguments)
     data=r.structuredContent or json.loads(r.content[0].text) if not r.isError else [getattr(c,'text','') for c in r.content]
     calls.append({'phase':phase,'host':host,'arguments':arguments,'is_error':bool(r.isError),'result':data})
     assert bool(r.isError)==error
     return data
    return await fn(call)
 async def first(call):
  nonlocal owner,epoch
  before=await call({'action':'info'});assert before['controller_id'] is None,'probe requires an unowned session; never take over another client'
  result=await call({'action':'acquire','request_id':trial+'-package-reconnect-first'})
  owner=result['controller_id'];epoch=result['controller_epoch'];assert owner=='simpeople-codex'
 async def reader(call):
  info=await call({'action':'info'});assert info['controller_id']==owner
  error=await call({'action':'acquire','request_id':trial+'-package-reconnect-other-host'},True);assert 'CONTROLLER_BUSY' in str(error)
 async def reconnected(call):
  info=await call({'action':'info'});assert info['controller_id']==owner and info['controller_epoch']==epoch
  result=await call({'action':'acquire','request_id':trial+'-package-reconnect-second'});assert result['controller_epoch']==epoch
  result=await call({'action':'release','request_id':trial+'-package-reconnect-release','expected_epoch':epoch});assert result['controller_id'] is None
 try:
  await connect('codex','initial',first);await connect('claude','reader',reader);await connect('codex','reconnect',reconnected)
 except Exception as error:
  from simpeople.tools.client import call as rpc
  if owner is not None:
   current=rpc('people.session_info',{},a.endpoint)
   if current['controller_id']==owner and current['controller_epoch']==epoch:
    rpc('people.control_session',{'request_id':trial+'-failed-probe-release','action':'release','controller_id':owner,'expected_epoch':epoch},a.endpoint)
  (d/'mcp_ownership_acceptance.json').write_text(json.dumps({'passed':False,'error':str(error),'calls':calls},indent=2))
  raise
 result={'passed':True,'scope':'real stdio clients configured by the thin plugin manifests; no natural-language host claim','actors_mutated':False,'plugin_config_sha256':{host:hashlib.sha256((ROOT/'plugins'/host/('mcp.json' if host=='codex' else '.mcp.json')).read_bytes()).hexdigest() for host in ['codex','claude']},'calls':calls}
 (d/'mcp_ownership_acceptance.json').write_text(json.dumps(result,indent=2));print(json.dumps({'passed':True,'sessions':3,'actors_mutated':False}))
asyncio.run(main())
