"""Isaac 6.2 / Behavior 110.4 adapter; constructed on the Kit main thread."""
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import carb
import carb.eventdispatcher
import omni.anim.behavior.core as bh
import omni.anim.navigation.core as nav
import omni.kit.commands
import omni.timeline
import omni.usd
from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel, UsdShade
from simpeople.core.errors import SimPeopleError
from simpeople.core.asset_paths import resolve_asset_path
from simpeople.core.quality_catalog import QualityCatalog,hash_tree,tree_stamp,template_hash

class NativeBackend:
    def __init__(self,root,semantics,allow_unverified=False,config_dir=None,capability_file=None,namespace='/World/SimPeople'):
        self.owner_thread=threading.get_ident()
        self.root=Path(root);self.stage=omni.usd.get_context().get_stage()
        self.namespace=namespace
        self.api=bh.acquire_interface();self.nav=nav.acquire_interface()
        self.timeline=omni.timeline.get_timeline_interface();self.semantics=semantics
        self.mpu=UsdGeom.GetStageMetersPerUnit(self.stage);self.up=UsdGeom.GetStageUpAxis(self.stage)
        layer=self.stage.GetRootLayer();meta=layer.customLayerData
        self.scene_id=meta.get('simpeople_scene_id',layer.identifier)
        self.scene_revision=meta.get('simpeople_scene_revision')
        self.config_dir=Path(config_dir) if config_dir else self.root/'configs'
        self.allow_unverified=allow_unverified;self.instances={};self.recorder=None;self.observations={};self.deferred_stops=set()
        behavior_file=getattr(bh,'__file__',None)
        actual_install=next((p for p in Path(behavior_file).parents if (p/'VERSION').is_file() and (p/'python.sh').is_file()),None) if behavior_file else None
        version_file=(actual_install or Path(os.environ.get('ISAAC_PATH','')))/'VERSION'
        def extension_revision(module,name):
            file=getattr(module,'__file__',None)
            return next((p.name for p in Path(file).parents if p.name.startswith(name+'-')),None) if file else None
        self.runtime_revision={'isaac_version':version_file.read_text().strip() if version_file.is_file() else None,
            'behavior_extension':extension_revision(bh,'omni.anim.behavior.core'),
            'navigation_extension':extension_revision(nav,'omni.anim.navigation.core')}
        self.task_errors={};self.on_event=None
        self.quality_sampling=False
        self.performance_optimized=True
        self.observation_frame_id=None;self.observation_frame_ids={}
        self.observation_counters={'queries':0,'cache_hits':0,'sdk_samples':0,'joint_index_queries':0}
        self.task_subscription=carb.eventdispatcher.get_eventdispatcher().observe_event(
            observer_name='SimPeople native task evidence',event_name=bh.GLOBAL_EVENT_BEHAVIOR_TASK_ENDED,
            on_event=self.task_ended)
        self.assets=[{'asset_id':'default','base_identity_id':'behavior_default',
            'appearance_id':'default','source_uri':str(self.root/'assets/cache/behavior/Characters/Human/Default.usd'),
            'rig_id':'Human','backend_support':['native'],'verified_actions':[],
            'radius_m':0.35,'height_m':1.82,'motion_library':str(self.root/'assets/cache/behavior/MotionLibrary/Human/HumanMotionLibrary.usd'),
            'license_note':'NVIDIA Behavior sample; local cache only. See source manifest.',
            'dependency_status':'cached'}]
        extra=(Path(config_dir) if config_dir else self.root/'configs')/'assets.json'
        if extra.exists():self.assets.extend(json.loads(extra.read_text())['assets'])
        for asset in self.assets:
            for field in ['source_uri','motion_library']:
                asset[field]=resolve_asset_path(asset[field],self.root)
            path=Path(asset['source_uri'])
            expected=asset.get('content_hash')
            asset['content_hash']=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            if expected and expected!=asset['content_hash']:
                asset.update(verified_actions=[],appearance_status='discovered',verification_status='source_changed',expected_content_hash=expected)
            asset['runtime_available']=path.is_file() and Path(asset['motion_library']).is_file()
            if not asset['runtime_available']:asset['verified_actions']=[]
        self.capabilities={a:{'status':'discovered'} for a in ['walk','run','wait','look_at','sit','leave_seat','follow']}
        cap=Path(capability_file) if capability_file else self.root/'reports/capability_matrix.json'
        if cap.exists():
            matrix=json.loads(cap.read_text())
            if matrix.get('actor_asset_sha256') in {None,self.assets[0]['content_hash']}:
                self.capabilities.update(matrix.get('actions',{}))
            else:self.assets[0]['verification_status']='source_changed'
        self.assets[0]['verified_actions']=[k for k,v in self.capabilities.items() if v['status']=='verified']
        for asset in self.assets:asset['quality_runtime_revision']=self.runtime_revision
        quality_file=(Path(config_dir) if config_dir else self.root/'configs')/'quality_catalog.json'
        self.quality_catalog=QualityCatalog(json.loads(quality_file.read_text()) if quality_file.exists() else None)
        self.quality_catalog_available=quality_file.exists();self.quality_revision_cache={}
        self.refresh_quality_revisions()

    def refresh_quality_revisions(self):
        if not self.quality_catalog_available:return
        checked={}
        def revision(directory):
            key=str(directory)
            if key in checked:return checked[key]
            stamp=tree_stamp(directory);old=self.quality_revision_cache.get(key)
            if old is None or old[0]!=stamp:self.quality_revision_cache[key]=(stamp,hash_tree(directory))
            checked[key]=self.quality_revision_cache[key][1];return checked[key]
        for asset in self.assets:
            asset['quality_revision_sha256']=revision(Path(asset['source_uri']).parent) if Path(asset['source_uri']).is_file() else None
            asset['motion_revision_sha256']=revision(Path(asset['motion_library']).parent) if Path(asset['motion_library']).is_file() else None
            asset['locomotion_quality']=self.quality_catalog.query(asset['quality_revision_sha256'],asset['motion_revision_sha256'],asset['rig_id'],'locomotion',runtime_revision=self.runtime_revision)

    def assert_thread(self):
        if threading.get_ident()!=self.owner_thread:raise RuntimeError('Kit access outside main thread')

    def task_ended(self,event):
        info={k:str(event[k]) for k in ['agent','task_id','task_status','task_error','task_elapsed_time']}
        try:info['task_error_name']=str(bh.BehaviorTaskError(int(event['task_error'])))
        except (ValueError,TypeError,AttributeError):pass
        self.task_errors[(str(event['agent']),int(event['task_id']))]=info
        if self.on_event:self.on_event('native_task_ended',**info)

    def task_error(self,handle,tid):return self.task_errors.get((handle,tid))
    def close(self):self.task_subscription=None;self.on_event=None
    def seat_egress(self,seat,handle):
        config=self.semantics[seat]
        candidates=config.get('egress_targets',[config.get('egress')])
        return self.choose_free_target(candidates,handle)

    def can_release_seat_here(self,handle,seat,obs):
        """A cancelled approach may already be outside every egress point.

        A seat lease starts before the approach, not when the body sits down.
        Do not send a stopped, standing actor back across the scene to release
        a chair it never reached. Retain normal egress for the interaction area.
        """
        if not self.is_standing(handle,obs) or obs['speed_mps']>=.15:return False
        config=self.semantics[seat]
        targets=config.get('egress_targets',[config.get('egress')])
        points=[self.resolve_target(t) for t in targets if t is not None]
        if not points:return False
        center=self.resolve_target(seat)
        radius=max(math.dist(center[:2],p[:2]) for p in points)
        return math.dist(center[:2],obs['position_m'][:2])>radius+.3

    def choose_free_target(self,candidates,handle):
        for candidate in candidates:
            if candidate is None:return None
            goal=self.resolve_target(candidate)
            occupied=False
            for other in self.instances:
                if other==handle:continue
                agent=self.api.get_agent(other)
                if agent:
                    p=agent.get_world_translation();pos=self.to_public([p.x,p.y,p.z])
                    if math.dist(goal[:2],pos[:2])<.9:occupied=True;break
            if not occupied:return candidate
        raise SimPeopleError('RESOURCE_BUSY','all egress points are occupied')

    def queue_slots(self,queue):return self.semantics[queue]['slots_m']
    def queue_egress(self,queue,handle):return self.choose_free_target(self.semantics[queue]['egress_targets'],handle)

    def move_prop(self,prop_id,position):
        self.assert_thread();config=self.semantics.get(prop_id,{})
        if config.get('kind')!='obstacle':raise SimPeopleError('TARGET_INVALID','prop is not a registered movable obstacle')
        size=config.get('size_m',[1,1,1])
        for handle in self.instances:
            obs=self.observe(handle)
            if not obs.get('ready'):continue
            p=obs['position_m'];distance=math.hypot(max(abs(p[0]-position[0])-size[0]/2,0),max(abs(p[1]-position[1])-size[1]/2,0))
            if distance<.35 and p[2]<position[2]+size[2]/2 and p[2]+1.8>position[2]-size[2]/2:
                raise SimPeopleError('RESOURCE_BUSY','requested prop pose overlaps a managed person',actor_path=handle)
        prim=self.stage.GetPrimAtPath(config['prim_path'])
        UsdGeom.Xformable(prim).GetOrderedXformOps()[0].Set(Gf.Vec3d(*self.to_stage(position)))
        return {'prop_id':prop_id,'position_m':position,'status':'succeeded'}

    def to_stage(self,p):
        q=[v/self.mpu for v in p]
        return q if self.up=='Z' else [q[0],q[2],-q[1]]

    def to_public(self,p):
        q=[float(p[i])*self.mpu for i in range(3)]
        return q if self.up=='Z' else [q[0],-q[2],q[1]]

    def resolve_path(self,target):
        if isinstance(target,str):
            path=self.semantics.get(target,{}).get('prim_path',target)
            if not path.startswith('/') or not self.stage.GetPrimAtPath(path):
                raise SimPeopleError('TARGET_INVALID','target prim not found',target=target)
            return path
        raise SimPeopleError('TARGET_INVALID','this action requires a semantic object or prim path')

    def resolve_target(self,target):
        if isinstance(target,list):return target
        path=self.resolve_path(target)
        p=UsdGeom.XformCache().GetLocalToWorldTransform(self.stage.GetPrimAtPath(path)).ExtractTranslation()
        return self.to_public(p)

    def list_assets(self):
        self.refresh_quality_revisions();return self.assets

    def list_actions(self,handle,include_quality=True):
        asset=next(a for a in self.assets if a['asset_id']==self.instances[handle]['asset_id'])
        actions={k:(v if asset['asset_id']=='default' or k in asset.get('verified_actions',[]) else {'status':'discovered'})
                 for k,v in self.capabilities.items()}
        if include_quality and self.quality_catalog_available:
            from .seat_geometry import seat_geometry_hash
            actions['sit']={**actions['sit'],'seat_quality':{name:self.quality_catalog.query(
                asset.get('quality_revision_sha256'),asset.get('motion_revision_sha256'),asset['rig_id'],'seat',
                template_hash(seat['seat_profile']),seat_geometry_hash(self.stage,seat),runtime_revision=self.runtime_revision)
                for name,seat in self.semantics.items() if seat.get('kind')=='seat' and seat.get('seat_profile')}}
        from .custom_actions import describe
        return {**actions,'queue':{'status':actions['walk']['status'],'implementation':'FIFO supervisor + verified walk'},
                'custom_action':describe(self,handle)}

    def inspect_scene(self):
        return {'backend':'native','meters_per_unit':self.mpu,'stage_up_axis':self.up,
            'scene_id':self.scene_id,'scene_revision':self.scene_revision,
            'recording':{'available':self.recorder is not None,'camera_view':self.recorder.camera_mode if self.recorder else None,
                         'focus_actor_id':self.recorder.focus_actor_id if self.recorder else None},
            'frame_spec':{'up_axis':'Z','units':'metres','handedness':'right'},
            'time_codes_per_second':self.stage.GetTimeCodesPerSecond(),
            'navmesh_available':self.nav.get_navmesh() is not None,'locations':self.semantics,
            'skelroots':[{'prim_path':str(p.GetPath()),'managed':str(p.GetPath()) in self.instances,
                          'behavior_configured':'BehaviorAgentAPI' in p.GetAppliedSchemas()}
                         for p in self.stage.Traverse() if p.IsA(UsdSkel.Root)]}

    def spawn(self,aid,asset_id,anchor):
        self.assert_thread()
        asset=next((a for a in self.assets if a['asset_id']==asset_id),None)
        if not asset:raise SimPeopleError('ASSET_INCOMPATIBLE','unknown asset_id',asset_id=asset_id)
        source=asset['source_uri']; motion=asset['motion_library']
        if not Path(source).is_file() or not Path(motion).is_file():
            raise SimPeopleError('ASSET_INCOMPATIBLE','cache missing; run scripts/cache_assets.py')
        position=self.resolve_target(anchor)
        for handle,instance in self.instances.items():
            observed=self.observe(handle)
            occupied=observed.get('position_m') if observed.get('ready') else instance.get('spawn_position_m')
            if occupied and math.dist(position[:2],occupied[:2])<.9:
                raise SimPeopleError('RESOURCE_BUSY','spawn anchor is occupied',actor_path=handle)
        parent=f'{self.namespace}/Actors/{aid}'
        container=UsdGeom.Xform.Define(self.stage,parent)
        container.AddTranslateOp().Set(Gf.Vec3d(*self.to_stage(position)))
        model=UsdGeom.Xform.Define(self.stage,parent+'/Character').GetPrim()
        model.GetReferences().AddReference(source)
        source_stage=Usd.Stage.Open(source)
        scale=UsdGeom.GetStageMetersPerUnit(source_stage)/self.mpu
        matrix=Gf.Matrix4d().SetScale(scale)
        source_up=UsdGeom.GetStageUpAxis(source_stage)
        if source_up!=self.up:matrix=matrix*Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1,0,0),90 if source_up=='Y' else -90))
        UsdGeom.Xformable(model).MakeMatrixXform().Set(matrix)
        overrides=0
        if asset.get('appearance_tint'):
            for prim in Usd.PrimRange(model):
                name=str(prim.GetPath()).lower()
                if not prim.IsA(UsdShade.Shader) or not any(k in name for k in ['fabric','cloth','shirt','pant','jacket','suit','vest','uniform','scrub']):continue
                if any(k in name for k in ['skin','hair','organic','eye','teeth']):continue
                mdl=prim.GetAttribute('info:mdl:sourceAsset').Get()
                if not mdl:continue
                parameter='diffuse_reflection_color' if mdl.path.endswith('OmniSurface.mdl') else 'diffuse_tint' if mdl.path.endswith('OmniPBR.mdl') else None
                if parameter:
                    UsdShade.Shader(prim).CreateInput(parameter,Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*asset['appearance_tint']))
                    if parameter=='diffuse_reflection_color':
                        UsdShade.Shader(prim).GetInput('diffuse_reflection_color_image').Set(Sdf.AssetPath(''))
                    overrides+=1
            if not overrides:
                self.stage.RemovePrim(parent)
                raise SimPeopleError('ASSET_INCOMPATIBLE','appearance has no supported apparel shader')
        skel=next((p for p in Usd.PrimRange(model) if p.IsA(UsdSkel.Root)),None)
        if not skel:
            self.stage.RemovePrim(parent);raise SimPeopleError('ASSET_INCOMPATIBLE','asset lacks SkelRoot')
        library=f'{self.namespace}/HumanMotionLibrary'
        if not self.stage.GetPrimAtPath(library):
            self.stage.DefinePrim(library).GetReferences().AddReference(motion)
        ok,_=omni.kit.commands.execute('ApplyBehaviorAgentAPICommand',
            skelroot_prim_paths=[skel.GetPath()],motion_library_prim_path=Sdf.Path(library),motion_library_skeleton_rig='Human')
        if not ok:
            self.stage.RemovePrim(parent);raise SimPeopleError('ASSET_INCOMPATIBLE','Behavior API application failed')
        handle=str(skel.GetPath());self.instances[handle]={'parent':parent,'asset_id':asset_id,
            'spawn_position_m':position,
            'base_identity_id':asset['base_identity_id'],'appearance_id':asset['appearance_id'],
            'appearance_overrides_applied':overrides}
        return handle

    def agent(self,handle):
        self.assert_thread()
        a=self.api.get_agent(handle)
        if a is None:raise SimPeopleError('SIM_NOT_READY','Behavior agent is not available; NavMesh and Play required')
        return a

    def despawn(self,handle):
        self.assert_thread();self.stage.RemovePrim(self.instances.pop(handle)['parent'])
        self.observations.pop(handle,None)

    def validate(self,handle,step):
        action=step['action'];cap=step.get('gait','walk') if action=='move_to' else ('walk' if action=='queue' else action)
        state=self.list_actions(handle,include_quality=False).get(cap,{'status':'unsupported'})
        if action=='custom_action':
            state=state.get('clips',{}).get(step['target'],{'status':'unsupported'}) if isinstance(step['target'],str) else {'status':'unsupported'}
        if state['status']=='unsupported' or (state['status']!='verified' and not self.allow_unverified):
            raise SimPeopleError('ACTION_UNSUPPORTED','action is not verified for this backend',action=cap,capability=state)
        if action=='custom_action':return
        if 'target' in step:
            self.resolve_target(step['target'])
            for point in step.get('via',[]):self.resolve_target(point)
            if action in {'sit','follow','queue'}:self.resolve_path(step['target'])
        if action=='sit' and self.semantics.get(step['target'],{}).get('kind')!='seat':
            raise SimPeopleError('TARGET_INVALID','sit requires a calibrated seat in scene semantics')
        if action=='queue' and self.semantics.get(step['target'],{}).get('kind')!='queue':
            raise SimPeopleError('TARGET_INVALID','queue requires registered slots')

    def start(self,handle,step):
        a=self.agent(handle);action=step['action']
        if action=='move_to':
            goal=self.to_stage(self.resolve_target(step['target']))
            navmesh=self.nav.get_navmesh()
            actual=a.get_world_translation()
            profile=nav.NavAgentDesc(radius=max(a.get_radius(),.4/self.mpu),height=a.get_height(),collision_gap=.05/self.mpu)
            points=[]
            for waypoint in [*step.get('via',[]),step['target']]:
                endpoint=self.to_stage(self.resolve_target(waypoint))
                path=navmesh.query_shortest_path(start_pos=actual,end_pos=carb.Float3(*endpoint),agent=profile) if navmesh else None
                segment=list(path.get_points()) if path else []
                if not segment or math.dist(self.to_public(segment[-1]),self.resolve_target(waypoint))>step.get('tolerance_m',0.3):
                    raise SimPeopleError('TARGET_UNREACHABLE','target lies outside reachable NavMesh',waypoint=waypoint)
                for point in segment:
                    point=tuple(point)
                    if not points or math.dist(points[-1],point)>1e-4:points.append(point)
                actual=carb.Float3(*segment[-1])
            a.set_speed(step.get('speed_mps',2.8 if step.get('gait')=='run' else 1.2)/self.mpu)
            if step.get('via'):
                waypoints=[self.to_stage(self.resolve_target(p)) for p in [*step['via'],step['target']]]
                if self.on_event:self.on_event('native_route_planned',agent=handle,waypoints_stage=waypoints,navmesh_point_count=len(points))
                tid=a.move_along(target=[carb.Float3(*p) for p in waypoints])
            else:
                reachable=points[-1]
                if math.dist(goal,reachable)*self.mpu>.02 and self.on_event:
                    self.on_event('native_goal_projected',agent=handle,requested_m=self.resolve_target(step['target']),
                                  reachable_m=self.to_public(reachable),tolerance_m=step.get('tolerance_m',.3))
                tid=a.move_to(target=tuple(reachable))
        elif action=='wait':
            current=a.get_action_task_id()
            tid=current if a.get_task_name(current)=='Sit' else a.idle()
        elif action=='look_at':tid=a.idle(facing=self.resolve_path(step['target']))
        elif action=='sit':tid=a.sit(target=self.resolve_path(step['target']))
        elif action in {'leave_seat','settle'}:tid=a.idle()
        elif action=='follow':
            a.set_speed(1.2/self.mpu)
            tid=a.follow(target=self.resolve_path(step['target']),distance=step.get('distance_m',2.0)/self.mpu)
        elif action=='custom_action':
            if step['target'] not in list(a.get_custom_action_names()):
                raise SimPeopleError('ACTION_UNSUPPORTED','clip absent from native agent',clip=step['target'])
            tid=a.custom_action(step['target'],duration=step['duration_s'])
        else:raise SimPeopleError('ACTION_UNSUPPORTED',action)
        if tid==bh.BEHAVIOR_TASK_ID_INVALID:
            raise SimPeopleError('BACKEND_TASK_FAILED','native task rejected',action=action,target=step.get('target'),
                                position_m=self.to_public(a.get_world_translation()))
        return tid

    def stop(self,handle):
        a=self.api.get_agent(handle)
        if a:
            # idle is a native transition, including stand-up from Sit.
            a.idle()
        elif self.timeline.is_stopped() is False:
            self.deferred_stops.add(handle)

    def task_state(self,handle,tid):
        state=self.agent(handle).get_task_status(tid)
        return {bh.BehaviorTaskStatus.RUNNING:'running',bh.BehaviorTaskStatus.SUCCEEDED:'succeeded',
                bh.BehaviorTaskStatus.FAILED:'failed'}[state]

    def observe(self,handle):
        self.assert_thread()
        self.observation_counters['queries']+=1
        sim_time=self.timeline.get_current_time()
        previous=self.observations.get(handle)
        same_frame=self.observation_frame_ids.get(handle)==self.observation_frame_id
        if not self.timeline.is_playing() and previous and not self.quality_sampling:
            return {**previous[1],'sim_paused':True,'observation_sim_time':previous[0]}
        if self.performance_optimized and previous and same_frame and abs(previous[0]-sim_time)<1e-9 and handle not in self.deferred_stops:
            self.observation_counters['cache_hits']+=1
            return previous[1]
        a=self.api.get_agent(handle)
        if not a:return {'ready':False,'position_m':None,'speed_mps':0}
        if not self.instances[handle].get('avoidance_configured'):
            a.set_auto_avoidance_enabled(True);a.set_obstacle_avoidance_enabled(True)
            self.instances[handle]['avoidance_configured']=True
            asset=next(v for v in self.assets if v['asset_id']==self.instances[handle]['asset_id'])
            asset['runtime_height_m']=a.get_height()*self.mpu;asset['runtime_radius_m']=a.get_radius()*self.mpu
            if asset.get('height_m') is None:asset['height_m']=asset['runtime_height_m']
        if handle in self.deferred_stops:
            a.idle();self.deferred_stops.discard(handle)
        if previous and same_frame and abs(previous[0]-sim_time)<1e-9:return previous[1]
        p=a.get_world_translation();v=a.get_linear_velocity();q=a.get_world_rotation();f=a.get_facing_direction()
        position=self.to_public([p.x,p.y,p.z]);velocity=[0.0,0.0,0.0]
        if previous and sim_time>previous[0]+1e-9:
            velocity=[(position[i]-previous[1]['position_m'][i])/(sim_time-previous[0]) for i in range(3)]
        joints={};joint_rotations={}
        tags=['Hips','LeftFoot','RightFoot','LeftToeBase','RightToeBase','LeftLeg','RightLeg']
        if self.quality_sampling:tags+=['Spine1','Spine2','Chest','Neck1','Neck2','Head','LeftShoulder','RightShoulder']
        indices=self.instances[handle].setdefault('joint_indices',{})
        if self.quality_sampling and 'skeleton_joint_names' not in self.instances[handle]:
            skeleton=next((UsdSkel.Skeleton(p) for p in Usd.PrimRange(self.stage.GetPrimAtPath(handle)) if p.IsA(UsdSkel.Skeleton)),None)
            if skeleton:self.instances[handle]['skeleton_joint_names']=list(skeleton.GetJointsAttr().Get())
        for tag in tags:
            if not self.performance_optimized or indices.get(tag,-1)<0:
                indices[tag]=a.get_joint_index(tag);self.observation_counters['joint_index_queries']+=1
                if indices[tag]<0 and self.quality_sampling:
                    names=self.instances[handle].get('skeleton_joint_names',[])
                    head=next((i for i,n in enumerate(names) if n.rsplit('/',1)[-1].rsplit(':',1)[-1]=='Head'),None)
                    if head is not None and a.get_joint_index('Head')==head:
                        aliases={'Neck1':{'Neck1','NeckTwist01','Neck'},'Neck2':{'Neck2','NeckTwist02'}}.get(tag,{tag})
                        indices[tag]=next((i for i,n in enumerate(names) if n.rsplit('/',1)[-1].rsplit(':',1)[-1] in aliases),-1)
            index=indices[tag]
            if index<0:continue
            jp=carb.Float3(0,0,0);jq=carb.Float4(0,0,0,1)
            if a.get_joint_world_transform(index,jp,jq):
                joints[tag]=self.to_public([jp.x,jp.y,jp.z])
                if self.quality_sampling:joint_rotations[tag]=[jq.x,jq.y,jq.z,jq.w]
        tid=a.get_action_task_id()
        result={'ready':True,'position_m':position,
            'orientation_xyzw_stage':[q.x,q.y,q.z,q.w],
            'facing_direction':self.to_public([f.x/self.mpu,f.y/self.mpu,f.z/self.mpu]),
            'velocity_mps':velocity,'native_reported_velocity_mps':self.to_public([v.x,v.y,v.z]),
            'velocity_source':'finite_difference_of_actual_runtime_position',
            'speed_mps':math.sqrt(sum(x*x for x in velocity)),
            'planar_speed_mps':math.hypot(*velocity[:2]),
            'action':a.get_task_name(tid),'native_task_id':tid,'joints_m':joints,
            'target_object':a.get_target_object(),
            'position_source':'BehaviorAgent.get_world_translation','observation_sim_time':sim_time,
            'asset_id':self.instances[handle]['asset_id']}
        if self.quality_sampling:
            result['joint_rotations_xyzw_stage']=joint_rotations
            result['quality_joint_indices']=dict(indices)
            result['native_speed_raw']=a.get_speed()
            result['sample_frame_id']=self.observation_frame_id
            result['sim_paused']=not self.timeline.is_playing()
            result['root_changed_without_sim_time']=bool(previous and abs(previous[0]-sim_time)<1e-9 and math.dist(position,previous[1]['position_m'])>1e-5)
            seats=[(name,seat) for name,seat in self.semantics.items() if seat.get('kind')=='seat' and seat.get('seat_profile')]
            for name,seat in seats:
                from simpeople.core.seats import SeatProfile
                profile=SeatProfile(**seat['seat_profile'])
                if math.dist(position[:2],profile.position_m[:2])>1.8:continue
                result.setdefault('seat_quality',{})[name]={'proxy_clearance_m':profile.proxy_clearances(joints)}
                focused=bool(self.recorder and self.recorder.focus_actor_id==self.instances[handle]['parent'].rsplit('/',1)[-1])
                if self.observation_frame_id is not None and (self.observation_frame_id%3==0 or focused):
                    from .body_geometry import HeadNeckGeometry
                    geometry=self.instances[handle].get('head_neck_geometry')
                    if geometry is None:
                        geometry=HeadNeckGeometry(self.stage,handle);self.instances[handle]['head_neck_geometry']=geometry
                    result['seat_quality'][name]['skinned_vertices']=geometry.evaluate(a,profile,self.mpu)
        self.observation_counters['sdk_samples']+=1
        result.update({k:self.instances[handle][k] for k in ['base_identity_id','appearance_id','appearance_overrides_applied']})
        self.observations[handle]=(sim_time,result)
        self.observation_frame_ids[handle]=self.observation_frame_id
        return result

    def seat_entry_ready(self,handle,target,obs):
        # A broad holding tolerance can also match an intermediate sit-entry
        # pose. Do not start the hold clock until the actual hip effector fits.
        hips=obs.get('joints_m',{}).get('Hips');seat=self.semantics[target]
        return bool(hips and math.dist(hips,self.resolve_target(seat['hips_prim_path']))<=seat.get('hips_entry_tolerance_m',.04))

    def is_seated(self,handle,target,obs):
        seat=self.semantics[target];hips=obs.get('joints_m',{}).get('Hips')
        expected=self.resolve_target(seat['hips_prim_path'])
        feet=[obs.get('joints_m',{}).get(k) for k in ['LeftFoot','RightFoot']]
        facing=obs.get('facing_direction',[0,0,0]);desired=seat['facing_direction']
        return bool(hips and math.dist(hips,expected)<=seat.get('hips_tolerance_m',0.18)
                    and all(p and -.02<p[2]<.25 for p in feet)
                    and sum(facing[i]*desired[i] for i in range(3))>math.cos(math.radians(20))
                    and obs.get('planar_speed_mps',obs['speed_mps'])<0.15 and obs['action']=='Sit')

    def is_standing(self,handle,obs):
        hips=obs.get('joints_m',{}).get('Hips');root=obs['position_m']
        return bool(hips and hips[2]-root[2]>0.75 and obs['action'] in {'Idle',''})

    def pause(self):self.timeline.pause()
    def resume(self):self.timeline.play()
    def record(self,p):
        if not self.recorder:raise SimPeopleError('RECORDING_UNAVAILABLE','renderer recording was not configured')
        return self.recorder.control(p)
