"""Production 101-bone sprint caches and actor-specific deformed-shoe fitting."""
import json,math
from pathlib import Path
import numpy as np
from pxr import Gf,Vt
from .deadweight_cinema import FilmPoseCache,quat_apply,quat_mul,inverse
from .deadweight_v2_actor import ActorV2

class MetroMotion(FilmPoseCache):
    def __init__(self,root):
        root=Path(root);run=root/'runs/platform04-motion-01';self.rig=json.loads((run/'rig.json').read_text());self.names=self.rig['joints'];self.parents=[self.names.index(n.rsplit('/',1)[0]) if '/' in n else -1 for n in self.names];self.parent_indices=np.array(self.parents);depth=[]
        for p in self.parents:depth.append(0 if p<0 else depth[p]+1)
        self.levels=[np.where(np.array(depth)==d)[0] for d in range(1,max(depth)+1)];self.toes=[self.index(s+'_ToeBase') for s in ['L','R']]
        rows=[json.loads(s) for s in (run/'frames.jsonl').read_text().splitlines()];data=np.load(run/'native_bones.npz');heading=np.arctan2([r['facing_direction'][1] for r in rows],[r['facing_direction'][0] for r in rows]);turn=np.zeros((len(rows),4));turn[:,2]=np.sin(-heading/2);turn[:,3]=np.cos(heading/2);self.p=quat_apply(turn[:,None,:],data['positions']-np.array([r['position_m'] for r in rows])[:,None,:]);self.q=quat_mul(turn[:,None,:],data['rotations']);self.clips={'sprint':(45,17),'infected_sprint':(135,17),'crouch':(205,53),'idle':(295,1)}
        # The imported full sprint's plant speed is about 9 m/s on this rig.
        # Keep its cadence and upper-body performance, fit leg excursion with
        # named two-bone IK for the station's 3-4 m/s chase. No global scaling.
        self.stride_scale=.36
        for i in [*range(45,62),*range(135,152)]:self.p[i],self.q[i]=fit_stride(self,self.p[i],self.q[i],self.stride_scale)
    def pose(self,frame,action='idle'):
        start,period=self.clips[action];u=float(frame)%period;i=int(u);a=start+i;b=start+(i+1)%period;w=u-i;p=self.p[a]*(1-w)+self.p[b]*w;q0=self.q[a];q1=self.q[b].copy();q1[np.sum(q0*q1,axis=1)<0]*=-1;q=q0*(1-w)+q1*w;q/=np.linalg.norm(q,axis=1)[:,None];return p.copy(),q

def rotate_branch(cache,p,q,leaf,rotation):
    p=p.copy();q=q.copy();j=cache.index(leaf);ids=[i for i,n in enumerate(cache.names) if n==cache.names[j] or n.startswith(cache.names[j]+'/')];p[ids]=quat_apply(rotation,p[ids]-p[j])+p[j];q[ids]=quat_mul(rotation,q[ids]);return p,q

def axis_q(axis,angle):
    v=np.asarray(axis,float);v/=np.linalg.norm(v);return np.r_[v*np.sin(angle/2),np.cos(angle/2)]

def blend(a,b,w):
    p,q=a;pp,qq=b;qq=qq.copy();qq[np.sum(q*qq,axis=1)<0]*=-1;r=q*(1-w)+qq*w;r/=np.linalg.norm(r,axis=1)[:,None];return p*(1-w)+pp*w,r

def look_at(cache,p,q,angle,weight=1.):
    # A torso contribution prevents impossible 180-degree neck twists.
    desired_angle=float(angle);angle=float(np.clip(angle,-2.25,2.25))*weight;torso=angle*.24;p,q=rotate_branch(cache,p,q,'Spine02',axis_q([0,0,1],torso));forward=quat_apply(q[cache.index('Head')],[0,0,1]);target=np.array([math.cos(angle),math.sin(angle),-.02]);target/=np.linalg.norm(target);axis=np.cross(forward,target);length=np.linalg.norm(axis)
    if length>1e-8:p,q=rotate_branch(cache,p,q,'NeckTwist01',axis_q(axis,min(1.75,math.atan2(length,float(forward@target)))))
    eye_turn=float(np.clip(desired_angle-angle,-.40,.40))
    for side in ['L','R']:p,q=rotate_branch(cache,p,q,side+'_Eye',axis_q([0,0,1],eye_turn))
    return p,q

def reach(cache,p,q,side,target):
    """Bounded two-bone IK on named upper-arm/forearm branches, movie only."""
    p=p.copy();q=q.copy();shoulder=cache.index(side+'_Upperarm');elbow=cache.index(side+'_Forearm');hand=cache.index(side+'_Hand');target=np.asarray(target,float)
    def align(leaf,child,desired):
        nonlocal p,q
        j=cache.index(leaf);k=cache.index(child);a=p[k]-p[j];b=desired-p[j];a/=np.linalg.norm(a);b/=np.linalg.norm(b);c=np.cross(a,b);le=np.linalg.norm(c)
        if le>1e-8:p,q=rotate_branch(cache,p,q,leaf,axis_q(c,math.atan2(le,float(a@b))))
    S=p[shoulder];a=np.linalg.norm(p[elbow]-S);b=np.linalg.norm(p[hand]-p[elbow]);v=target-S;d=float(np.clip(np.linalg.norm(v),abs(a-b)+.015,a+b-.01));direction=v/np.linalg.norm(v);normal=np.cross(direction,np.array([0,0,1.]));normal/=max(np.linalg.norm(normal),1e-8);bend=np.cross(normal,direction);along=(a*a+d*d-b*b)/(2*d);desired_elbow=S+direction*along-bend*math.sqrt(max(0,a*a-along*along));align(side+'_Upperarm',side+'_Forearm',desired_elbow);align(side+'_Forearm',side+'_Hand',S+direction*d);return p,q

def fit_stride(cache,p,q,scale):
    p=p.copy();q=q.copy()
    for side in ['L','R']:
        top,mid,end=[cache.index(side+'_'+s) for s in ['Thigh','Calf','Foot']];S=p[top].copy();target=p[end].copy();target[0]=S[0]+(target[0]-S[0])*scale;target[2]=.11+max(0,target[2]-.11)*.68;foot_q=q[end].copy();a=np.linalg.norm(p[mid]-S);b=np.linalg.norm(p[end]-p[mid]);delta=target-S;d=min(a+b-.008,np.linalg.norm(delta));direction=delta/np.linalg.norm(delta);pole=p[mid]-S;pole-=direction*np.dot(pole,direction)
        if np.linalg.norm(pole)<.01:pole=np.array([1.,0,0])-direction*direction[0]
        pole/=np.linalg.norm(pole);along=(a*a+d*d-b*b)/(2*d);knee=S+direction*along+pole*math.sqrt(max(0,a*a-along*along))
        for leaf,child,goal in [(side+'_Thigh',side+'_Calf',knee),(side+'_Calf',side+'_Foot',S+direction*d)]:
            j=cache.index(leaf);k=cache.index(child);v=p[k]-p[j];w=goal-p[j];v/=np.linalg.norm(v);w/=np.linalg.norm(w);axis=np.cross(v,w)
            if np.linalg.norm(axis)>1e-8:p,q=rotate_branch(cache,p,q,leaf,axis_q(axis,math.atan2(np.linalg.norm(axis),v@w)))
        p,q=rotate_branch(cache,p,q,side+'_Foot',quat_mul(foot_q,inverse(q[end])))
    return p,q

class MetroActor(ActorV2):
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw);self.fits={}
    def update(self,p,q,position,heading=0,lift=0):
        # Preserve flight phases: the old all-frame minimum-toe grounding is
        # intentionally replaced by an actor/clip-specific shoe calibration.
        t,r=self.cache.local_trs(p,q);t=t*self.length_ratio[:,None];t[0,2]+=lift;self.joint_p=t.copy();self.joint_q=q
        for ids in self.cache.levels:
            ps=self.cache.parent_indices[ids];self.joint_p[ids]=self.joint_p[ps]+quat_apply(q[ps],t[ids])
        self.animation.GetTranslationsAttr().Set(Vt.Vec3fArray.FromNumpy(t.astype(np.float32)));self.animation.GetRotationsAttr().Set(Vt.QuatfArray([Gf.Quatf(float(a[3]),Gf.Vec3f(*map(float,a[:3]))) for a in r]));self.matrix=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0,0,1),math.degrees(heading)));self.matrix.SetTranslateOnly(Gf.Vec3d(*map(float,position)));self.xform.Set(self.matrix)
        for updater in self.props:updater(self)
    def fit(self,action):
        if action in self.fits:return self.fits[action]
        period=self.cache.clips[action][1];feet=[]
        for k in range(period):self.update(*self.cache.pose(k,action),[0,0,0]);feet.append(self.foot_points())
        minimum=np.array([min(float(v[:,2].min()) for v in f.values()) for f in feet]);h=minimum-minimum.min();u=np.clip(h/.06,0,1);weight=1-u*u*(3-2*u);lifts=.003-minimum.min()-h*weight
        for k in range(period):self.update(*self.cache.pose(k,action),[0,0,0],lift=lifts[k]);feet[k]=self.foot_points()
        dx=np.full(period,np.nan);support=[]
        for k in range(period):
            previous=feet[k];current=feet[(k+1)%period];candidates=[]
            for side in ['L','R']:
                a,b=previous[side],current[side];mask=(a[:,2]<.035)&(b[:,2]<.045)
                if mask.sum()>2:
                    delta=float(np.median(a[mask,0]-b[mask,0]))
                    if delta>0:candidates.append((delta,side))
            if candidates:dx[k],side=max(candidates);support.append(side)
            else:support.append(None)
        known=np.flatnonzero(np.isfinite(dx))
        if not len(known) and action!='idle':raise ValueError('no actual shoe support in '+action)
        if len(known):dx=np.interp(np.arange(period),np.r_[known-period,known,known+period],np.tile(dx[known],3))
        else:dx[:]=0
        travel=np.r_[0,np.cumsum(dx)];result={'period':period,'lifts':lifts,'travel':travel,'feet':feet,'support':support,'stride_m':float(travel[-1]),'flight_frames':sum(min(float(v[:,2].min()) for v in f.values())>.05 for f in feet)};self.fits[action]=result;return result
    def phase(self,distance,action):
        fit=self.fit(action);cycles,x=divmod(max(0,float(distance)),fit['stride_m']);return cycles*fit['period']+float(np.interp(x,fit['travel'],np.arange(fit['period']+1)))
    def ground_lift(self,action,phase):
        a=self.fit(action);k=float(phase)%a['period'];i=int(k);u=k-i;return float(a['lifts'][i]*(1-u)+a['lifts'][(i+1)%a['period']]*u)
