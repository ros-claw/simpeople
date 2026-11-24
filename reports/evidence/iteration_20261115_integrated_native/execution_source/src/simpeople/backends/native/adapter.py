"""Isaac 6.2 / Behavior 110.4 adapter; constructed on the Kit main thread."""
import hashlib
import json
import math
import os
from pathlib import Path
import threading
import uuid
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
        self.native_seed_configuration=None;self.native_seed_sealed=False
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
        gesture_file=self.config_dir/'native_gesture_catalog.json'
        self.gesture_catalog=QualityCatalog(json.loads(gesture_file.read_text()) if gesture_file.exists() else None)
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

    def configure_native_seed(self,seed):
        self.assert_thread()
        if isinstance(seed,bool) or not isinstance(seed,int) or not 0<=seed<2**32:
            raise SimPeopleError('INVALID_REQUEST','native seed must be an unsigned 32-bit integer')
        if self.native_seed_sealed or self.instances or self.timeline.is_playing():
            raise SimPeopleError('POLICY_UNSUPPORTED','native seed must be configured before actors and Play')
        previous=self.native_seed_configuration
        if previous is not None:
            if previous['api_seed']!=seed:raise SimPeopleError('POLICY_UNSUPPORTED','native startup seed was already configured')
            return dict(previous)
        self.api.set_random_seed(seed)
        self.native_seed_configuration={'api_seed':seed,'configured_before_agents':True,'configured_on_owner_thread':True}
        return dict(self.native_seed_configuration)

    def canonical_startup_quality(self,reference):
        self.assert_thread()
        domain=reference.get('native_startup_conditions')
        if domain is None:return None  # Legacy clips without a declared generated domain retain their contract.
        import carb.settings
        from simpeople.motion.startup import startup_error
        settings=carb.settings.get_settings();prefix='/exts/omni.anim.behavior.core/'
        actual={'idle_tags':settings.get(prefix+'idleAnimationTags'),
                'response_time_s':settings.get(prefix+'agentResponseTime'),
                'response_random_offset_s':settings.get(prefix+'agentResponseTimeMaxRandomOffset'),
                'nav_blocked_timeout_s':settings.get(prefix+'navBlockedTimeout'),
                'seed_configuration':self.native_seed_configuration}
        quality=startup_error(actual,domain)
        if not quality['passed']:
            raise SimPeopleError('MOTION_ENTRY_NOT_READY','native startup is outside this preloaded canonical domain',startup_error=quality)
        return quality

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

    def actor_label(self,handle):
        instance=self.instances.get(handle)
        return (instance.get('actor_id') or instance['parent'].rsplit('/',1)[-1]) if instance else handle

    def choose_free_target(self,candidates,handle):
        blockers=set()
        for candidate in candidates:
            if candidate is None:return None
            goal=self.resolve_target(candidate)
            occupied=False
            for other in self.instances:
                if other==handle:continue
                agent=self.api.get_agent(other)
                if agent:
                    p=agent.get_world_translation();pos=self.to_public([p.x,p.y,p.z])
                    if math.dist(goal[:2],pos[:2])<.9:
                        blockers.add(self.actor_label(other));occupied=True;break
            if not occupied:return candidate
        raise SimPeopleError('RESOURCE_BUSY','all egress points are occupied',blocker_ids=sorted(blockers),candidate_targets=candidates)

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
        actions['look_at']={**actions['look_at'],'precision_profile':{'status':'discovered' if getattr(self,'precise_facing_probe_enabled',False) else 'unsupported','optional_field':'max_angle_deg','target_kind':'fixed_world_point','range_deg':[.1,2],'max_sim_seconds':8,'max_sdk_commands':16,'scope':'Experimental only, not Native qualified or enabled by default'}}
        from .custom_actions import describe
        from .gestures import profile
        actions.update({name:profile(self,handle,name) for name in ['head_look','reach_hand']})
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

    def interaction_targets(self,semantic_id=None):
        from .interactions import snapshot_targets
        return snapshot_targets(self,semantic_id)

    def interaction_path_reachable(self,handle,target):
        self.assert_thread();agent=self.agent(handle);mesh=self.nav.get_navmesh()
        if mesh is None:return False
        profile=nav.NavAgentDesc(radius=max(agent.get_radius(),.45/self.mpu),height=agent.get_height(),collision_gap=.0)
        path=mesh.query_shortest_path(start_pos=agent.get_world_translation(),end_pos=carb.Float3(*self.to_stage(target)),agent=profile)
        points=list(path.get_points()) if path else []
        return bool(points and math.dist(self.to_public(points[-1]),target)<=.3)

    def spawn(self,aid,asset_id,anchor):
        self.assert_thread()
        self.native_seed_sealed=True
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
        # Behavior caches agents by their physical USD path. Reusing that path
        # during Play can retain the old agent/root even after logical reset.
        # Keep the public actor ID, but allocate a fresh physical incarnation.
        parent=f'{self.namespace}/Actors/{aid}/Instance_{uuid.uuid4().hex}'
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
        handle=str(skel.GetPath());self.instances[handle]={'parent':parent,'asset_id':asset_id,'actor_id':aid,
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
        self.assert_thread();instance=self.instances[handle]
        # USD deletion alone can leave the SDK's old agent enabled. Stop only
        # this explicitly despawned instance, and remove its native API while
        # its SkelRoot still exists. SDK session opinions are stronger than the
        # reference-owning root layer, so author removal there.
        agent=self.api.get_agent(handle)
        if agent:agent.set_enabled(False)
        with Usd.EditContext(self.stage,self.stage.GetSessionLayer()):
            ok,_=omni.kit.commands.execute('RemoveBehaviorAgentAPICommand',skelroot_prim_paths=[Sdf.Path(handle)],layer=self.stage.GetSessionLayer())
            if not ok:raise SimPeopleError('BACKEND_ERROR','native actor API removal failed',actor_id=instance.get('actor_id'))
            # Native session opinions can keep an orphan hierarchy composed
            # after removing its weaker reference. Retire this instance's whole
            # subtree, including any SDK-created physics, in the strongest layer.
            if not self.stage.GetPrimAtPath(instance['parent']).SetActive(False):
                raise SimPeopleError('BACKEND_ERROR','native actor subtree retirement failed',actor_id=instance.get('actor_id'))
        self.stage.RemovePrim(instance['parent']);self.instances.pop(handle)
        if instance.get('actor_id'):
            logical=instance['parent'].rsplit('/',1)[0];prim=self.stage.GetPrimAtPath(logical)
            if prim and not prim.GetChildren():self.stage.RemovePrim(logical)
        self.observations.pop(handle,None)
        self.observation_frame_ids.pop(handle,None);self.deferred_stops.discard(handle)

    def validate(self,handle,step):
        if step['action'] in {'head_look','reach_hand'}:
            from .gestures import validate
            validate(self,handle,step);return
        if 'max_angle_deg' in step and not getattr(self,'precise_facing_probe_enabled',False):
            raise SimPeopleError('ACTION_UNSUPPORTED','precise facing requires the explicit experimental runtime profile')
        if 'max_angle_deg' in step and not isinstance(step.get('target'),list):
            raise SimPeopleError('TARGET_INVALID','precise facing currently requires a fixed world coordinate point')
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
        if 'max_angle_deg' in step:
            observation=self.observe(handle);goal=self.resolve_target(step['target'])
            if not observation.get('ready') or math.dist(goal[:2],observation['position_m'][:2])<.05:
                raise SimPeopleError('TARGET_INVALID','precise facing requires a distinct horizontal target')
        if action=='sit' and self.semantics.get(step['target'],{}).get('kind')!='seat':
            raise SimPeopleError('TARGET_INVALID','sit requires a calibrated seat in scene semantics')
        if action=='queue' and self.semantics.get(step['target'],{}).get('kind')!='queue':
            raise SimPeopleError('TARGET_INVALID','queue requires registered slots')

    def canonical_entry_quality(self,handle,reference):
        self.canonical_startup_quality(reference)
        from simpeople.motion.entry import entry_error
        asset=next(v for v in self.assets if v['asset_id']==self.instances[handle]['asset_id'])
        if reference['source_asset_sha256']!=asset['content_hash']:raise SimPeopleError('MOTION_RIG_MISMATCH','canonical motion is for another source asset')
        skeleton=next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(self.stage.GetPrimAtPath(handle)) if p.IsA(UsdSkel.Skeleton))
        if list(map(str,skeleton.GetJointsAttr().Get()))!=reference['joint_paths']:raise SimPeopleError('MOTION_RIG_MISMATCH','canonical motion joint layout changed')
        agent=self.agent(handle);pose=[]
        for index in range(len(reference['joint_paths'])):
            point=carb.Float3(0,0,0);rotation=carb.Float4(0,0,0,1)
            if not agent.get_joint_world_transform(index,point,rotation):raise SimPeopleError('MOTION_ENTRY_NOT_READY','canonical entry readback unavailable')
            pose.append([*self.to_public(point),rotation.x,rotation.y,rotation.z,rotation.w])
        observation=self.observe(handle);quality=entry_error(pose,observation['facing_direction'],reference)
        if reference.get('native_entry_domain') is not None:
            from simpeople.motion.entry import heading_window_error
            domain=heading_window_error(self.instances[handle].get('canonical_heading_history',[]),observation,reference['native_entry_domain'])
            quality['native_entry_domain']=domain
            quality['passed']=quality['passed'] and domain['passed']
        if not quality['passed'] or observation['speed_mps']>=.15:raise SimPeopleError('MOTION_ENTRY_NOT_READY','actual pose is outside this preloaded canonical entry',entry_error=quality,speed_mps=observation['speed_mps'])
        return quality

    def prepare_immediate_motion_start(self,handle,step,previous):
        if step['action']!='custom_action':return False
        entry=getattr(self,'custom_actions',{}).get(step['target'],{});reference=entry.get('canonical_entry')
        if not reference:return False
        base=entry.get('entry_base_action');agent=self.agent(handle)
        if not base or not previous or previous['status']!='running' or previous.get('native_task_id')!=agent.get_action_task_id() or agent.get_task_name(agent.get_action_task_id())!=base:
            raise SimPeopleError('MOTION_ENTRY_NOT_READY','canonical clip requires its still-owned preloaded base task',required_base_action=base)
        self.canonical_entry_quality(handle,reference)
        if hasattr(self,'check_action_space'):self.check_action_space(handle,step)
        return True

    def action_admission_block(self,handle):
        from .custom_stop import ready
        if not ready(self,handle,require_window=True):
            record=self.instances[handle]['custom_stop']
            return {'reason':'cancelled_custom_still_settling','since_sim_time':record['requested_sim_time'],
                    'retired_native_task_id':record['retired_native_task_id']}
        return None


    def adopt_precision_idle(self,handle):
        """Transfer only an observed Idle previously issued by this body owner.

        No SDK command is issued here. Engine.start_native records the new
        logical binding to the existing native ID. External/default IDs and
        unresolved head/hand cleanup cannot be adopted.
        """
        self.assert_thread()
        instance=self.instances[handle]
        if instance.get('gesture'):return None
        agent=self.agent(handle);current=agent.get_action_task_id()
        known=instance.get('engine_native_ids',[])
        if current<=0 or current not in known or agent.get_task_name(current)!='Idle':return None
        if self.task_state(handle,current)!='running':return None
        observed=self.observe(handle);speed=observed.get('speed_mps')
        if (not observed.get('ready') or observed.get('native_task_id')!=current or observed.get('action')!='Idle'
            or observed.get('observation_sim_time')!=self.timeline.get_current_time()
            or isinstance(speed,bool) or not isinstance(speed,(int,float)) or not math.isfinite(speed) or not 0<=speed<.15):return None
        if self.on_event:self.on_event('native_idle_adopted_for_precision',agent=handle,native_task_id=current,
                                      observation_sim_time=observed['observation_sim_time'],issued_new_sdk_command=False)
        return current

    def start(self,handle,step):
        self.assert_thread()
        if 'max_angle_deg' in step and not getattr(self,'precise_facing_probe_enabled',False):
            raise SimPeopleError('ACTION_UNSUPPORTED','precise facing requires the explicit experimental runtime profile')
        from .custom_stop import ready
        if not ready(self,handle,require_window=True):
            raise SimPeopleError('MOTION_ENTRY_NOT_READY','cancelled custom action has not exited actual Native playback')
        self.instances[handle].pop('custom_stop',None)
        a=self.agent(handle);action=step['action']
        if action in {'head_look','reach_hand'}:
            from .gestures import start
            return start(self,handle,step)
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
        elif action=='look_at':
            adopted=self.adopt_precision_idle(handle) if 'max_angle_deg' in step and '_native_facing_direction' not in step else None
            if adopted is not None:tid=adopted
            elif '_native_facing_direction' in step:
                if not getattr(self,'precise_facing_probe_enabled',False) or a.get_action_task_id()!=step['_expected_native_task_id']:
                    raise SimPeopleError('BACKEND_TASK_FAILED','precise facing lost its native owner before command')
                direction=self.to_stage(step['_native_facing_direction']);length=math.sqrt(sum(v*v for v in direction))
                tid=a.idle(facing=carb.Float3(*[v/length for v in direction]))
            elif isinstance(step['target'],list):
                # Public numeric look_at is a world point, NOT an SDK direction.
                goal=self.resolve_target(step['target']);position=self.to_public(a.get_world_translation())
                delta=[goal[0]-position[0],goal[1]-position[1],0.]
                if math.hypot(*delta[:2])<.05:tid=a.idle()
                else:
                    direction=self.to_stage(delta);length=math.sqrt(sum(v*v for v in direction))
                    tid=a.idle(facing=carb.Float3(*[v/length for v in direction]))
            else:tid=a.idle(facing=self.resolve_path(step['target']))
        elif action=='sit':tid=a.sit(target=self.resolve_path(step['target']))
        elif action in {'leave_seat','settle'}:tid=a.idle()
        elif action=='follow':
            a.set_speed(1.2/self.mpu)
            tid=a.follow(target=self.resolve_path(step['target']),distance=step.get('distance_m',2.0)/self.mpu)
        elif action=='custom_action':
            if step['target'] not in list(a.get_custom_action_names()):
                raise SimPeopleError('ACTION_UNSUPPORTED','clip absent from native agent',clip=step['target'])
            reference=getattr(self,'custom_actions',{}).get(step['target'],{}).get('canonical_entry')
            if reference:
                quality=self.canonical_entry_quality(handle,reference)
                if self.on_event:self.on_event('motion_canonical_entry_verified',agent=handle,clip=step['target'],entry_error=quality)
            tid=a.custom_action(step['target'],duration=step['duration_s'])
        else:raise SimPeopleError('ACTION_UNSUPPORTED',action)
        if tid==bh.BEHAVIOR_TASK_ID_INVALID:
            raise SimPeopleError('BACKEND_TASK_FAILED','native task rejected',action=action,target=step.get('target'),
                                position_m=self.to_public(a.get_world_translation()))
        known=self.instances[handle].setdefault('engine_native_ids',[])
        if tid not in known:known.append(tid)
        del known[:-32]
        return tid

    def stop(self,handle):
        self.assert_thread()
        from .gestures import stop
        stop(self,handle)
        a=self.api.get_agent(handle)
        if a:
            current=a.get_action_task_id();name=a.get_task_name(current)
            entry=getattr(self,'custom_actions',{}).get(name,{})
            if entry.get('playback_mode')=='out_and_back':
                previous=self.instances[handle].get('custom_stop')
                if previous and previous['retired_native_task_id']==current:return
                record={'retired_native_task_id':current,'clip':name,
                        'requested_sim_time':self.timeline.get_current_time(),'actual_idle_times':[]}
                self.instances[handle]['custom_stop']=record
                a.cancel_task(current)
                record['idle_request_native_task_id']=int(a.idle())
                if self.on_event:self.on_event('native_custom_stop_requested',agent=handle,**record)
            else:
                # idle is a native transition, including stand-up from Sit.
                a.idle()
        elif self.timeline.is_stopped() is False:
            self.deferred_stops.add(handle)

    def task_state(self,handle,tid):
        state=self.agent(handle).get_task_status(tid)
        return {bh.BehaviorTaskStatus.RUNNING:'running',bh.BehaviorTaskStatus.SUCCEEDED:'succeeded',
                bh.BehaviorTaskStatus.FAILED:'failed'}[state]

    def gesture_status(self,handle,tid,step,obs):
        from .gestures import status
        return status(self,handle,tid,step,obs)

    def end_gesture(self,handle,tid):
        from .gestures import stop
        stop(self,handle,tid)

    def gesture_stop_settled(self,handle,obs):
        from .gestures import settled
        from .custom_stop import ready
        return ready(self,handle,obs) and settled(self,handle,obs)

    def tick_gestures(self):
        from .gestures import tick
        tick(self)

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
        sample_gesture=self.instances[handle].get('gesture_sampling',False)
        sample_joints=self.quality_sampling or sample_gesture
        if sample_joints:tags+=['Spine1','Spine2','Chest','Neck1','Neck2','Head','LeftShoulder','RightShoulder',
            'LeftArm','RightArm','LeftForeArm','RightForeArm','LeftHand','RightHand','LeftHandMiddle2','RightHandMiddle2']
        indices=self.instances[handle].setdefault('joint_indices',{})
        if sample_joints and 'skeleton_joint_names' not in self.instances[handle]:
            skeleton=next((UsdSkel.Skeleton(p) for p in Usd.PrimRange(self.stage.GetPrimAtPath(handle)) if p.IsA(UsdSkel.Skeleton)),None)
            if skeleton:self.instances[handle]['skeleton_joint_names']=list(skeleton.GetJointsAttr().Get())
        for tag in tags:
            if not self.performance_optimized or indices.get(tag,-1)<0:
                indices[tag]=a.get_joint_index(tag);self.observation_counters['joint_index_queries']+=1
                if indices[tag]<0 and sample_joints:
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
                if sample_joints:joint_rotations[tag]=[jq.x,jq.y,jq.z,jq.w]
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
        if sample_joints:result['joint_rotations_xyzw_stage']=joint_rotations
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
                focused=bool(self.recorder and self.recorder.focus_actor_id==self.actor_label(handle))
                if self.observation_frame_id is not None and (self.observation_frame_id%3==0 or focused):
                    from .body_geometry import HeadNeckGeometry
                    geometry=self.instances[handle].get('head_neck_geometry')
                    if geometry is None:
                        geometry=HeadNeckGeometry(self.stage,handle);self.instances[handle]['head_neck_geometry']=geometry
                    result['seat_quality'][name]['skinned_vertices']=geometry.evaluate(a,profile,self.mpu)
        self.observation_counters['sdk_samples']+=1
        result.update({k:self.instances[handle][k] for k in ['base_identity_id','appearance_id','appearance_overrides_applied']})
        if any(v.get('canonical_entry',{}).get('native_entry_domain') is not None for v in getattr(self,'custom_actions',{}).values()):
            history=self.instances[handle].setdefault('canonical_heading_history',[])
            if not history or result['observation_sim_time']>history[-1]['observation_sim_time']+1e-9:
                history.append({k:result[k] for k in ['observation_sim_time','native_task_id','action','facing_direction','speed_mps','ready']})
                del history[:-8]
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
        from .custom_stop import ready
        if not ready(self,handle,obs,require_window=True):return False
        hips=obs.get('joints_m',{}).get('Hips');root=obs['position_m']
        return bool(hips and hips[2]-root[2]>0.75 and obs['action'] in {'Idle',''})

    def pause(self):self.timeline.pause()
    def resume(self):self.timeline.play()
    def record(self,p):
        if not self.recorder:raise SimPeopleError('RECORDING_UNAVAILABLE','renderer recording was not configured')
        return self.recorder.control(p)
