"""Versioned interaction targets and advisory checks, with no Kit dependencies."""
import copy
import hashlib
import json
import math
from .errors import SimPeopleError

DEFAULT_ACTIONS={'seat':{'sit'},'queue':{'queue'},'workstation':{'wait','look_at'},'activity_bay':{'custom_action'}}
KINDS={**DEFAULT_ACTIONS,'workstation':{'wait','look_at','head_look','reach_hand'}}
ACTIVE={'admitted','serving','exiting'}


def revision(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


class SceneInteractionRegistry:
    def __init__(self,targets,scene_id=None):
        self.scene_id=scene_id;self.targets={};paths=set()
        for raw in targets:
            item=copy.deepcopy(raw);semantic=item.get('semantic_id');kind=item.get('kind')
            if not isinstance(semantic,str) or not semantic or semantic in self.targets:
                raise SimPeopleError('TARGET_INVALID','interaction IDs must be unique nonempty strings')
            if kind not in KINDS or not str(item.get('prim_path','')).startswith('/'):
                raise SimPeopleError('TARGET_INVALID','interaction requires an explicit kind and USD path',target=semantic)
            if item['prim_path'] in paths:raise SimPeopleError('TARGET_INVALID','one physical interaction cannot have independent resource aliases',target=semantic)
            paths.add(item['prim_path'])
            capacity=item.get('capacity',1)
            if isinstance(capacity,bool) or not isinstance(capacity,int) or not 1<=capacity<=100:
                raise SimPeopleError('TARGET_INVALID','invalid interaction capacity',target=semantic)
            actions=item.get('allowed_actions',sorted(DEFAULT_ACTIONS[kind]))
            if not isinstance(actions,list) or any(not isinstance(x,str) for x in actions) or not set(actions)<=KINDS[kind]:
                raise SimPeopleError('TARGET_INVALID','action is not supported for this interaction kind',target=semantic)
            item.update(capacity=capacity,allowed_actions=actions,
                frame_spec={'up_axis':'Z','units':'metres','handedness':'right'})
            for field in ['approach_points_m','exit_points_m']:
                for point in item.setdefault(field,[]):
                    if not isinstance(point,(list,tuple)) or len(point)!=3 or any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) for x in point):
                        raise SimPeopleError('TARGET_INVALID','invalid interaction point',target=semantic,field=field)
            anchors=item.get('anchors',{})
            if not isinstance(anchors,dict):raise SimPeopleError('TARGET_INVALID','interaction anchors must be a mapping',target=semantic)
            for name,anchor in anchors.items():
                point=anchor.get('position_m') if isinstance(anchor,dict) else None
                if not isinstance(point,(list,tuple)) or len(point)!=3 or any(isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x) for x in point):
                    raise SimPeopleError('TARGET_INVALID','anchor requires a finite metre position',target=semantic,anchor=name)
            evidence=item.pop('evidence',{'status':'discovered','reason':'no revision-bound execution evidence attached'})
            digest=revision(item);status=evidence.get('status','discovered')
            if status not in {'discovered','calibrated','verified','unavailable'}:
                raise SimPeopleError('TARGET_INVALID','unknown evidence status',target=semantic)
            if status in {'calibrated','verified'} and evidence.get('geometry_revision')!=digest:
                evidence={**evidence,'status':'discovered','invalidated':True,'reason':'evidence geometry revision changed'}
            self.targets[semantic]={**item,'geometry_revision':digest,'evidence':evidence}
        self.revision=revision({name:item['geometry_revision'] for name,item in sorted(self.targets.items())})

    def resolve(self,semantic_id,expected_revision=None):
        if not isinstance(semantic_id,str):raise SimPeopleError('INVALID_REQUEST','target must be an interaction ID')
        if semantic_id not in self.targets:raise SimPeopleError('TARGET_NOT_FOUND','unregistered interaction',target=semantic_id)
        item=self.targets[semantic_id]
        if expected_revision is not None and expected_revision!=item['geometry_revision']:
            raise SimPeopleError('TARGET_STALE','interaction geometry changed',target=semantic_id,
                expected_revision=expected_revision,geometry_revision=item['geometry_revision'])
        return copy.deepcopy(item)

    def list(self,kind=None):
        if kind is not None and kind not in KINDS:raise SimPeopleError('INVALID_REQUEST','unknown interaction kind')
        return [self.resolve(name) for name in sorted(self.targets) if kind is None or self.targets[name]['kind']==kind]

    def validate_interaction(self,actor,action,semantic_id,snapshot,expected_revision=None):
        item=self.resolve(semantic_id,expected_revision);errors=[];warnings=[]
        if item['evidence']['status']=='unavailable' or not item['approach_points_m']:errors.append({'code':'TARGET_INVALID','reason':'interaction approach unavailable'})
        if action not in item['allowed_actions']:errors.append({'code':'ACTION_UNSUPPORTED','action':action})
        if not actor.get('ready'):errors.append({'code':'SIM_NOT_READY'})
        capabilities=actor.get('capabilities',{})
        required={'sit':['walk','sit'],'queue':['walk','queue'],'wait':['walk','wait'],'look_at':['look_at'],'custom_action':['custom_action'],'head_look':['head_look'],'reach_hand':['reach_hand']}.get(action,[])
        for capability in required:
            if capabilities.get(capability,{}).get('status')!='verified':
                errors.append({'code':'ACTION_UNVERIFIED','capability':capability})
        occupancy=copy.deepcopy(snapshot.get('occupancy',{}).get(semantic_id,{}))
        occupants=occupancy.get('occupants',[]);waiters=occupancy.get('waiters',[])
        others=[row for row in occupants if (row.get('actor_id'),row.get('actor_instance_id'))!=(actor.get('actor_id'),actor.get('actor_instance_id'))]
        available=len(others)<item['capacity']
        if not available:
            if item['kind']=='queue' and len(waiters)<occupancy.get('outside_capacity',0):warnings.append('queue_full_bounded_outside_wait_available')
            else:errors.append({'code':'RESOURCE_BUSY','blockers':[r.get('actor_id') for r in others]})
        if item['evidence']['status'] not in {'calibrated','verified'}:warnings.append('interaction_execution_evidence_unverified')
        if snapshot.get('navmesh_available') is not True:errors.append({'code':'NAVMESH_UNAVAILABLE'})
        paths=snapshot.get('path_checks',{}).get(semantic_id)
        if paths is False:errors.append({'code':'TARGET_UNREACHABLE'})
        elif paths is not True:warnings.append('path_reachability_unchecked')
        approaches=item['approach_points_m'];position=actor.get('position_m')
        distance=min((math.dist(position[:2],p[:2]) for p in approaches),default=None) if position is not None else None
        return {'valid':not errors,'target':item,'action':action,'actor_id':actor.get('actor_id'),
            'occupancy':occupancy,'errors':errors,'warnings':warnings,'at_approach':distance is not None and distance<=.3,
            'approach_distance_m':distance,'snapshot_sim_time':snapshot.get('sim_time'),
            'reservation_acquired':False,'execution_completed':False,'advisory':True,
            'limits':['preflight does not acquire a slot or future corridor; execution rechecks occupancy',
                'geometric proximity and a configured anchor do not certify hand contact, grasping or force']}
