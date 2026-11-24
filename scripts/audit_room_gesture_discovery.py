"""Fresh-source handoff gesture discovery; never promotes a capability catalog."""
import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import sys


OWNER=['session_id','episode_id','actor_id','actor_instance_id','control_epoch','task_id']


def reject_fences(row):
    before,after=row['before'],row['after']
    required={'controller_id','controller_epoch','task_count','actor_instance_id','control_epoch','task_id',
              'actual_native_action_task_id','owned_gesture_ids'}
    if set(before)!=required or before!=after:raise ValueError('stale rejection changed logical or actual SDK owner')
    if any(not isinstance(before[k],str) or not before[k] for k in ['controller_id','actor_instance_id','task_id']):
        raise ValueError('stale rejection owner identity missing')
    if any(type(before[k]) is not int or before[k]<0 for k in ['controller_epoch','task_count','control_epoch','actual_native_action_task_id']):
        raise ValueError('invalid stale rejection owner fence')


def hold_end_cancellation(task, event, start, overlay, events):
    """The last pose is read before tick cancels the completed overlay.

    SDK state is sampled after that tick. Only its exact journaled boundary
    cancellation is allowed; an earlier failed sample never qualifies.
    """
    old=start['native_task_id'];owned=overlay.get('owned',{})
    if owned.get('native_task_id')!={'native_task_id':old,'actual_status':'failed'}:
        return False
    fields=['session_id','episode_id','actor_id','actor_instance_id','control_epoch']
    ends=[e for e in events if e['kind']=='native_task_ended'
          and ((type(e.get('native_task_id')) is int and e['native_task_id']==old)
               or (type(e.get('native_task_id')) is str and e['native_task_id']==str(old)))
          and e.get('logical_task_id')==task['task_id']]
    if len(ends)!=1:return False
    end=ends[0]
    if (any(end.get(k)!=task[k] for k in fields) or end.get('agent')!=start['agent']
            or end.get('sim_time')!=event['sim_time'] or overlay.get('sim_time')!=event['sim_time']
            or end.get('task_error_name')!='BehaviorTaskError.CANCELED'
            or end.get('correlation_status')!='unique' or type(end.get('cursor')) is not int
            or type(event.get('cursor')) is not int or not 0<=end['cursor']<event['cursor']):
        return False
    if start['action']=='head_look':
        returns=[e for e in events if e['kind']=='native_gesture_return_started'
                 and e.get('original_native_task_id')==old and e.get('task_id')==task['task_id']]
        if len(returns)!=1:return False
        returned=returns[0];tid=returned.get('native_task_id')
        if (type(tid) is not int or tid==old or any(returned.get(k)!=task[k] for k in fields)
                or returned.get('agent')!=start['agent'] or returned.get('sim_time')!=event['sim_time']
                or not end['cursor']<returned['cursor']<event['cursor']
                or owned.get('return_task_id')!={'native_task_id':tid,'actual_status':'running'}):return False
    elif 'return_task_id' in owned:return False
    return True


def hold(task,event,start,binding,rows,overlays,measure_fn,events=()):
    if task['status']!='succeeded' or task['steps'][0]['duration_s']!=.6 or task['steps'][0]['timeout_s']!=8:
        raise ValueError('original short gesture task/budget changed')
    if any(binding.get(k)!=task[k] for k in ['task_id','actor_id','actor_instance_id','control_epoch']):
        raise ValueError('gesture SDK binding belongs to another owner')
    old=binding['native_task_id']
    if type(old) is not int or start['native_task_id']!=old:raise ValueError('actual gesture SDK task missing')
    if event['task_id']!=task['task_id'] or event['hold_sim_s']<.6-1e-7 or event['hold_sim_s']>.6+1/30+1e-7:
        raise ValueError('recorded hold duration or task changed')
    begin=event['sim_time']-event['hold_sim_s'];end=event['sim_time']
    selected=[r for r in rows if r.get('task_id')==task['task_id'] and begin-1e-7<=r['sim_time']<=end+1e-7]
    if len(selected)<19 or abs(selected[0]['sim_time']-begin)>1e-7 or abs(selected[-1]['sim_time']-end)>1e-7:
        raise ValueError('full actual hold interval missing')
    body,prim=selected[0].get('traffic_body_instance_id'),selected[0].get('native_actor_prim_path')
    if not isinstance(body,str) or not body or not isinstance(prim,str) or not prim or start['agent']!=prim:
        raise ValueError('actual gesture body identity missing')
    indexed={r['frame_identity']['source_tick']:r for r in overlays}
    if len(indexed)!=len(overlays):raise ValueError('duplicate SDK overlay frame')
    for i,row in enumerate(selected):
        tick=row['frame_identity']['source_tick'];overlay=indexed.get(tick,{})
        running=overlay.get('owned',{}).get('native_task_id')=={'native_task_id':old,'actual_status':'running'}
        boundary=(i==len(selected)-1 and hold_end_cancellation(task,event,start,overlay,events))
        if (type(tick) is not int or any(row.get(k)!=task[k] or overlay.get(k)!=task[k] for k in OWNER)
                or row.get('ready') is not True or row.get('position_source')!='BehaviorAgent.get_world_translation'
                or type(row.get('observation_sim_time')) not in (float,int) or not math.isfinite(row['observation_sim_time'])
                or abs(row['observation_sim_time']-row['sim_time'])>1e-7
                or row.get('traffic_body_instance_id')!=body or row.get('native_actor_prim_path')!=prim
                or overlay.get('frame_identity')!=row['frame_identity'] or overlay.get('sim_time')!=row['sim_time']
                or overlay.get('traffic_body_instance_id')!=body or overlay.get('native_actor_prim_path')!=prim
                or not (running or boundary)):
            raise ValueError('hold lacks fresh same-owner running Native gesture evidence')
        if i and (tick!=selected[i-1]['frame_identity']['source_tick']+1 or abs(row['sim_time']-selected[i-1]['sim_time']-1/30)>1e-6):
            raise ValueError('actual gesture hold is not continuous30Hz')
        if not measure_fn(start['action'],start.get('hand'),start['target_m'],start['baseline'],row)['aligned']:
            raise ValueError('actual joint geometry does not support claimed hold')
    return {'task_id':task['task_id'],'actor_id':task['actor_id'],'action':start['action'],
            'actual_samples':len(selected),'hold_sim_s':end-begin,'actual_running_gesture_native_id':old,
            'traffic_body_instance_id':body,'native_actor_prim_path':prim}


def sha_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def audit(folder):
    folder=Path(folder);errors=[];proofs=[];hashes={}
    try:
        read=lambda n:json.loads((folder/n).read_text());done=read('completed.json');config=read('probe_config.json')
        if (not done['harness_completed'] or not done['functional_expected_matched'] or done['strict_catalog_verified'] is not False
                or done['unverified_gesture_discovery'] is not True or abs(done['duration_s']-16)>1e-6 or done['frames']!=480):
            raise ValueError('original16s/480frame discovery did not close')
        if config['layout']!='room' or not config['gestures'] or not config['discovery'] or config['startup_profile']!='product-default' or config['minimal_sampling']:
            raise ValueError('frozen discovery/sampling/startup mode changed')
        if (folder/'bound_gesture_acceptance.json').exists():raise ValueError('discovery must not emit strict gesture acceptance')
        snap=folder/'source_snapshot';manifest=read('source_manifest.json')
        for name,digest in manifest.items():
            path=snap/name
            if not path.resolve().is_relative_to(snap.resolve()) or sha_file(path)!=digest:raise ValueError('source snapshot changed')
        catalog=read('source_snapshot/configs/native_gesture_catalog.json')
        if any(record['status']!='discovered' for record in catalog['records']):raise ValueError('discovery copied or promoted a catalog proof')
        settings=read('sdk_idle_settings.json');prefix='/exts/omni.anim.behavior.core/'
        tags=['Idle','IdleCautious','IdleGroove','IdleTaunt','IdleTilt','IdleTired','IdleTough']
        if settings['startup_profile']['mode']!='default' or settings['startup_profile']['active_tags']!=tags or settings['requested_api_seed']!=42:
            raise ValueError('product default menu/seed request changed')
        for k,v in [('agentResponseTime',1/30),('agentResponseTimeMaxRandomOffset',0),('navBlockedTimeout',3)]:
            actual=settings['active_response'][prefix+k]
            if type(actual) not in (int,float) or not math.isfinite(actual) or abs(actual-v)>1e-8:raise ValueError('product response settings changed')
        capture=[json.loads(x) for x in (folder/'video_timestamps.jsonl').open()];metrics=read('recording_metrics.json')
        if len(capture)!=480 or metrics['frames_written']!=480 or metrics['empty_rgb_frames'] or metrics['dropped_frames']:
            raise ValueError('room RGB capture incomplete')
        for i,stamp in enumerate(capture):
            if type(stamp['frame']) is not int or stamp['frame']!=i or stamp['frame_identity']['source_tick']!=i or (i and abs(stamp['sim_time']-capture[i-1]['sim_time']-1/30)>1e-6):
                raise ValueError('RGB identities/clock changed')
        events=[json.loads(x) for x in (folder/'events.jsonl').open()];rows=[json.loads(x) for x in (folder/'trajectories.jsonl').open()]
        overlays=[json.loads(x) for x in (folder/'gesture_frame_states.jsonl').open()]
        if len(overlays)!=480:raise ValueError('all actual overlay frames required')
        for row,stamp in zip(overlays,capture):
            if row['frame_identity']!=stamp['frame_identity'] or row['sim_time']!=stamp['sim_time']:raise ValueError('overlay/RGB identity mismatch')
        registry=read('registry_acceptance.json');discovery=read('bound_gesture_discovery.json')
        if registry['initial']['scene_id']!=read('scene_handoff.json')['scene_id'] or registry['bound_head_hand_verified'] is not False or discovery['strict_catalog_verified'] is not False:
            raise ValueError('handoff scene or discovery scope changed')
        if registry['bound_task']['error']['code']!='TARGET_STALE' or registry['fresh_task']['status']!='succeeded':raise ValueError('registry revision lifecycle failed')
        reject_fences(registry['stale_revision_fences']);reject_fences(discovery['stale_anchor_fences'])
        if discovery['old_anchor_error']['code']!='TARGET_STALE':raise ValueError('old palm anchor not rejected')
        sys.path.insert(0,str(snap/'src'));math_module=importlib.import_module('simpeople.core.gestures')
        if Path(math_module.__file__).resolve()!=snap.joinpath('src/simpeople/core/gestures.py').resolve():raise ValueError('gesture math imported from a different source')
        holds=[e for e in events if e['kind']=='gesture_hold_completed']
        if len(holds)!=2:raise ValueError('exactly two original room gesture holds required')
        for name in ['head','hand']:
            task=discovery[name+'_task'];preflight=discovery[name+'_preflight']
            if preflight['valid'] or not preflight['errors'] or any(e['code']!='ACTION_UNVERIFIED' for e in preflight['errors']):raise ValueError('discovery falsely passed capability preflight')
            step=task['steps'][0]
            if step['target']!=preflight['resolved_target_m'] or step['resource_id']!='gesture_station' or step['interaction_revision']!=preflight['target']['geometry_revision']:
                raise ValueError('gesture did not bind explicit geometry revision/anchor')
            bindings=[e for e in events if e['kind']=='native_task_bound' and e.get('task_id')==task['task_id'] and type(e.get('native_task_id')) is int]
            if len(bindings)!=1:raise ValueError('one actual SDK gesture binding required')
            binding=bindings[0];starts=[e for e in events if e['kind']=='native_gesture_started' and e['native_task_id']==binding['native_task_id']]
            ended=[e for e in holds if e['task_id']==task['task_id']]
            if len(starts)!=1 or len(ended)!=1:raise ValueError('original gesture hold/baseline missing')
            proofs.append(hold(task,ended[0],starts[0],binding,rows,overlays,math_module.measure,events))
        cleanup=read('gesture_owned_task_states.json');states=cleanup['states']
        if len(states)!=3 or any(s['actual_status']=='running' for s in states) or cleanup['remaining_gesture_owners']:
            raise ValueError('owned gesture or return SDK task remains active')
        if any(s['actor_id']!='operator' or s['actor_instance_id']!=discovery['head_task']['actor_instance_id']
               or s['agent']!=proofs[0]['native_actor_prim_path'] for s in states):raise ValueError('cleanup belongs to another actual actor')
        if registry['witness_task']['status']!='succeeded':raise ValueError('independent witness did not finish')
        witness=[r for r in rows if r['actor_id']=='witness']
        if len(witness)!=480 or any(any(r.get(k)!=registry['witness_task'][k] for k in OWNER) for r in witness):raise ValueError('witness body stream/owner missing')
        witness_body=witness[0].get('traffic_body_instance_id');witness_prim=witness[0].get('native_actor_prim_path')
        if (not isinstance(witness_body,str) or not witness_body or not isinstance(witness_prim,str) or not witness_prim
                or witness_body==proofs[0]['traffic_body_instance_id'] or witness_prim==proofs[0]['native_actor_prim_path']):raise ValueError('distinct witness Native body required')
        for row,stamp in zip(witness,capture):
            position=row.get('position_m')
            if (row.get('ready') is not True or row.get('position_source')!='BehaviorAgent.get_world_translation'
                    or row.get('frame_identity')!=stamp['frame_identity'] or row.get('sim_time')!=stamp['sim_time']
                    or row.get('observation_sim_time')!=row['sim_time'] or row.get('traffic_body_instance_id')!=witness_body
                    or row.get('native_actor_prim_path')!=witness_prim or not isinstance(position,list) or len(position)!=3
                    or any(type(v) not in (int,float) or not math.isfinite(v) for v in position)):
                raise ValueError('witness actual body/RGB stream changed')
        if max(math.dist(r['position_m'][:2],witness[0]['position_m'][:2]) for r in witness)<=1:raise ValueError('witness did not move')
        for name in ['source_manifest.json','probe_config.json','scene_handoff.json','registry_acceptance.json','bound_gesture_discovery.json',
                     'events.jsonl','trajectories.jsonl','gesture_frame_states.jsonl','gesture_owned_task_states.json','video_timestamps.jsonl','sdk_idle_settings.json']:
            hashes[name]=sha_file(folder/name)
    except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError) as error:errors.append(str(error))
    return {'run_id':folder.name,'discovery_measurement_verified':not errors and len(proofs)==2,'errors':errors,'holds':proofs,
            'inputs_sha256':hashes,'strict_catalog_verified':False,'production_source_installed':False,'qualified_generated_native_rigs':[],
            'scope':'Two short Default gestures bound to explicit handoff-room anchors, revision rejection, actual SDK overlay and continuous joint readback. Discovery only; no old proof transfer, strict catalog, second-asset, long hold, skin/force or generated rig qualification.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run');p.add_argument('--output',required=True);args=p.parse_args();result=audit(args.run)
    Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps({k:result[k] for k in ['run_id','discovery_measurement_verified','errors']}))
    raise SystemExit(0 if result['discovery_measurement_verified'] else 2)
