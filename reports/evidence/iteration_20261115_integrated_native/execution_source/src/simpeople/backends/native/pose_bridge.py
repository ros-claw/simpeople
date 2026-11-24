"""Kit-thread readbacks and skeleton-only inverse retarget calibration.

No live actor transforms, joint values, or Behavior ownership are written here.
"""
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import carb
import carb.settings
from pxr import Usd, UsdGeom, UsdSkel, Gf, Vt, Sdf
from simpeople.core.errors import SimPeopleError
from simpeople.motion.contracts import digest
from simpeople.motion.pose_bridge import identity
from simpeople.motion.rig import world_to_local, forward_kinematics, convert_root, inverse, validate_poses


def skeleton_descriptor(skeleton):
    result={}
    for key in ['joints','restTransforms','bindTransforms','controlRig:retargetTags','controlRig:retargetTransforms','controlRig:upAxis','controlRig:forwardAxis']:
        value=skeleton.GetPrim().GetAttribute(key).Get()
        result[key]=np.asarray(value).tolist() if value is not None and not isinstance(value,str) else value
    return result


def capture_actual_pose(backend, engine, actor_id, history, source_tick):
    """Read after the world's step and engine tick, at the native scene time."""
    backend.assert_thread()
    try:
        if backend.up != 'Z' or abs(backend.mpu - 1) > 1e-12:
            raise ValueError('pose capture currently requires a Z-up metre scene')
        actor = engine.actors[actor_id]
        handle = actor['handle']
        task = engine.tasks.get(actor.get('task_id'), {})
        binding = identity(task)
        if task.get('status')!='running' or binding['actor_instance_id']!=actor['actor_instance_id'] or binding['control_epoch']!=actor['control_epoch'] or binding['session_id']!=engine.session_id or binding['episode_id']!=engine.episode_id or task.get('cancel_requested'):
            history.clear();return None
        asset = next(a for a in backend.assets if a['asset_id'] == backend.instances[handle]['asset_id'])
        sk = next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(backend.stage.GetPrimAtPath(handle)) if p.IsA(UsdSkel.Skeleton))
        names = list(map(str, sk.GetJointsAttr().Get()))
        agent = backend.agent(handle)
        native_task_id=task.get('native_task_id')
        # An engine tick can submit the next native task after this world's
        # rendering step. Its receipt alone does not make this pose its output.
        if not isinstance(native_task_id,int) or isinstance(native_task_id,bool):
            history.clear();return None
        elapsed=float(agent.get_task_elapsed_time(native_task_id))
        import omni.anim.behavior.core as behavior
        if agent.get_action_task_id()!=native_task_id or agent.get_task_status(native_task_id)!=behavior.BehaviorTaskStatus.RUNNING or not math.isfinite(elapsed) or elapsed<1/30-1e-5:
            history.clear();return None
        pose = []
        for index in range(len(names)):
            point = carb.Float3(0, 0, 0)
            quat = carb.Float4(0, 0, 0, 1)
            if not agent.get_joint_world_transform(index, point, quat):
                raise ValueError('native joint readback failed')
            pose.append([*backend.to_public(point), quat.x, quat.y, quat.z, quat.w])
        row = {'sample_source': 'behavior_sdk', 'actor_id': actor_id,
               'actor_instance_id': actor['actor_instance_id'], 'task': {**binding, 'status': task['status']},
               'source_asset_sha256': asset['content_hash'], 'source_tick': source_tick,
               'active_skeleton_sha256':digest(skeleton_descriptor(sk)),
               'sample_native_task_id':native_task_id,'sample_native_elapsed_s':elapsed,'step_index':task.get('step_index'),
               'sim_time': backend.timeline.get_current_time(), 'joint_paths': names,
               'world_pose': pose, 'actual_observation': backend.observe(handle)}
        history.record(row)
        return row
    except Exception:
        history.clear()
        raise


class NativePoseConverter:
    def __init__(self, backend, asset_path, soma_path, rig, directory, active_skeleton=None, active_descriptor=None,
                 intermediate_skeleton_path=None):
        backend.assert_thread()
        self.backend = backend
        self.rig = rig
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.asset = Path(asset_path).resolve(strict=True)
        self.asset_sha256 = hashlib.sha256(self.asset.read_bytes()).hexdigest()
        source_stage = Usd.Stage.Open(str(self.asset))
        asset_source = next(UsdSkel.Skeleton(p) for p in source_stage.Traverse() if p.IsA(UsdSkel.Skeleton))
        if active_skeleton is not None and active_descriptor is not None:raise ValueError('choose one actual skeleton descriptor')
        source=active_skeleton or asset_source
        if list(map(str,source.GetJointsAttr().Get()))!=list(map(str,asset_source.GetJointsAttr().Get())):raise ValueError('active native skeleton joint layout differs from source asset')
        self.names = list(map(str, source.GetJointsAttr().Get()))
        self.tags = {}
        for index, tag in enumerate(source.GetPrim().GetAttribute('controlRig:retargetTags').Get() or []):
            if tag:
                if str(tag) in self.tags:raise ValueError('ambiguous source retarget tag: '+str(tag))
                self.tags[str(tag)] = index
        self.parents = list(UsdSkel.Topology(source.GetJointsAttr().Get()).GetParentIndices())
        self.mpu = UsdGeom.GetStageMetersPerUnit(source_stage)
        self.yup = UsdGeom.GetStageUpAxis(source_stage) == 'Y'
        if not self.yup and UsdGeom.GetStageUpAxis(source_stage) != 'Z':
            raise ValueError('unsupported source up axis')
        from .motion_import import prepare_soma_rig
        prepare_soma_rig(Path(soma_path), self.directory / 'soma.usda')
        target_stage = Usd.Stage.Open(str(self.directory / 'soma.usda'))
        target = UsdSkel.Skeleton(target_stage.GetPrimAtPath('/Soma/Skeleton'))
        self.namespace = backend.namespace + '/PoseCalibration_' + self.asset_sha256[:12]
        if backend.stage.GetPrimAtPath(self.namespace):
            raise ValueError('pose calibration already exists for this asset')
        UsdGeom.Xform.Define(backend.stage, self.namespace)
        def copy_skeleton(original, path):
            skel = UsdSkel.Skeleton.Define(backend.stage, path)
            # Only static skeleton attributes. No actor meshes, animations,
            # references, relationship targets, or Behavior APIs are cloned.
            for attr in original.GetPrim().GetAttributes():
                value = attr.Get()
                if value is not None:
                    skel.GetPrim().CreateAttribute(attr.GetName(), attr.GetTypeName(), custom=attr.IsCustom()).Set(value)
            return skel
        self.source = copy_skeleton(source, self.namespace + '/Source')
        if active_descriptor is not None:
            if set(active_descriptor)!=set(skeleton_descriptor(asset_source)) or active_descriptor['joints']!=self.names:raise ValueError('recorded active skeleton descriptor is incompatible')
            # These are new calibration prims, never the live actor. Original
            # asset tags can differ from the runtime's AutoSetupControlRig tags.
            for key,value in active_descriptor.items():
                if value is None:continue
                attr=self.source.GetPrim().GetAttribute(key)
                if attr.GetTypeName()==Sdf.ValueTypeNames.Matrix4dArray:value=Vt.Matrix4dArray([Gf.Matrix4d(tuple(tuple(float(x) for x in row) for row in matrix)) for matrix in value])
                elif attr.GetTypeName()==Sdf.ValueTypeNames.TokenArray:value=Vt.TokenArray(value)
                attr.Set(value)
            self.tags={str(tag):i for i,tag in enumerate(self.source.GetPrim().GetAttribute('controlRig:retargetTags').Get()) if tag}
        self.target = copy_skeleton(target, self.namespace + '/Soma')
        self.target_parents = list(UsdSkel.Topology(self.target.GetJointsAttr().Get()).GetParentIndices())
        import omni.anim.retarget.core as retarget
        self.controller = retarget.RetargetController(None, str(self.source.GetPath()), -1, str(self.target.GetPath()))
        self.intermediate = None
        self.route_controllers = []
        if intermediate_skeleton_path is not None:
            path=Path(intermediate_skeleton_path).resolve(strict=True)
            human_stage=Usd.Stage.Open(str(path))
            skeletons=[UsdSkel.Skeleton(p) for p in human_stage.Traverse() if p.IsA(UsdSkel.Skeleton)]
            if (len(skeletons)!=1 or len(skeletons[0].GetJointsAttr().Get())!=81
                    or str(UsdGeom.GetStageUpAxis(human_stage))!='Y'
                    or abs(UsdGeom.GetStageMetersPerUnit(human_stage)-.01)>1e-9):
                raise ValueError('explicit Human81 Y-up centimetre intermediate required')
            self.intermediate=copy_skeleton(skeletons[0],self.namespace+'/Human81')
            self.route_controllers=[
                retarget.RetargetController(None,str(self.source.GetPath()),-1,str(self.intermediate.GetPath())),
                retarget.RetargetController(None,str(self.intermediate.GetPath()),-1,str(self.target.GetPath()))]
        self.profile = {'source_asset_sha256': self.asset_sha256, 'joint_paths_sha256': digest(self.names),
                        'rig_sha256': rig['rig_sha256'], 'mapping_revision': 'native-sdk-actual-rig_to_soma-local-v2' if active_skeleton is not None or active_descriptor is not None else 'native-sdk-world_to_soma-local-v1',
                        'source_axis': 'Y' if self.yup else 'Z', 'source_meters_per_unit': self.mpu,
                        'retarget_runtime': backend.runtime_revision, 'online_application_verified': False}
        template_description=skeleton_descriptor(self.source);active_description=active_descriptor or skeleton_descriptor(active_skeleton or source)
        self.profile['asset_skeleton_sha256']=digest(skeleton_descriptor(asset_source))
        self.profile['template_skeleton_sha256']=digest(template_description)
        self.profile['active_skeleton_sha256']=digest(active_description)
        if self.intermediate is not None:
            self.profile.update(mapping_revision='native-sdk-actual-rig_via-human81_to-soma-local-v3',
                intermediate_asset_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                intermediate_skeleton_sha256=digest(skeleton_descriptor(self.intermediate)),
                retarget_route=['source','human81','soma78'])
            (self.directory/'intermediate_skeleton.json').write_text(json.dumps(skeleton_descriptor(self.intermediate),indent=2)+'\n')
        (self.directory/'template_skeleton.json').write_text(json.dumps(template_description,indent=2)+'\n')
        (self.directory/'active_skeleton.json').write_text(json.dumps(active_description,indent=2)+'\n')
        self.profile['retarget_extension']=next((p.name for p in Path(retarget.__file__).parents if p.name.startswith('omni.anim.retarget.core-')),None)
        self.profile['retarget_settings']={k:carb.settings.get_settings().get('/persistent/exts/omni.anim.retarget.core/'+k) for k in ['enableFeetIK','feetIKActivation','feetIKTags']}
        (self.directory / 'profile.json').write_text(json.dumps(self.profile, indent=2) + '\n')

    def convert_world_history(self, rows, profile):
        self.backend.assert_thread()
        if profile != self.profile:
            raise SimPeopleError('MOTION_RIG_MISMATCH', 'converter calibration profile changed')
        if any(r['joint_paths'] != self.names or r['source_asset_sha256'] != self.asset_sha256 for r in rows):
            raise SimPeopleError('MOTION_RIG_MISMATCH', 'observed native skeleton differs from calibration')
        world = validate_poses([r['world_pose'] for r in rows], len(self.names))
        return self._convert(world,digest(rows),'Read-only inverse retarget of executed samples; no pose application or seam certification.')

    def convert_authored_goal(self, world_pose):
        self.backend.assert_thread()
        world=validate_poses(world_pose,len(self.names))
        if len(world)!=1:raise ValueError('one authored native goal required')
        return self._convert(world,digest({'authored_goal':world.tolist(),'profile':self.profile}),'Offline authored target conversion, not an executed history.')

    def _convert(self,world,sample_digest,scope):
        local = world_to_local(world, self.parents)
        basis = np.array([math.sqrt(.5), 0, 0, math.sqrt(.5)])
        if self.yup:
            local = convert_root(local, inverse(basis))
        local[:, :, :3] /= self.mpu
        source_origin = local[0, 0, :3].copy()
        local[:, 0, :3] -= source_origin
        route_raw={};route_errors={}
        if self.intermediate is not None:
            from simpeople.motion.retarget_chain import retarget_chain
            def invoke(controller,pose):
                p,q=controller.retarget([carb.Float3(*map(float,v[:3])) for v in pose],
                                        [carb.Float4(*map(float,v[3:])) for v in pose])
                return [[*position,*rotation] for position,rotation in zip(p,q)]
            _,route_raw,route_errors=retarget_chain(local,[
                ('source_to_human81',81,lambda pose:invoke(self.route_controllers[0],pose)),
                ('human81_to_soma78',len(self.target_parents),lambda pose:invoke(self.route_controllers[1],pose))])
            raw=route_raw['human81_to_soma78']
        else:
            values = []
            for pose in local:
                p, q = self.controller.retarget([carb.Float3(*map(float, v[:3])) for v in pose], [carb.Float4(*map(float, v[3:])) for v in pose])
                values.append([[*position, *rotation] for position, rotation in zip(p, q)])
            raw = np.array(values, dtype=float)
        norms = np.linalg.norm(raw[:, :, 3:], axis=-1)
        error = float(np.abs(norms - 1).max())
        if not np.isfinite(raw).all() or error > .01:
            raise ValueError('SDK retarget rotations exceed numeric normalization bound')
        corrected = raw.copy()
        corrected[:, :, 3:] /= norms[:, :, None]
        soma = validate_poses(corrected, len(self.target_parents))
        world_soma = forward_kinematics(soma, self.target_parents)
        full = soma[:, 1:, :].copy()
        full[:, 0] = world_soma[:, 1]
        full[:, :, :3] *= .01
        full = convert_root(full, basis)
        full[:, 0, :3] += world[0, 0, :3]
        validate_poses(full, len(self.rig['joint_names']))
        path = self.directory / (sample_digest + '.npz')
        if path.exists():
            with np.load(path, allow_pickle=False) as old:
                if not np.array_equal(old['source_world'], world) or not np.array_equal(old['soma_local'], full):
                    raise ValueError('same observed window produced different conversion')
        else:
            np.savez(path, source_world=world, sdk_raw=raw, soma_local=full, **route_raw)
        receipt={'source_history_sha256': sample_digest, 'conversion_artifact': str(path),
                      'conversion_artifact_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      'max_sdk_quaternion_renormalization': error, 'world_origin_m': world[0, 0, :3].tolist(),
                      'scope': scope}
        if route_raw:
            receipt['retarget_stage_quaternion_renormalization']=route_errors
            receipt['retarget_route']=self.profile['retarget_route']
        return full,receipt

    def close(self):
        self.backend.assert_thread()
        self.controller = None
        self.route_controllers = []
        self.backend.stage.RemovePrim(self.namespace)

    def diagnose_roundtrip(self, conversion):
        """Offline SDK diagnostic on calibration skeletons, not live playback."""
        self.backend.assert_thread()
        import omni.anim.retarget.core as retarget
        with np.load(conversion['conversion_artifact'],allow_pickle=False) as data:
            world=data['source_world'];soma=data['sdk_raw'].copy()
        soma[:,:,3:]/=np.linalg.norm(soma[:,:,3:],axis=-1,keepdims=True)
        if self.intermediate is not None:
            from simpeople.motion.retarget_chain import retarget_chain
            first=retarget.RetargetController(None,str(self.target.GetPath()),-1,str(self.intermediate.GetPath()))
            last=retarget.RetargetController(None,str(self.intermediate.GetPath()),-1,str(self.source.GetPath()))
            def invoke(controller,pose):
                p,q=controller.retarget([carb.Float3(*map(float,v[:3])) for v in pose],[carb.Float4(*map(float,v[3:])) for v in pose])
                return [[*x,*r] for x,r in zip(p,q)]
            restored,_,reverse_errors=retarget_chain(soma,[
                ('soma78_to_human81',81,lambda pose:invoke(first,pose)),
                ('human81_to_source',len(self.names),lambda pose:invoke(last,pose))])
            error=max(reverse_errors.values())
        else:
            controller=retarget.RetargetController(None,str(self.target.GetPath()),-1,str(self.source.GetPath()));values=[]
            for pose in soma:
                p,q=controller.retarget([carb.Float3(*map(float,v[:3])) for v in pose],[carb.Float4(*map(float,v[3:])) for v in pose]);values.append([[*x,*r] for x,r in zip(p,q)])
            restored=np.asarray(values,dtype=float);norm=np.linalg.norm(restored[:,:,3:],axis=-1);error=float(abs(norm-1).max())
        norm=np.linalg.norm(restored[:,:,3:],axis=-1)
        if not np.isfinite(restored).all() or error>.01:raise ValueError('roundtrip SDK diagnostic outside numeric bound')
        restored[:,:,3:]/=norm[:,:,None];local=world_to_local(world,self.parents);basis=np.array([math.sqrt(.5),0,0,math.sqrt(.5)])
        if self.yup:local=convert_root(local,inverse(basis))
        restored[:,0,:3]+=local[0,0,:3]/self.mpu;restored[:,:,:3]*=self.mpu
        if self.yup:restored=convert_root(restored,basis)
        recovered=forward_kinematics(restored,self.parents);position=np.linalg.norm(recovered[:,:,:3]-world[:,:,:3],axis=-1);worst=np.unravel_index(np.argmax(position),position.shape)
        path=self.directory/(conversion['source_history_sha256']+'_roundtrip.npz');np.savez(path,source_world=world,recovered_world=recovered)
        return {'passed':float(position.max())<=.03,'max_joint_position_error_m':float(position.max()),'worst_joint':self.names[worst[1]],'frames':len(world),'mapping_revision':self.profile['mapping_revision'],'max_sdk_quaternion_renormalization':error,'artifact':str(path),'scope':'SDK inverse/forward diagnostic in the actual calibrated tag configuration; not a native playback or seam certificate.'}
