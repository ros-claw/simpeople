"""Film-only full-pose playback. This does not implement navigation/Native ride.

Input is sampled from the actual Behavior runtime, including all 101 joints.
The cinematic controller exclusively owns bones and actor transforms. A support
toe proxy reconstructs translation for the imported in-place zombie cycle.
"""
import json
from pathlib import Path
import numpy as np

def cross3(a,b):
    """Fixed three-component cross product; avoid generic axis reshuffling."""
    return np.stack([a[...,1]*b[...,2]-a[...,2]*b[...,1],a[...,2]*b[...,0]-a[...,0]*b[...,2],a[...,0]*b[...,1]-a[...,1]*b[...,0]],axis=-1)

def quat_mul(a,b):
    a=np.asarray(a);b=np.asarray(b)
    return np.concatenate((a[...,3,None]*b[...,:3]+b[...,3,None]*a[...,:3]+cross3(a[...,:3],b[...,:3]),(a[...,3]*b[...,3]-np.sum(a[...,:3]*b[...,:3],axis=-1))[...,None]),axis=-1)

def quat_apply(q,v):
    q=np.asarray(q);v=np.asarray(v);t=2*cross3(q[...,:3],v)
    return v+q[...,3,None]*t+cross3(q[...,:3],t)

def inverse(q):
    result=np.array(q,copy=True);result[...,:3]*=-1;return result


class FilmPoseCache:
    def __init__(self, directory):
        directory=Path(directory)
        self.rig=json.loads((directory/'cache_rig.json').read_text())
        self.names=self.rig['joints']
        self.parents=[self.names.index(n.rsplit('/',1)[0]) if '/' in n else -1 for n in self.names]
        rows=[json.loads(s) for s in (directory/'zombie_frames.jsonl').read_text().splitlines()]
        data=np.load(directory/'native_bones.npz')
        heading=np.arctan2([r['facing_direction'][1] for r in rows],[r['facing_direction'][0] for r in rows])
        self.heading=heading;self.roots=np.array([r['position_m'] for r in rows])
        turn=np.zeros((len(heading),4));turn[:,2]=np.sin(-heading/2);turn[:,3]=np.cos(-heading/2)
        origin=np.array([r['position_m'] for r in rows])
        self.p=quat_apply(turn[:,None,:],data['positions']-origin[:,None,:])
        self.q=quat_mul(turn[:,None,:],data['rotations'])
        depths=[]
        for parent in self.parents:depths.append(0 if parent<0 else depths[parent]+1)
        self.levels=[np.where(np.asarray(depths)==d)[0] for d in range(1,max(depths)+1)]
        self.parent_indices=np.array(self.parents)
        self.toes=[self.index('L_ToeBase'),self.index('R_ToeBase')]
        # Measure the loop in the retargeted runtime: its sample rate differs
        # from the source asset. Never assume its authored 40-frame period.
        errors={k:float(np.abs(self.p[140:260-k]-self.p[140+k:260]).mean()) for k in range(25,50)}
        self.period=min(errors,key=errors.get)
        if errors[self.period]>1e-4:raise ValueError('no stable runtime zombie loop')
        self.cycle=self.p[140:140+self.period].copy()
        self.travel=np.zeros((self.period+1,3));self.support=[]
        for k in range(1,self.period+1):
            a=self.cycle[(k-1)%self.period,self.toes];b=self.cycle[k%self.period,self.toes]
            # Advancing foot is swing; the backward moving low toe is support.
            score=(b[:,0]-a[:,0])+np.maximum(b[:,2]-b[:,2].min()-.06,0)*2
            toe=int(np.argmin(score));self.support.append(toe)
            delta=a[toe]-b[toe];delta[2]=0
            self.travel[k]=self.travel[k-1]+delta
        if self.travel[-1,0]<=0:raise ValueError('invalid reconstructed stride')

    def index(self, leaf):return next(i for i,n in enumerate(self.names) if n.rsplit('/',1)[-1]==leaf)

    def pose(self, frame, action='zombie'):
        if action=='zombie':
            start=140;period=self.period
        elif action=='walk':
            start=22;period=38
        else:
            return self.p[380].copy(),self.q[380].copy()
        k=float(frame)%period;i=start+int(k);j=start+(int(k)+1)%period;u=k-int(k)
        p=self.p[i]*(1-u)+self.p[j]*u;a=self.q[i].copy();b=self.q[j].copy()
        b[np.sum(a*b,axis=1)<0]*=-1;q=a*(1-u)+b*u;q/=np.linalg.norm(q,axis=1)[:,None]
        return p,q

    def displacement(self, frame):
        cycles,k=divmod(float(frame),self.period);i=int(k);u=k-i
        return cycles*self.travel[-1]+self.travel[i]*(1-u)+self.travel[i+1]*u

    def phase_at_distance(self,distance):
        cycles,x=divmod(float(distance),self.travel[-1,0])
        return cycles*self.period+float(np.interp(x,self.travel[:,0],np.arange(self.period+1)))

    def local_trs(self,p,q):
        """Global canonical joint poses to source Skeleton's parent-local TRS."""
        t=p.copy();rq=q.copy();j=np.where(self.parent_indices>=0)[0];parents=self.parent_indices[j]
        inv=inverse(q[parents]);t[j]=quat_apply(inv,p[j]-p[parents]);rq[j]=quat_mul(inv,q[j])
        return t,rq

    def report(self):
        # A proxy test of each integrated support interval; not a foot force.
        residual=[]
        for k in range(1,self.period+1):
            toe=self.toes[self.support[k-1]]
            a=self.cycle[(k-1)%self.period,toe]+self.travel[k-1]
            b=self.cycle[k%self.period,toe]+self.travel[k]
            residual.append(float(np.linalg.norm((a-b)[:2])))
        return {'mode':'exclusive film skeletal cache, not Native zombie navigation',
                'runtime_cycle_frames':self.period,'stride_m':self.travel[-1].tolist(),
                'support_toe_horizontal_step_max_m':max(residual),
                'contact_scope':'selected toe proxy; drag/swing toe intentionally moves; not a mesh/force test'}


class FilmActor:
    def __init__(self,stage,path,cache,tint=None,source_uri=None):
        from pxr import UsdGeom,UsdSkel,UsdShade,Sdf,Gf,Vt,Usd
        self.stage=stage;self.path=path;self.cache=cache
        self.xform=UsdGeom.Xform.Define(stage,path).AddTransformOp()
        model=stage.DefinePrim(path+'/Character');model.GetReferences().AddReference(source_uri or cache.rig['source_uri'])
        skeleton=next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(model) if p.IsA(UsdSkel.Skeleton))
        if list(skeleton.GetJointsAttr().Get())!=cache.names:raise ValueError('film target skeleton topology mismatch')
        original=Usd.Stage.Open(cache.rig['source_uri']);original_skeleton=next(UsdSkel.Skeleton(p) for p in original.Traverse() if p.IsA(UsdSkel.Skeleton))
        lengths=np.array([m.ExtractTranslation().GetLength() for m in original_skeleton.GetRestTransformsAttr().Get()])
        target=np.array([m.ExtractTranslation().GetLength() for m in skeleton.GetRestTransformsAttr().Get()])
        self.length_ratio=np.divide(target,lengths,out=np.ones_like(target),where=lengths>1e-6)
        self.length_ratio[0]=1
        self.props=[]
        for prim in Usd.PrimRange(model):
            if prim.IsA(UsdGeom.Mesh) and any(k in prim.GetName().lower() for k in ['hardhat','policehat','badge','holster']):UsdGeom.Imageable(prim).MakeInvisible()
        # There is no Behavior API on this reference. No competing controller.
        self.animation=UsdSkel.Animation.Define(stage,path+'/FilmAnimation')
        self.animation.CreateJointsAttr(Vt.TokenArray(cache.names))
        self.animation.CreateScalesAttr(Vt.Vec3hArray([Gf.Vec3h(1)]*len(cache.names)))
        UsdSkel.BindingAPI.Apply(skeleton.GetPrim()).CreateAnimationSourceRel().SetTargets([self.animation.GetPath()])
        self.animation.CreateTranslationsAttr();self.animation.CreateRotationsAttr()
        if tint:
            for prim in Usd.PrimRange(model):
                name=str(prim.GetPath()).lower()
                if not prim.IsA(UsdShade.Shader) or not any(k in name for k in ['fabric','cloth','shirt','pant','jacket','suit','vest']):continue
                if any(k in name for k in ['skin','hair','eye','teeth']):continue
                mdl=prim.GetAttribute('info:mdl:sourceAsset').Get()
                if not mdl:continue
                key='diffuse_reflection_color' if mdl.path.endswith('OmniSurface.mdl') else 'diffuse_tint'
                UsdShade.Shader(prim).CreateInput(key,Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*tint))
                if key=='diffuse_reflection_color':UsdShade.Shader(prim).GetInput('diffuse_reflection_color_image').Set(Sdf.AssetPath(''))

    def update(self,p,q,position,heading=0):
        from pxr import Gf,Vt
        t,r=self.cache.local_trs(p,q)
        t=t*self.length_ratio[:,None]
        # Re-evaluate target anatomy for prop mounts and geometric observations.
        self.joint_p=t.copy()
        for j in self.cache.levels:
            parents=self.cache.parent_indices[j];self.joint_p[j]=self.joint_p[parents]+quat_apply(q[parents],t[j])
        self.joint_q=q
        # Film-only grounding, after adapting the complete target anatomy.
        # Toe joints are above the shoe sole; this is a contact proxy, not IK
        # from a physics contact sensor. Preserve all source joint rotations.
        lift=.04-min(self.joint_p[j,2] for j in self.cache.toes)
        t[0,2]+=lift;self.joint_p[:,2]+=lift
        self.animation.GetTranslationsAttr().Set(Vt.Vec3fArray.FromNumpy(t.astype(np.float32)))
        self.animation.GetRotationsAttr().Set(Vt.QuatfArray([Gf.Quatf(float(a[3]),Gf.Vec3f(*map(float,a[:3]))) for a in r]))
        self.matrix=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0,0,1),float(np.degrees(heading))))
        self.matrix.SetTranslateOnly(Gf.Vec3d(*map(float,position)));self.xform.Set(self.matrix)
        for updater in self.props:updater(self)

    def rainwear(self,color):
        """A simple authored waterproof cape follows animated shoulders/hips."""
        from pxr import UsdGeom,Gf
        mesh=UsdGeom.Mesh.Define(self.stage,self.path+'/RainCape')
        mesh.CreateSubdivisionSchemeAttr('none');mesh.CreateDoubleSidedAttr(True)
        mesh.SetNormalsInterpolation('vertex')
        mesh.CreatePointsAttr();mesh.CreateNormalsAttr()
        segments=24;rings=5
        mesh.CreateFaceVertexCountsAttr([4]*(segments*(rings-1)))
        mesh.CreateFaceVertexIndicesAttr([v for r in range(rings-1) for k in range(segments) for v in [r*segments+k,r*segments+(k+1)%segments,(r+1)*segments+(k+1)%segments,(r+1)*segments+k]])
        mesh.CreateDisplayColorAttr([Gf.Vec3f(*color)])
        angles=np.arange(segments)*2*np.pi/segments;cosine=np.cos(angles)[None,:,None];sine=np.sin(angles)[None,:,None]
        widths=np.array([.30,.27,.29,.30,.15])[:,None,None];depths=np.array([.21,.19,.19,.18,.115])[:,None,None]
        folds=1+.035*np.cos(angles*8)[None,:,None];heights=np.linspace(0,1,rings)[:,None,None]
        def update(actor):
            hips=actor.joint_p[self.cache.index('Hip')];chest=actor.joint_p[self.cache.index('Spine02')]
            up=chest-hips;up/=np.linalg.norm(up);across=np.array([0,1,0]);front=cross3(across,up);front/=np.linalg.norm(front)
            top=chest+up*.13;bottom=hips-up*.14
            centers=bottom[None,None,:]+(top-bottom)[None,None,:]*heights
            points=centers+folds*(front[None,None,:]*depths*cosine+across[None,None,:]*widths*sine)
            normals=front[None,None,:]*cosine/depths+across[None,None,:]*sine/widths;normals/=np.linalg.norm(normals,axis=2)[:,:,None]
            from pxr import Vt
            mesh.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(points.reshape(-1,3).astype(np.float32)))
            mesh.GetNormalsAttr().Set(Vt.Vec3fArray.FromNumpy(normals.reshape(-1,3).astype(np.float32)))
        self.props.append(update)

    def gull(self,asset):
        from pxr import UsdGeom,Gf
        prop=UsdGeom.Xform.Define(self.stage,self.path+'/GullHood');prop.GetPrim().GetReferences().AddReference(str(asset));op=prop.AddTransformOp()
        wings=[]
        for side in ['L','R']:
            wing=UsdGeom.Sphere.Define(self.stage,self.path+'/'+side+'Wing');wing.CreateRadiusAttr(1);wing.CreateDisplayColorAttr([Gf.Vec3f(.87,.86,.69)]);wing_op=wing.AddTransformOp();wings.append((side,wing_op))
        def update(actor):
            neck=actor.joint_p[self.cache.index('NeckTwist01')]+np.array([-.15,0,0])
            m=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0,0,1),90));m.SetTranslateOnly(Gf.Vec3d(*map(float,neck)));op.Set(m)
            for side,wo in wings:
                hand=actor.joint_p[self.cache.index(side+'_Hand')];elbow=actor.joint_p[self.cache.index(side+'_Forearm')]
                direction=hand-elbow;direction/=np.linalg.norm(direction)
                rot=Gf.Rotation(Gf.Vec3d(0,0,1),Gf.Vec3d(*map(float,direction)))
                wm=Gf.Matrix4d().SetScale(Gf.Vec3d(.19,.09,.40))*Gf.Matrix4d().SetRotate(rot);wm.SetTranslateOnly(Gf.Vec3d(*map(float,hand+direction*.12)));wo.Set(wm)
        self.props.append(update)

    def camera_prop(self):
        from .deadweight_set import box
        from pxr import UsdGeom,Gf
        parent=UsdGeom.Xform.Define(self.stage,self.path+'/TouristCamera');op=parent.AddTranslateOp()
        box(self.stage,self.path+'/TouristCamera/Body',(0,0,0),(.10,.21,.14),(.015,.018,.022),.5)
        lens=UsdGeom.Cylinder.Define(self.stage,self.path+'/TouristCamera/Lens');lens.CreateAxisAttr('X');lens.CreateRadiusAttr(.06);lens.CreateHeightAttr(.11);lens.AddTranslateOp().Set(Gf.Vec3d(.08,0,0));lens.CreateDisplayColorAttr([Gf.Vec3f(.025,.055,.065)])
        def update(actor):op.Set(Gf.Vec3d(*map(float,actor.joint_p[self.cache.index('Spine02')]+np.array([.22,0,-.06]))))
        self.props.append(update)


def raised_wings(cache,p,q,amount,sides=('L','R')):
    """Film gesture: rotate each whole arm branch, preserving skin hierarchy."""
    p=p.copy();q=q.copy()
    for side in sides:
        bone=cache.index(side+'_Upperarm');pivot=p[bone].copy()
        angle=-float(amount)*1.9;rotation=np.array([0,np.sin(angle/2),0,np.cos(angle/2)])
        branch=[i for i,n in enumerate(cache.names) if n==cache.names[bone] or n.startswith(cache.names[bone]+'/')]
        p[branch]=quat_apply(rotation,p[branch]-pivot)+pivot
        q[branch]=quat_mul(rotation,q[branch])
    return p,q


def torso_sway(cache,p,q,angle):
    p=p.copy();q=q.copy();bone=cache.index('Spine01');pivot=p[bone].copy()
    rotation=np.array([0,np.sin(angle/2),0,np.cos(angle/2)])
    branch=[i for i,n in enumerate(cache.names) if n==cache.names[bone] or n.startswith(cache.names[bone]+'/')]
    p[branch]=quat_apply(rotation,p[branch]-pivot)+pivot;q[branch]=quat_mul(rotation,q[branch])
    return p,q


def infected_wait(cache,phase,amount=1):
    """Plant the ordinary idle legs and graft the sick upper-body performance.

    Background waits must not play a walking cycle with a stationary root.
    """
    p,q=cache.pose(0,'idle');zp,zq=cache.pose(phase)
    bone=cache.index('Spine01');parent=cache.parents[bone]
    align=quat_mul(q[parent],inverse(zq[parent]))
    branch=[i for i,n in enumerate(cache.names) if n==cache.names[bone] or n.startswith(cache.names[bone]+'/')]
    target_p=quat_apply(align,zp[branch]-zp[bone])+p[bone]
    target_q=quat_mul(align,zq[branch]);a=q[branch].copy();target_q[np.sum(a*target_q,axis=1)<0]*=-1
    p[branch]=p[branch]*(1-amount)+target_p*amount;q[branch]=a*(1-amount)+target_q*amount;q[branch]/=np.linalg.norm(q[branch],axis=1)[:,None]
    return p,q
