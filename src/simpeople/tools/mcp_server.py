"""Thin stdio MCP wrapper. All operations use the same live bridge as CLI."""
import os
import uuid
import hashlib
import json
from typing import Literal
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations,CallToolResult,TextContent
from .client import call
from simpeople.core.engine import READ_METHODS
from simpeople.core.errors import SimPeopleError

CLIENT_ID=os.environ.get('SIMPEOPLE_CONTROLLER_ID','mcp-'+uuid.uuid4().hex[:20])

mcp=FastMCP('ROSClaw SimPeople',instructions='Inspect scene, session scope and verified capabilities before submitting activities. Supply the observed session_id and episode_id on writes to reject stale plans. accepted is not completed. Use if_busy=reject to preserve an existing activity. Poll explicit cancellation to cancelled with physical_stop_verified=true; superseded only invalidates the old plan.')
def rpc(method,params=None):
    params={k:v for k,v in (params or {}).items() if v is not None}
    if method not in READ_METHODS:
        params['controller_id']=CLIENT_ID
        if params.get('request_id'):
            params['request_id']='mcp-'+hashlib.sha256((CLIENT_ID+':'+params['request_id']).encode()).hexdigest()
    try:return call('people.'+method,params,os.environ.get('SIMPEOPLE_ENDPOINT','http://127.0.0.1:8768'))
    except SimPeopleError as error:
        body={'error':error.as_dict()}
        return CallToolResult(isError=True,structuredContent=body,
                              content=[TextContent(type='text',text=json.dumps(body,ensure_ascii=False))])

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
    """Read actual actor capabilities and activity_contract. walk/run are capability/gait labels: activity steps use action=move_to with gait=walk/run. Discovered is not verified; obey the exact actor domain."""
    return rpc('list_actions',{'actor_id':actor_id})

@mcp.tool(name='people_list_interactions',annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
def list_interactions(kind:str|None=None,target:str|None=None,revision:str|None=None,offset:int=0,limit:int=30)->dict:
    """Read explicit seat/queue/workstation/activity targets, actual geometry revisions and live occupancy. Discovery is not execution evidence."""
    return rpc('list_interactions',locals())

@mcp.tool(name='people_validate_interaction',annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
def validate_interaction(actor_id:str,action:str,target:str,revision:str|None=None,hand:str|None=None)->dict:
    """Advisory action, current occupancy and static NavMesh preflight. Does not reserve or execute. Bind run_activity steps with interaction_revision to reject geometry changes."""
    return rpc('validate_interaction',locals())

@mcp.tool(name='people_motion',annotations=ToolAnnotations(readOnlyHint=False,destructiveHint=False,openWorldHint=False))
def motion(op:Literal['prepare','status','cancel'],spec:dict|None=None,job_id:str|None=None,expected_worker:str|None=None)->dict:
    """Optional local asset production only: prepare/status/cancel. Disabled without SIMPEOPLE_MOTION_ENDPOINT. Does not publish or play on a person; cancellation does not stop an actor. Reuse returned worker_instance_id on status/cancel. Generated is not native-verified."""
    from .motion import motion_operation
    try:return motion_operation(op,CLIENT_ID,spec,job_id,expected_worker)
    except SimPeopleError as error:
        body={'error':error.as_dict()}
        return CallToolResult(isError=True,structuredContent=body,content=[TextContent(type='text',text=json.dumps(body,ensure_ascii=False))])

@mcp.tool(name='people_spawn')
def spawn(request_id:str,actor_id:str,asset_id:str='default',spawn_anchor:str|list[float]='entrance',command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Create a human with independent native animation state. Retry with same request_id."""
    return rpc('spawn',locals())

@mcp.tool(name='people_despawn')
def despawn(request_id:str,actor_id:str,command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Cancel tasks and remove only this managed actor."""
    return rpc('despawn',locals())

@mcp.tool(name='people_move_to')
def move_to(request_id:str,actor_id:str,target:str|list[float],gait:str='walk',timeout_s:float=120,via:list[str|list[float]]|None=None,command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Move to semantic location or Z-up metre coordinates. Returns a task to poll."""
    return rpc('move_to',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_perform')
def perform(request_id:str,actor_id:str,action:str,target:str|list[float]|None=None,duration_s:float|None=None,command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None,hand:str|None=None)->dict:
    """Perform a listed action. Native head_look/reach_hand require exact-revision evidence and a settled standing actor."""
    return rpc('perform',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_validate_activity',annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
def validate_activity(actor_id:str,steps:list[dict])->dict:
    """Validate all activity steps without replacing the current plan. Step action values: move_to, wait, look_at, sit, leave_seat, follow, custom_action, queue, head_look, reach_hand. Walking/running use action=move_to, target and gait=walk/run; action=walk/run is invalid. See list_actions.activity_contract and actor capabilities for required fields and supported domains."""
    return rpc('validate_activity',locals())

@mcp.tool(name='people_run_activity')
def run_activity(request_id:str,actor_id:str,steps:list[dict],command_id:str|None=None,attempt_id:str|None=None,
                 on_blocked:str|None=None,if_busy:str|None=None,actor_instance_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Submit validated sequential steps from list_actions.activity_contract. Walking/running use action=move_to and gait=walk/run, not action=walk/run. Default supersede replaces the old plan after validation; if_busy=reject preserves it. on_blocked=report keeps supervision; replan_or_report requests up to two same-goal recoveries when the backend supports them, keeping the original deadline. Bind actor_instance_id to reject a plan for a deleted/recreated actor. Poll the returned task for actual completion."""
    return rpc('run_activity',locals())

@mcp.tool(name='people_get_state',annotations=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False))
def get_state(actor_id:str|None=None,task_id:str|None=None)->dict:
    """Read actual runtime position, joints, speed, task state and failure cause."""
    return rpc('get_state' if actor_id or task_id else 'crowd_state',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_session')
def session(action:str='info',request_id:str|None=None,expected_epoch:int|None=None,command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Read info/preflight. Acquire/release/takeover write ownership explicitly; takeover and release require current expected_epoch. Activities survive disconnect and takeover. This is local coordination, not authentication."""
    if action in {'info','preflight'}:return rpc('session_info' if action=='info' else 'preflight')
    return rpc('control_session',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_crowd')
def crowd(operation:str='state',request_id:str|None=None,selector:dict|None=None,
          items:list[dict]|None=None,steps:list[dict]|None=None,offset:int=0,limit:int=20,
          details:bool=False,after:int=0,command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """state: summary and paginated actors; events: incremental cursor. run_activity/cancel/spawn: batch with per-item outcomes, at most 100. run_activity items accept actor_id, steps, actor_instance_id, if_busy, on_blocked; cancel items accept actor_id/task_id and actor_instance_id; spawn items accept actor_id, asset_id, spawn_anchor, role, group. Selector supports actor_ids, role, group, region_m=[xmin,ymin,xmax,ymax]. Freeze selected IDs, then use explicit items to bind each instance or use selector.actor_ids with shared steps. Instance mismatch rejects that item without replacing the current task. Batch accepts items or selector+steps; policies belong to individual items. Poll task IDs for completion."""
    if operation=='state':return rpc('crowd_state',{'selector':selector,'offset':offset,'limit':limit,'details':details})
    if operation=='events':return rpc('read_events',{'after':after,'limit':limit})
    return rpc('batch',{k:v for k,v in {'request_id':request_id,'operation':operation,'selector':selector,'items':items,'steps':steps,'command_id':command_id,'attempt_id':attempt_id,'session_id':session_id,'episode_id':episode_id,'controller_epoch':controller_epoch}.items() if v is not None})

@mcp.tool(name='people_populate')
def populate(request_id:str,count:int=10,seed:int=42,asset_pool:list[str]|None=None,prefix:str='person',command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Create independent humans with seeded local role programs in an industrial scene. Returns per-actor results."""
    return rpc('populate',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_move_prop')
def move_prop(request_id:str,prop_id:str,position_m:list[float],command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Move a registered kinematic obstacle for dynamic-blockage tests."""
    return rpc('move_prop',locals())

@mcp.tool(name='people_cancel')
def cancel(request_id:str,task_id:str|None=None,actor_id:str|None=None,command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Request a native stop. Poll until cancelled; a completed task keeps its terminal state."""
    return rpc('cancel',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_signal_event')
def signal_event(request_id:str,kind:str,actor_ids:list[str],source_id:str='agent',target:str|list[float]|None=None,duration_s:float=3,command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Supply robot_nearby, passage_blocked, call_person or region_closed events. Ordinary events defer across seat/queue interactions; inspect get_state for outcomes."""
    return rpc('signal_event',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_reset')
def reset(request_id:str,episode_id:str|None=None,command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Delete managed actors, cancel tasks and invalidate old episode resources."""
    return rpc('reset',{k:v for k,v in locals().items() if v is not None})

@mcp.tool(name='people_pause')
def pause(request_id:str,command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Pause simulation and activity clocks while keeping bridge responsive."""
    return rpc('pause',locals())

@mcp.tool(name='people_resume')
def resume(request_id:str,command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Resume simulation and activity clocks."""
    return rpc('resume',locals())

@mcp.tool(name='people_record')
def record(request_id:str,mode:str,view:str|None=None,actor_id:str|None=None,command_id:str|None=None,attempt_id:str|None=None,session_id:str|None=None,episode_id:str|None=None,controller_epoch:int|None=None)->dict:
    """Start/stop RGB recording, or mode=camera with view=overview/follow/seat_side/gait_side and actor_id. Output stays in the current run directory. Recording may be disabled by the session capture profile."""
    return rpc('record',{k:v for k,v in locals().items() if v is not None})

def main():mcp.run(transport='stdio')
if __name__=='__main__':main()
