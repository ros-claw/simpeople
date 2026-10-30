"""Thin stdio MCP wrapper. All operations use the same live bridge as CLI."""
import os
import uuid
import hashlib
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from .client import call
from simpeople.core.engine import READ_METHODS
from simpeople.core.errors import SimPeopleError

CLIENT_ID=os.environ.get('SIMPEOPLE_CONTROLLER_ID','mcp-'+uuid.uuid4().hex[:20])

mcp=FastMCP('ROSClaw SimPeople',instructions='Inspect scene and verified capabilities before submitting activities. accepted is not completed. Poll tasks; cancellation must reach cancelled.')
def rpc(method,params=None):
    params=dict(params or {})
    if method not in READ_METHODS:
        params['controller_id']=CLIENT_ID
        if params.get('request_id'):
            params['request_id']='mcp-'+hashlib.sha256((CLIENT_ID+':'+params['request_id']).encode()).hexdigest()
    try:return call('people.'+method,params,os.environ.get('SIMPEOPLE_ENDPOINT','http://127.0.0.1:8768'))
    except SimPeopleError as error:
        # FastMCP exposes exceptions as tool errors. Preserve the actionable
        # code instead of losing it in the default exception message.
        raise RuntimeError(error.code+': '+str(error)) from None

@mcp.tool(name='people_inspect_scene',annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
def inspect_scene()->dict:
    """Read current scene, actors, semantic places, units, resources and NavMesh."""
    return rpc('inspect_scene')

@mcp.tool(name='people_list_assets',annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
def list_assets()->dict:
    """List registered human assets and their verification state."""
    return rpc('list_assets')

@mcp.tool(name='people_list_actions',annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
def list_actions(actor_id:str)->dict:
    """Read actual actor action capabilities; discovered is not verified."""
    return rpc('list_actions',{'actor_id':actor_id})

@mcp.tool(name='people_spawn')
def spawn(request_id:str,actor_id:str,asset_id:str='default',spawn_anchor:str|list[float]='entrance')->dict:
    """Create a human with independent native animation state. Retry with same request_id."""
    return rpc('spawn',locals())

@mcp.tool(name='people_despawn')
def despawn(request_id:str,actor_id:str)->dict:
    """Cancel tasks and remove only this managed actor."""
    return rpc('despawn',locals())

@mcp.tool(name='people_move_to')
def move_to(request_id:str,actor_id:str,target:str|list[float],gait:str='walk',timeout_s:float=120,via:list[str|list[float]]|None=None)->dict:
    """Move to semantic location or Z-up metre coordinates. Returns a task to poll."""
    return rpc('move_to',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_perform')
def perform(request_id:str,actor_id:str,action:str,target:str|None=None,duration_s:float|None=None)->dict:
    """Perform wait, look_at, sit, leave_seat or follow. Consult list_actions first."""
    return rpc('perform',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_validate_activity',annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
def validate_activity(actor_id:str,steps:list[dict])->dict:
    """Validate all steps and capabilities without replacing the current activity."""
    return rpc('validate_activity',locals())

@mcp.tool(name='people_run_activity')
def run_activity(request_id:str,actor_id:str,steps:list[dict])->dict:
    """Submit a sequential activity; replaces the actor's old activity after full validation."""
    return rpc('run_activity',locals())

@mcp.tool(name='people_get_state',annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
def get_state(actor_id:str|None=None,task_id:str|None=None)->dict:
    """Read actual runtime position, joints, speed, task state and failure cause."""
    return rpc('get_state' if actor_id or task_id else 'crowd_state',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_session')
def session(action:str='info',request_id:str|None=None,expected_epoch:int|None=None)->dict:
    """Read info/preflight. Acquire/release/takeover write ownership explicitly; takeover and release require current expected_epoch. Activities survive disconnect and takeover. This is local coordination, not authentication."""
    if action in {'info','preflight'}:return rpc('session_info' if action=='info' else 'preflight')
    return rpc('control_session',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_crowd')
def crowd(operation:str='state',request_id:str|None=None,selector:dict|None=None,
          items:list[dict]|None=None,steps:list[dict]|None=None,offset:int=0,limit:int=20,
          details:bool=False,after:int=0)->dict:
    """state: summary and paginated actors; events: incremental cursor. run_activity/cancel/spawn: batch with per-item outcomes, at most 100. Selector supports actor_ids, role, group, region_m=[xmin,ymin,xmax,ymax]. Batch accepts items or selector+steps. Poll task IDs for completion."""
    if operation=='state':return rpc('crowd_state',{'selector':selector,'offset':offset,'limit':limit,'details':details})
    if operation=='events':return rpc('read_events',{'after':after,'limit':limit})
    return rpc('batch',{k:v for k,v in {'request_id':request_id,'operation':operation,'selector':selector,'items':items,'steps':steps}.items() if v is not None})

@mcp.tool(name='people_populate')
def populate(request_id:str,count:int=10,seed:int=42,asset_pool:list[str]|None=None,prefix:str='person')->dict:
    """Create independent humans with seeded local role programs in an industrial scene. Returns per-actor results."""
    return rpc('populate',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_move_prop')
def move_prop(request_id:str,prop_id:str,position_m:list[float])->dict:
    """Move a registered kinematic obstacle for dynamic-blockage tests."""
    return rpc('move_prop',locals())

@mcp.tool(name='people_cancel')
def cancel(request_id:str,task_id:str|None=None,actor_id:str|None=None)->dict:
    """Request a native stop. Poll until cancelled; a completed task keeps its terminal state."""
    return rpc('cancel',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_signal_event')
def signal_event(request_id:str,kind:str,actor_ids:list[str],source_id:str='agent',target:str|list[float]|None=None,duration_s:float=3)->dict:
    """Supply robot_nearby, passage_blocked, call_person or region_closed events. Ordinary events defer across seat/queue interactions; inspect get_state for outcomes."""
    return rpc('signal_event',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_reset')
def reset(request_id:str,episode_id:str|None=None)->dict:
    """Delete managed actors, cancel tasks and invalidate old episode resources."""
    return rpc('reset',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_pause')
def pause(request_id:str)->dict:
    """Pause simulation and activity clocks while keeping bridge responsive."""
    return rpc('pause',locals())

@mcp.tool(name='people_resume')
def resume(request_id:str)->dict:
    """Resume simulation and activity clocks."""
    return rpc('resume',locals())

@mcp.tool(name='people_record')
def record(request_id:str,mode:str,view:str|None=None,actor_id:str|None=None)->dict:
    """Start/stop RGB recording, or mode=camera with view=overview/follow/seat_side/gait_side and actor_id. Output stays in the current run directory. Recording may be disabled by the session capture profile."""
    return rpc('record',{k:v for k,v in locals().items() if v is not None})

def main():mcp.run(transport='stdio')
if __name__=='__main__':main()
