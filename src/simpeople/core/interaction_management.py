"""Read-only Agent access to versioned interaction geometry and live occupancy."""
import math
from .scene_semantics import SceneInteractionRegistry,ACTIVE
from .errors import SimPeopleError


class InteractionManagement:
    def interaction_registry(self,semantic_id=None):
        if not hasattr(self.backend,'interaction_targets'):
            raise SimPeopleError('ACTION_UNSUPPORTED','backend has no interaction registry')
        return SceneInteractionRegistry(self.backend.interaction_targets(semantic_id),getattr(self.backend,'scene_id',None))

    def interaction_occupancy(self,registry):
        resources=self.resources.snapshot()['admission'];queues=self.queues.snapshot();result={}
        for name,target in registry.targets.items():
            group=(queues if target['kind']=='queue' else resources).get(target.get('resource_id',name),{})
            def row(t):
                token=t.get('lease_token',[])
                return {'actor_id':t['actor_id'],'actor_instance_id':token[1] if len(token)>2 else None,
                    'ticket_id':t['ticket_id'],'status':t['status'],'rank':t['rank']}
            result[name]={'occupants':[row(t) for t in group.get('tickets',[]) if t['status'] in ACTIVE],
                'waiters':[row(t) for t in group.get('tickets',[]) if t['status']=='waiting'],
                'outside_capacity':group.get('outside_capacity',self.policy['queue_outside_capacity'] if target['kind']=='queue' else self.policy['resource_waiter_capacity']),
                'cleanup_actor_ids':[aid for aid,a in self.actors.items() if a.get('queue_cleanup',{}).get('resource_id')==name or a.get('release_seat_when_standing') and a.get('seat')==name]}
        return result

    def cmd_list_interactions(self,p):
        from .management import bounded_int
        if p.get('revision') is not None and not p.get('target'):raise SimPeopleError('INVALID_REQUEST','revision requires a target')
        registry=self.interaction_registry(p.get('target'));rows=registry.list(p.get('kind'))
        if p.get('target'):rows=[registry.resolve(p['target'],p.get('revision'))]
        offset=bounded_int(p.get('offset',0),'offset',0,1000000);limit=bounded_int(p.get('limit',30),'limit',1,100)
        occupancy=self.interaction_occupancy(registry)
        return {'session_id':self.session_id,'episode_id':self.episode_id,'snapshot_sim_time':self.sim_time,
            'scene_id':registry.scene_id,'registry_revision':registry.revision,'total':len(rows),
            'interactions':[{**r,'occupancy':occupancy[r['semantic_id']]} for r in rows[offset:offset+limit]],
            'next_offset':offset+limit if offset+limit<len(rows) else None,'advisory':True,'reservation_acquired':False}

    def cmd_validate_interaction(self,p):
        a=self.actor(p.get('actor_id'));name=p.get('target');registry=self.interaction_registry(name)
        target=registry.resolve(name,p.get('revision'));obs=self.backend.observe(a['handle'])
        if hasattr(self.backend,'refresh_quality_revisions'):self.backend.refresh_quality_revisions()
        capabilities=self.backend.list_actions(a['handle'])
        if p.get('action')=='custom_action':
            # Discovery mode may allow backend.validate() to accept unverified
            # clips; acceptance must never manufacture a verified capability.
            clip=capabilities.get('custom_action',{}).get('clips',{}).get(target.get('clip'),{'status':'unsupported'})
            capabilities={**capabilities,'custom_action':clip}
        paths={}
        for approach in target['approach_points_m']:
            if not hasattr(self.backend,'interaction_path_reachable'):break
            if self.backend.interaction_path_reachable(a['handle'],approach):paths[name]=True;break
            paths[name]=False
        bodies={aid:self.backend.observe(other['handle']) for aid,other in self.actors.items() if aid!=p['actor_id']}
        def clearance(points):
            return [{'position_m':point,'blocker_ids':[aid for aid,o in bodies.items() if o.get('ready') and o.get('position_m') is not None and
                math.dist(point[:2],o['position_m'][:2])<.9]} for point in points]
        clearances={'approaches':clearance(target['approach_points_m']),'exits':clearance(target['exit_points_m']),
            'threshold_m':.9,'unknown_body_ids':[aid for aid,o in bodies.items() if not o.get('ready')]}
        actor={**obs,'actor_id':p['actor_id'],'actor_instance_id':a['actor_instance_id'],'capabilities':capabilities}
        snapshot={'sim_time':self.sim_time,'occupancy':self.interaction_occupancy(registry),'path_checks':paths,
            'navmesh_available':self.backend.inspect_scene().get('navmesh_available')}
        result=registry.validate_interaction(actor,p.get('action'),name,snapshot,p.get('revision'))
        if p.get('action') in {'head_look','reach_hand'}:
            try:
                point=self.gesture_anchor(target,p['action'],p.get('hand'))
                spec={'action':p['action'],'target':point,'duration_s':min(1,capabilities.get(p['action'],{}).get('max_hold_duration_s',1))}
                if p['action']=='reach_hand':spec['hand']=p.get('hand')
                self.backend.validate(a['handle'],spec)
                result['resolved_target_m']=point
            except SimPeopleError as error:
                result['valid']=False;result['errors'].append(error.as_dict())
        result['body_clearance']=clearances
        if clearances['approaches'] and all(row['blocker_ids'] for row in clearances['approaches']):
            if target['kind']=='queue':result['warnings'].append('queue_approach_occupied_wait_required')
            else:
                result['valid']=False;result['errors'].append({'code':'TARGET_BLOCKED','blockers':sorted({aid for row in clearances['approaches'] for aid in row['blocker_ids']})})
        if clearances['exits'] and all(row['blocker_ids'] for row in clearances['exits']):result['warnings'].append('all_exit_points_currently_occupied')
        if clearances['unknown_body_ids']:result['warnings'].append('some_body_positions_unavailable')
        if p.get('action')=='sit':result['actor_specific_quality']=capabilities.get('sit',{}).get('seat_quality',{}).get(name,{'status':'unverified'})
        return {**result,'session_id':self.session_id,'episode_id':self.episode_id}

    def validate_interaction_revision(self,step):
        expected=step.get('interaction_revision')
        if expected is None:return
        name=step.get('resource_id') or step.get('target')
        target=self.interaction_registry(name).resolve(name,expected)
        if step['action'] not in target['allowed_actions'] or step['action']=='custom_action' and step['target']!=target.get('clip'):
            raise SimPeopleError('ACTION_UNSUPPORTED','step is not an allowed interaction action',target=name,action=step['action'])
        if step['action'] in {'head_look','reach_hand'}:
            point=self.gesture_anchor(target,step['action'],step.get('hand'))
            if math.dist(point,self.backend.resolve_target(step['target']))>.001:
                raise SimPeopleError('TARGET_INVALID','bound gesture must use the declared anchor',target=name)

    def gesture_anchor(self,target,action,hand):
        if action=='reach_hand' and hand not in {'left','right'}:raise SimPeopleError('INVALID_REQUEST','reach preflight requires hand left or right')
        key='look' if action=='head_look' else 'palm_'+hand
        anchor=target.get('anchors',{}).get(key,{})
        if anchor.get('position_m') is None:raise SimPeopleError('TARGET_INVALID','explicit gesture anchor unavailable',anchor=key)
        return anchor['position_m']
