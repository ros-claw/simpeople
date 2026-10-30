"""Session coordination and bounded crowd APIs, independent of Kit.

Controller IDs coordinate local clients; they are not authentication credentials.
Activities belong to the runtime and survive transport disconnection or takeover.
"""
import copy
import math
from collections import Counter
from .errors import SimPeopleError
from .protocol import identifier

def bounded_int(value,name,lo,hi):
    if isinstance(value,bool) or not isinstance(value,int) or not lo<=value<=hi:
        raise SimPeopleError('INVALID_REQUEST',f'{name} must be an integer in [{lo},{hi}]')
    return value

class Management:
    def controller_check(self,p):
        client=identifier(p.get('controller_id','legacy-local'),'controller_id')
        if 'controller_epoch' in p:bounded_int(p['controller_epoch'],'controller_epoch',0,2**63-1)
        if p.get('controller_epoch',self.controller_epoch)!=self.controller_epoch:
            raise SimPeopleError('CONTROLLER_STALE','control generation changed',controller_epoch=self.controller_epoch)
        if self.controller_id is None:
            self.controller_id=client;self.controller_epoch+=1
            self.event('controller_acquired',controller_id=client,controller_epoch=self.controller_epoch)
        if client!=self.controller_id:
            raise SimPeopleError('CONTROLLER_BUSY','another client owns this session; use explicit takeover',
                                 controller_id=self.controller_id,controller_epoch=self.controller_epoch)

    def cmd_session_info(self,p):
        return {'api_version':'0.2','session_id':self.session_id,'episode_id':self.episode_id,
                'scene_id':getattr(self.backend,'scene_id',None),'scene_revision':getattr(self.backend,'scene_revision',None),
                'runtime_revision':getattr(self.backend,'runtime_revision',None),
                'run_mode':getattr(self.backend,'run_mode','attached'),'render_profile':getattr(self.backend,'render_profile',None),
                'controller_id':self.controller_id,'controller_epoch':self.controller_epoch,
                'tasks_persist_on_disconnect':True,'coordination':'local logical ownership; not authentication',
                'event_cursor':self.event_sequence,'modes':['interactive','generation','audit','experimental'],
                'capacity_status':'see versioned acceptance evidence; modes do not imply real-time capacity'}

    def cmd_control_session(self,p):
        client=identifier(p.get('controller_id'),'controller_id');action=p.get('action','acquire')
        if action not in {'acquire','release','takeover'}:raise SimPeopleError('INVALID_REQUEST','invalid control action')
        expected=p.get('expected_epoch')
        if expected is not None:bounded_int(expected,'expected_epoch',0,2**63-1)
        if action in {'takeover','release'} and expected!=self.controller_epoch:
            raise SimPeopleError('CONTROLLER_STALE','supply current expected_epoch',controller_epoch=self.controller_epoch)
        if action=='release':
            if client!=self.controller_id:raise SimPeopleError('CONTROLLER_BUSY','only the current controller can release')
            self.controller_id=None;self.controller_epoch+=1
        elif action=='acquire':self.controller_check(p)
        else:
            self.controller_id=client;self.controller_epoch+=1
        self.event('controller_changed',action=action,controller_id=self.controller_id,controller_epoch=self.controller_epoch)
        return self.cmd_session_info({})

    def actor_metadata(self,aid):
        a=self.actor(aid);assignment=self.population.assignments.get(aid,{}) if self.population else {}
        return {'role':assignment.get('role',a.get('role')),'group':a.get('group')}

    def select_actors(self,selector=None):
        selector=selector or {}
        if not isinstance(selector,dict) or set(selector)-{'actor_ids','role','group','region_m'}:
            raise SimPeopleError('INVALID_REQUEST','selector accepts actor_ids, role, group, region_m')
        ids=selector.get('actor_ids',list(self.actors))
        if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids):raise SimPeopleError('INVALID_REQUEST','actor_ids must be strings')
        ids=list(dict.fromkeys(ids))
        for aid in ids:self.actor(aid)
        region=selector.get('region_m')
        if region is not None:
            if (not isinstance(region,list) or len(region)!=4 or any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in region)
                or region[0]>region[2] or region[1]>region[3]):raise SimPeopleError('INVALID_REQUEST','region_m must be [xmin,ymin,xmax,ymax]')
        selected=[]
        for aid in ids:
            meta=self.actor_metadata(aid)
            if any(k in selector and meta[k]!=selector[k] for k in ('role','group')):continue
            if region is not None:
                o=self.backend.observe(self.actor(aid)['handle']);pos=o.get('position_m')
                if not o.get('ready') or not (region[0]<=pos[0]<=region[2] and region[1]<=pos[1]<=region[3]):continue
            selected.append(aid)
        return sorted(selected)

    def cmd_crowd_state(self,p):
        ids=self.select_actors(p.get('selector'));offset=bounded_int(p.get('offset',0),'offset',0,1000000)
        limit=bounded_int(p.get('limit',20),'limit',1,100);details=bool(p.get('details',False))
        status=Counter();actions=Counter();rows=[]
        for aid in ids:
            a=self.actor(aid);task=self.tasks.get(a['task_id']);s=task['status'] if task else 'idle'
            status[s]+=1
            if task and task['step_index']<len(task['steps']):actions[task['steps'][task['step_index']]['action']]+=1
        for aid in ids[offset:offset+limit]:
            a=self.actor(aid);t=self.tasks.get(a['task_id']);o=self.backend.observe(a['handle'])
            row={'actor_id':aid,**self.actor_metadata(aid),'status':t['status'] if t else 'idle',
                 'task_id':a['task_id'],'position_m':o.get('position_m'),'speed_mps':o.get('speed_mps'),
                 'error':t.get('error') if t else None,'seat':a['seat']}
            if details:row.update(task=self.public(t) if t else None,observation=o)
            rows.append(row)
        return {**self.cmd_session_info({}),'sim_time':self.sim_time,'paused':self.paused,'total':len(ids),
                'status_counts':dict(status),'action_counts':dict(actions),'actors':rows,
                'next_offset':offset+limit if offset+limit<len(ids) else None}

    def cmd_read_events(self,p):
        cursor=bounded_int(p.get('after',0),'after',0,2**63-1);limit=bounded_int(p.get('limit',50),'limit',1,100)
        oldest=self.event_buffer[0]['cursor'] if self.event_buffer else self.event_sequence+1
        rows=[copy.deepcopy(e) for e in self.event_buffer if e['cursor']>cursor][:limit]
        return {'session_id':self.session_id,'events':rows,'next_cursor':rows[-1]['cursor'] if rows else cursor,
                'latest_cursor':self.event_sequence,'history_gap':cursor<oldest-1,'oldest_cursor':oldest}

    def cmd_batch(self,p):
        operation=p.get('operation');selector=p.get('selector');items=p.get('items')
        if operation not in {'run_activity','cancel','spawn'}:raise SimPeopleError('INVALID_REQUEST','batch supports run_activity, cancel, spawn')
        if items is None:
            if operation=='spawn':raise SimPeopleError('INVALID_REQUEST','spawn requires explicit items')
            ids=self.select_actors(selector)
            items=[{'actor_id':aid,**({'steps':p.get('steps')} if operation=='run_activity' else {})} for aid in ids]
        elif selector is not None:raise SimPeopleError('INVALID_REQUEST','use items or selector, not both')
        if not isinstance(items,list) or len(items)>100 or any(not isinstance(x,dict) for x in items):
            raise SimPeopleError('INVALID_REQUEST','items must be at most 100 objects')
        # Validate the whole envelope before executing; item errors remain individual.
        allowed={'actor_id','steps'} if operation=='run_activity' else {'actor_id','task_id'} if operation=='cancel' else {'actor_id','asset_id','spawn_anchor','role','group'}
        if any(set(x)-allowed for x in items):raise SimPeopleError('INVALID_REQUEST','unsupported batch item fields')
        results=[]
        for index,item in enumerate(items):
            try:
                result=getattr(self,'cmd_'+operation)(copy.deepcopy(item))
                results.append({'index':index,'actor_id':item.get('actor_id'),'result':result})
            except SimPeopleError as err:results.append({'index':index,'actor_id':item.get('actor_id'),'error':err.as_dict()})
        return {'results':results,'accepted':sum('error' not in r for r in results),'rejected':sum('error' in r for r in results),
                'atomic':False,'completion':'poll task_id; accepted does not mean completed'}

    def cmd_preflight(self,p):
        scene=self.backend.inspect_scene();frame=scene.get('frame_spec',{})
        checks=[{'name':'navmesh','passed':bool(scene.get('navmesh_available'))},
                {'name':'stage_units','passed':bool(scene.get('meters_per_unit',frame.get('meters_per_unit',0))>0 and frame.get('up_axis') in {'Y','Z'})},
                {'name':'semantics','passed':bool(scene.get('semantic_targets',scene.get('locations',{})))}]
        assets=self.backend.list_assets()
        checks.append({'name':'available_assets','passed':any(a.get('runtime_available',True) for a in assets)})
        seats={name:value.get('seat_profile') for name,value in scene.get('locations',{}).items() if value.get('kind')=='seat'}
        return {'session_id':self.session_id,'checks':checks,'ready':all(x['passed'] for x in checks),
                'scene':scene,'assets':[{'asset_id':a['asset_id'],'available':a.get('runtime_available',True),
                    'verified_actions':a.get('verified_actions',[]),'verification_status':a.get('verification_status')} for a in assets],
                'seats':seats,'uncalibrated_seats':[name for name,profile in seats.items() if profile is None],
                'seat_quality':'functional sit is separate from geometric quality certification',
                'handoff_schema':'schemas/scene-handoff.schema.json'}
