"""Actual installed MCP conversion, with an isolated in-process transport."""
import asyncio,importlib
import pytest
pytest.importorskip('mcp')
from test_engine import Backend,Journal
from simpeople.core.engine import Engine
from simpeople.tools import mcp_server

def test_structured_tool_error_keeps_code_phase_and_correlation(monkeypatch):
    e=Engine(Backend(),Journal())
    monkeypatch.setattr(mcp_server,'call',lambda method,params,endpoint:e.call(method,params))
    result=asyncio.run(mcp_server.mcp.call_tool('people_run_activity',{'request_id':'bad','command_id':'command','attempt_id':'attempt','actor_id':'missing','steps':[{'action':'wait','duration_s':1}]}))
    assert result.isError
    error=result.structuredContent['error']
    assert error['code']=='ACTOR_NOT_FOUND' and error['stage']=='validation'
    assert error['details']['command_id']=='command' and error['details']['attempt_id']=='attempt'
    assert e.controller_id is None

def test_reconnect_uses_stable_logical_client(monkeypatch):
    e=Engine(Backend(),Journal());monkeypatch.setenv('SIMPEOPLE_CONTROLLER_ID','reconnect-test')
    for i in range(2):
        server=importlib.reload(mcp_server)
        monkeypatch.setattr(server,'call',lambda method,params,endpoint:e.call(method,params))
        result=server.rpc('spawn',{'request_id':'same','actor_id':'a'})
        if i:assert result['idempotent_replay']
    assert len(e.actors)==1 and e.controller_id=='reconnect-test'

def test_mcp_explicit_old_session_cannot_write_after_runtime_restart(monkeypatch):
    before=Engine(Backend(),Journal());after=Engine(Backend(),Journal())
    monkeypatch.setattr(mcp_server,'call',lambda method,params,endpoint:after.call(method,params))
    result=asyncio.run(mcp_server.mcp.call_tool('people_spawn',{
        'request_id':'old_spawn','actor_id':'a','session_id':before.session_id}))
    assert result.isError and result.structuredContent['error']['code']=='SESSION_MISMATCH'
    assert after.controller_id is None and not after.actors


def test_actual_mcp_validation_keeps_the_capability_step_hint(monkeypatch):
    e=Engine(Backend(),Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    monkeypatch.setattr(mcp_server,'call',lambda method,params,endpoint:e.call(method,params))
    result=asyncio.run(mcp_server.mcp.call_tool('people_validate_activity',{'actor_id':'a','steps':[{'action':'walk','target':[1,2,0]}]}))
    assert result.isError
    error=result.structuredContent['error']
    assert error['code']=='ACTION_UNSUPPORTED'
    assert error['details']['step_fields_hint']=={'action':'move_to','gait':'walk'}
    assert not e.tasks
