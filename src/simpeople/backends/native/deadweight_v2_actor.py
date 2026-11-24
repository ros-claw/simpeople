"""V2 movie actors: original skinned clothes, measured wrist mitts, mesh QA."""
import importlib.util,json
from pathlib import Path
import numpy as np
from pxr import Usd,UsdGeom,UsdSkel,Gf,Vt
from .deadweight_cinema import FilmActor,FilmPoseCache,quat_apply,quat_mul,inverse

class RepairPoseCache(FilmPoseCache):
    """V2 healthy loop measured from steady Native walking, before infection."""
    def __init__(self,directory):
        super().__init__(directory)
        legs=[i for i,n in enumerate(self.names) if any(k in n for k in ['Thigh','Calf','Foot','Toe'])]
        errors={lag:float(np.abs(self.p[40:89-lag,legs]-self.p[40+lag:89,legs]).mean()) for lag in range(22,44)}
        self.walk_period=min(errors,key=errors.get);self.walk_start=self.walk_period;self.walk_loop_mean_joint_error_m=errors[self.walk_period]
        if self.walk_loop_mean_joint_error_m>.03:raise ValueError('healthy cached loop does not close sufficiently')
    def pose(self,frame,action='zombie'):
        if action!='walk':return super().pose(frame,action)
        k=float(frame)%self.walk_period;i=self.walk_start+int(k);j=self.walk_start+(int(k)+1)%self.walk_period;u=k-int(k);p=self.p[i]*(1-u)+self.p[j]*u;a=self.q[i].copy();b=self.q[j].copy();b[np.sum(a*b,axis=1)<0]*=-1;q=a*(1-u)+b*u;q/=np.linalg.norm(q,axis=1)[:,None];return p,q


def transform_points(points,matrix):
    m=np.asarray(matrix);return np.asarray(points)@m[:3,:3]+m[3,:3]


class ActorV2(FilmActor):
    def __init__(self,stage,path,cache,tint=None,source_uri=None):
        super().__init__(stage,path,cache,tint,source_uri)
        model=stage.GetPrimAtPath(path+'/Character')
        self.skeleton=next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(model) if p.IsA(UsdSkel.Skeleton))
        root=next(UsdSkel.Root(p) for p in Usd.PrimRange(model) if p.IsA(UsdSkel.Root));self.skin_root=root
        self.skin=UsdSkel.Cache();self.skin.Populate(root,Usd.PrimDefaultPredicate);self.skel_query=self.skin.GetSkelQuery(self.skeleton)
        self.meshes=[];self.mitts=[]
        for prim in Usd.PrimRange(model):
            if not prim.IsA(UsdGeom.Mesh):continue
            query=self.skin.GetSkinningQuery(prim)
            if not query:continue
            mesh=UsdGeom.Mesh(prim);points=Vt.Vec3fArray(mesh.GetPointsAttr().Get());ix,weights=query.ComputeVaryingJointInfluences(len(points))
            count=query.GetNumInfluencesPerComponent();ix=np.asarray(ix).reshape(-1,count);weights=np.asarray(weights).reshape(-1,count)
            order=list(query.GetJointOrder() or cache.names)
            foot=np.array([('/L_Foot' in n or '/R_Foot' in n) for n in order])
            hands={s:np.sum(weights*np.array([('/'+s+'_Hand') in n for n in order])[ix],axis=1)>.45 for s in ['L','R']}
            foot_mask=np.sum(weights*foot[ix],axis=1)>.45
            if any(k in prim.GetName().lower() for k in ['shoe','boot']):foot_mask[:]=True
            feet_sides={side:np.sum(weights*np.array([('/'+side+'_Foot') in n or ('/'+side+'_Thigh') in n and any(k in prim.GetName().lower() for k in ['shoe','boot']) for n in order])[ix],axis=1)>.45 for side in ['L','R']}
            self.meshes.append({'prim':prim,'query':query,'rest':points,'feet':foot_mask,'feet_sides':feet_sides,'hands':hands})

    def skin_points(self,*,feet_only=False):
        # UsdSkel query caches are not a live renderer: invalidate after authored
        # pose changes, otherwise a valid-looking query can return rest points.
        self.skin.Clear();self.skin.Populate(self.skin_root,Usd.PrimDefaultPredicate);self.skel_query=self.skin.GetSkelQuery(self.skeleton)
        xforms=self.skel_query.ComputeSkinningTransforms(Usd.TimeCode.Default());xf=UsdGeom.XformCache()
        matrix=xf.GetLocalToWorldTransform(self.skeleton.GetPrim())*xf.GetLocalToWorldTransform(self.stage.GetPrimAtPath(self.path)).GetInverse()
        result={}
        for m in self.meshes:
            if feet_only and not np.any(m['feet']):continue
            points=Vt.Vec3fArray(m['rest'])
            query=self.skin.GetSkinningQuery(m['prim'])
            if not query.ComputeSkinnedPoints(xforms,points,Usd.TimeCode.Default()):raise RuntimeError('skinning readback failed')
            result[str(m['prim'].GetPath())]=transform_points(points,matrix)
        return result

    def update(self,p,q,position,heading=0,grounding_lift_m=None):
        super().update(p,q,position,heading)
        if not self.meshes:return
        if grounding_lift_m is None:
            points=self.skin_points(feet_only=True);soles=np.concatenate([points[str(m['prim'].GetPath())][m['feet']] for m in self.meshes if np.any(m['feet'])]);lift=.001-float(soles[:,2].min())
        else:lift=float(grounding_lift_m)
        translations=self.animation.GetTranslationsAttr().Get();translations[0]=translations[0]+Gf.Vec3f(0,0,lift);self.animation.GetTranslationsAttr().Set(translations)
        self.joint_p[:,2]+=lift
        for updater in self.props:updater(self)
        self.sole_min_actor_z_m=None if grounding_lift_m is not None else float(soles[:,2].min()+lift)

    def rainwear(self,color):
        raise RuntimeError('V2 uses the original skinned clothes; RainCape is prohibited')

    def hood(self,asset):
        prop=UsdGeom.Xform.Define(self.stage,self.path+'/GullHood');prop.GetPrim().GetReferences().AddReference(str(asset));op=prop.AddTransformOp()
        def update(actor):
            point=actor.joint_p[self.cache.index('NeckTwist01')]+np.array([-.15,0,0])
            matrix=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0,0,1),90));matrix.SetTranslateOnly(Gf.Vec3d(*map(float,point)));op.Set(matrix)
        self.props.append(update)

    def short_mitts(self,root,output):
        """Fit from deformed hand vertices, then follow only the wrist bone."""
        root=Path(root);output=Path(output);output.mkdir(parents=True,exist_ok=True)
        spec=importlib.util.spec_from_file_location('short_mitt_builder',root/'.runtime/deadweight_v2/repair_kit/optional_mitt/build_short_wing.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
        points=self.skin_points();measurements={}
        for side in ['L','R']:
            wrist=self.joint_p[self.cache.index(side+'_Hand')];middle=self.joint_p[self.cache.index(side+'_Mid3')]
            y=middle-wrist;y/=np.linalg.norm(y)
            x=self.joint_p[self.cache.index(side+'_Index1')]-self.joint_p[self.cache.index(side+'_Ring1')]
            x-=y*np.dot(x,y);x/=np.linalg.norm(x);z=np.cross(x,y)
            if np.dot(z,np.array([0,1 if side=='L' else -1,0]))<0:x=-x;z=-z
            basis=np.stack([x,y,z]);hand_q=self.joint_q[self.cache.index(side+'_Hand')];hand_rows=quat_apply(hand_q,np.eye(3));calibration=basis@hand_rows.T
            hand=np.concatenate([points[str(m['prim'].GetPath())][m['hands'][side]] for m in self.meshes if np.any(m['hands'][side])])
            local=(hand-wrist)@basis.T;positive=local[local[:,1]>=0]
            L=float(positive[:,1].max());W=float(np.ptp(positive[:,0]));T=float(np.ptp(positive[:,2]));near=local[np.abs(local[:,1])<.018]
            ww=float(np.ptp(near[:,0])) if len(near)>3 else W*.7;wt=float(np.ptp(near[:,2])) if len(near)>3 else T*.8
            if not .10<L<.25 or not .035<W<.15:raise ValueError(f'unreasonable measured palm {side}: {L,W,T}')
            par={'hand_length_m':L,'palm_width_m':W,'palm_thickness_m':T,'wrist_width_m':ww,'wrist_thickness_m':wt,'side':'left' if side=='L' else 'right'}
            asset=output/f'{side}_short_wing.usda';model=builder.build(L,W,T,ww,wt,left=side=='L')
            if not asset.exists():builder.write(model,asset,par)
            prop=UsdGeom.Xform.Define(self.stage,self.path+'/'+side+'WristSocket');prop.GetPrim().GetReferences().AddReference(str(asset));op=prop.AddTransformOp()
            local_points=np.concatenate([v for _,v,_ in model.values()]);measurements[side]={**par,'external_extent_m':np.ptp(local_points,axis=0).tolist(),'socket_hand_basis':calibration.tolist(),'asset':str(asset)}
            self.mitts.append({'side':side,'path':str(prop.GetPath()),'local_points':local_points})
            def update(actor,side=side,calibration=calibration,op=op):
                j=self.cache.index(side+'_Hand');rotation=calibration@quat_apply(actor.joint_q[j],np.eye(3));matrix=np.eye(4);matrix[:3,:3]=rotation;matrix[3,:3]=actor.joint_p[j];op.Set(Gf.Matrix4d(*matrix.ravel().tolist()))
            self.props.append(update)
        (output/'fit_measurements.json').write_text(json.dumps(measurements,indent=2))
        for updater in self.props:updater(self)
        return measurements

    def mitt_world_points(self):
        xf=UsdGeom.XformCache()
        return {m['side']:transform_points(m['local_points'],xf.GetLocalToWorldTransform(self.stage.GetPrimAtPath(m['path']))) for m in self.mitts}

    def foot_points(self):
        points=self.skin_points(feet_only=True)
        return {side:np.concatenate([points[str(m['prim'].GetPath())][m['feet_sides'][side]] for m in self.meshes if np.any(m['feet_sides'][side])]) for side in ['L','R']}


class SkinnedStride:
    """Movie contact correction using deformed shoe vertices, not toe joints."""
    def __init__(self,actor,action='zombie'):
        self.actor=actor;self.cache=actor.cache;self.action=action;self.period=self.cache.period if action=='zombie' else getattr(self.cache,'walk_period',38)
        self.feet=[]
        for phase in range(self.period):
            p,q=self.cache.pose(phase,action);actor.update(p,q,[0,0,0]);self.feet.append(actor.foot_points())
        self.travel=np.zeros((self.period+1,3));self.support=[]
        for k in range(1,self.period+1):
            a=self.feet[(k-1)%self.period];b=self.feet[k%self.period]
            preferred=['L','R'][self.cache.support[k-1]] if action=='zombie' else min(['L','R'],key=lambda s:float(np.median(b[s][:,0]-a[s][:,0]))+2*max(0,float(b[s][:,2].min())-.06))
            before=a[preferred];after=b[preferred];mask=(before[:,2]<.025)&(after[:,2]<.03)
            if mask.sum()<3:
                mask=np.zeros(len(before),bool);mask[np.argsort(before[:,2]+after[:,2])[:8]]=True
            delta=np.median(before[mask]-after[mask],axis=0);delta[2]=0;self.travel[k]=self.travel[k-1]+delta;self.support.append(preferred)
        if self.travel[-1,0]<=0:raise ValueError('measured shoe stride does not advance')

    def displacement(self,frame):
        cycles,k=divmod(float(frame),self.period);i=int(k);u=k-i
        return cycles*self.travel[-1]+self.travel[i]*(1-u)+self.travel[i+1]*u

    def phase_at_distance(self,distance):
        cycles,x=divmod(float(distance),self.travel[-1,0])
        if np.min(np.diff(self.travel[:,0]))<=0:raise ValueError('nonmonotone foot displacement: do not silently move root backwards')
        return cycles*self.period+float(np.interp(x,self.travel[:,0],np.arange(self.period+1)))


def wrist_turn(cache,p,q,side,angle):
    p=p.copy();q=q.copy();j=cache.index(side+'_Hand');axis=p[cache.index(side+'_Mid3')]-p[j];axis/=np.linalg.norm(axis)
    turn=np.r_[axis*np.sin(angle/2),np.cos(angle/2)]
    branch=[i for i,n in enumerate(cache.names) if n==cache.names[j] or n.startswith(cache.names[j]+'/')]
    p[branch]=quat_apply(turn,p[branch]-p[j])+p[j];q[branch]=quat_mul(turn,q[branch]);return p,q
