"""Read explicitly registered interaction geometry on the Kit main thread."""
import hashlib
import json
from pxr import Usd,UsdGeom
from simpeople.core.scene_semantics import KINDS,DEFAULT_ACTIONS


def snapshot_targets(backend,semantic_id=None):
    backend.assert_thread();stage=backend.stage
    time=Usd.TimeCode(backend.timeline.get_current_time()*stage.GetTimeCodesPerSecond())
    transforms=UsdGeom.XformCache(time);boxes=UsdGeom.BBoxCache(time,[UsdGeom.Tokens.default_])
    locations=backend.semantics
    config=backend.config_dir/'interaction_targets.json'
    overlays=json.loads(config.read_text()).get('targets',[]) if config.exists() else []
    declared={name:dict(row) for name,row in locations.items() if row.get('kind') in KINDS}
    for row in overlays:
        name=row['semantic_id']
        if name in locations and name not in declared and not any(d.get('prim_path')==row.get('prim_path') for d in declared.values()):declared[name]=dict(row)

    def point(value):
        if isinstance(value,(list,tuple)):return list(value)
        path=locations.get(value,{}).get('prim_path',value);prim=stage.GetPrimAtPath(path)
        if not prim:raise ValueError('interaction anchor is missing: '+str(value))
        return backend.to_public(transforms.GetLocalToWorldTransform(prim).ExtractTranslation())

    result=[]
    for name,data in sorted(declared.items()):
        if semantic_id is not None and name!=semantic_id:continue
        prim=stage.GetPrimAtPath(data.get('prim_path',''))
        if not prim or not prim.IsActive():continue
        try:
            position=point(data['prim_path']);approach=data.get('approach')
            approaches=([point(approach)] if approach is not None else
                [list(data['slots_m'][0])] if data.get('slots_m') else [position] if data['kind']=='activity_bay' else [])
            exits=[point(x) for x in data.get('egress_targets',[data['egress']] if data.get('egress') else [])]
            anchors={}
            for tag,key in [('hips','hips_prim_path'),('palm_left','palm_left_prim_path'),('palm_right','palm_right_prim_path'),('look','look_prim_path')]:
                if data.get(key):anchors[tag]={'prim_path':data[key],'position_m':point(data[key])}
            bounds=boxes.ComputeWorldBound(prim).ComputeAlignedRange();bbox=None
            if not bounds.IsEmpty():
                lo,hi=bounds.GetMin(),bounds.GetMax()
                corners=[backend.to_public([x,y,z]) for x in [lo[0],hi[0]] for y in [lo[1],hi[1]] for z in [lo[2],hi[2]]]
                bbox={'min_m':[min(p[i] for p in corners) for i in range(3)],'max_m':[max(p[i] for p in corners) for i in range(3)]}
            authored={}
            for child in Usd.PrimRange(prim):
                # Behavior may add identity rotate/scale ops on first prop use.
                # Hash the evaluated transform, not a transform parameterization
                # that can change without changing the interaction geometry.
                attrs={str(a.GetName()):str(a.Get(time)) for a in child.GetAttributes() if str(a.GetName()) in {'points','faceVertexCounts','faceVertexIndices','extent'}}
                if child.IsA(UsdGeom.Xformable):
                    matrix=transforms.GetLocalToWorldTransform(child)
                    attrs['world_transform']=[[0.0 if float(v)==0 else float(v) for v in row] for row in matrix]
                if attrs:attrs['prim_type']=str(child.GetTypeName())
                if attrs:authored[str(child.GetPath())]=attrs
            geometry=hashlib.sha256(json.dumps(authored,sort_keys=True).encode()).hexdigest()
            result.append({'semantic_id':name,'kind':data['kind'],'prim_path':data['prim_path'],
                'position_m':position,'bounds_m':bbox,'approach_points_m':approaches,'exit_points_m':exits,
                'facing_direction':data.get('facing_direction'),'anchors':anchors,'capacity':data.get('capacity',1),
                'allowed_actions':data.get('allowed_actions',sorted(DEFAULT_ACTIONS[data['kind']])),
                'resource_id':data.get('resource_id',name),'clip':data.get('clip'),
                'clearance_radius_m':data.get('clearance_radius_m'),'geometry_sha256':geometry,
                'calibration_profile':data.get('seat_profile'),'source':'explicit USD semantics or local interaction_targets.json',
                'release_condition':('outside_all_slots_and_settled' if data['kind']=='queue' else
                    'native_stand_egress_and_settlement' if data['kind']=='seat' else 'step_end_or_fenced_cleanup'),
                'evidence':{'status':'discovered','reason':'geometry readback; actor-specific action/fit evidence is reported separately'}})
        except (ValueError,TypeError) as error:
            result.append({'semantic_id':name,'kind':data['kind'],'prim_path':data['prim_path'],'capacity':data.get('capacity',1),
                'evidence':{'status':'unavailable','reason':str(error)}})
    return result
