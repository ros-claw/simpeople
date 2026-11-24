"""Authored action phrases and explicit short-step support for R2 film tests.

Native Jog remains a source for ordinary travel, never the entire performance.
Braking, launching, missed grabs and recovery have separate full-body phases.
"""
import math
from dataclasses import dataclass
from pathlib import Path
import numpy as np
from .platform04_90_animation import DirectorMotion,DirectorActor,canonical_capture
from .performance_score import smooth,window
from .platform04_animation import axis_q,rotate_branch,reach
from .deadweight_cinema import quat_apply,quat_mul,inverse


class PerformanceMotion(DirectorMotion):
    def __init__(self,root):
        super().__init__(root)
        p,q=canonical_capture(Path(root)/'runs/deadweight-zombie-probe-05','zombie_frames.jsonl')
        errors={k:float(np.abs(p[140:260-k]-p[140+k:260]).mean()) for k in range(25,50)}
        period=min(errors,key=errors.get)
        if errors[period]>1e-4:raise ValueError('unstable previously captured infection walk')
        self.banks['zslow']=[self.anatomy.from_global(p[k],q[k]) for k in range(140,140+period)]
        self.clips['zslow']=(0,period)


@dataclass
class Sole:
    path: str
    vertex: int
    offset_bone: np.ndarray
    foot_q: np.ndarray


class FootPhrase:
    """Animator-authored contacts; not inferred from a toe's height afterward."""
    def __init__(self,root_sample,slots):
        self.root_sample=root_sample;self.slots={s:[] for s in ['L','R']}
        for side,start,end,advance in slots:
            p,yaw,_=root_sample(start);c,s=math.cos(yaw),math.sin(yaw);lateral=.115 if side=='L' else -.115
            anchor=np.r_[p+[c*advance-s*lateral,s*advance+c*lateral],.004]
            self.slots[side].append({'start':start,'end':end,'anchor':anchor,'yaw':yaw})
        for values in self.slots.values():values.sort(key=lambda v:v['start'])

    def target(self,side,t):
        slots=self.slots[side]
        for i,slot in enumerate(slots):
            if slot['start']<=t<=slot['end']:
                return slot['anchor'].copy(),slot['yaw'],True,f'{side}:{i}:{slot["start"]:.3f}'
        previous=[v for v in slots if v['end']<t];following=[v for v in slots if v['start']>t]
        if not previous:return slots[0]['anchor'].copy(),slots[0]['yaw'],False,None
        if not following:return slots[-1]['anchor'].copy(),slots[-1]['yaw'],False,None
        a,b=previous[-1],following[0];u=np.clip((t-a['end'])/(b['start']-a['end']),0,1);w=smooth(u);p=a['anchor']*(1-w)+b['anchor']*w;p[2]+=.105*math.sin(math.pi*u)**1.3
        yaw=a['yaw']+((b['yaw']-a['yaw']+math.pi)%(2*math.pi)-math.pi)*w
        return p,yaw,False,None


def door_feet(score,aid):
    if aid=='H01':slots=[('L',4.40,4.57,.25),('R',4.62,4.98,.32),('L',5.00,5.26,.20),('R',5.35,5.54,.22),('L',5.62,5.80,.22),('R',5.91,6.08,.22),('L',6.19,6.34,.22)]
    else:slots=[('R',3.40,3.55,.19),('L',3.68,3.84,.18),('R',3.94,4.13,.14),('L',4.20,4.53,.10),('R',4.43,4.73,.09),('L',4.74,5.02,.10),('R',4.99,5.15,.13),('L',5.27,5.40,.22),('R',5.56,5.69,.22),('L',5.85,5.98,.22),('R',6.14,6.27,.21),('L',6.45,6.68,.15),('R',6.81,7.08,.13),('L',7.20,7.55,.10),('R',7.55,8.05,.06),('L',8.10,8.42,.05),('R',8.55,8.92,.05),('L',9.05,10.1,.05)]
    return FootPhrase(lambda t:score.root(aid,t),slots)


class PerformanceActor(DirectorActor):
    def calibrate_soles(self):
        self.safe_update(self.cache.pose(0,'idle'),[0,0,0]);cloud=self.skin_points(feet_only=True);self.soles={}
        for side in ['L','R']:
            candidates=[]
            for m in self.meshes:
                path=str(m['prim'].GetPath());ix=np.flatnonzero(m['feet_sides'][side])
                if path in cloud and len(ix):
                    for j in ix:candidates.append((path,int(j),cloud[path][j],any(k in m['prim'].GetName().lower() for k in ['shoe','boot'])))
            preferred=[v for v in candidates if v[3]] or candidates;points=np.array([v[2] for v in preferred]);low=points[:,2].min();ankle=self.joint_p[self.cache.index(side+'_Foot')];goal=ankle+[.10,0,-.10]
            index=min(range(len(preferred)),key=lambda i:np.linalg.norm(points[i]-goal)+(5 if points[i,2]>low+.018 else 0));path,j,point,_=preferred[index];q=self.joint_q[self.cache.index(side+'_Foot')].copy();q/=np.linalg.norm(q);offset=quat_apply(inverse(q),point-ankle);self.soles[side]=Sole(path,j,offset,q)

    def soles_world(self):
        skin=self.skin_points(feet_only=True);m=np.asarray(self.matrix)
        return {side:skin[s.path][s.vertex]@m[:3,:3]+m[3,:3] for side,s in self.soles.items()}

    def feet_phrase_pose(self,pose,root,yaw,phrase,t,lift=0):
        """IK then sole-bone orientation, with bounded actual-skin refinement."""
        root=np.r_[root,0.];c,s=math.cos(yaw),math.sin(yaw);world_to_actor=np.array([[c,s,0],[-s,c,0],[0,0,1]])
        physical_p,physical_q=self.physical_pose(pose,lift);source=self.cache.anatomy.from_global(*pose);ledger={}
        for side,sole in self.soles.items():
            point,heading,planted,token=phrase.target(side,t);desired_q=quat_mul(axis_q([0,0,1],heading-yaw),sole.foot_q);target=(point-root)@world_to_actor.T-quat_apply(desired_q,sole.offset_bone)
            physical_p,physical_q=self.cache.foot_ik(physical_p,physical_q,side,target)
            foot=self.cache.index(side+'_Foot');delta=quat_mul(desired_q,inverse(physical_q[foot]));physical_p,physical_q=rotate_branch(self.cache,physical_p,physical_q,side+'_Foot',delta)
            ledger[side]={'point_goal_world_m':point.tolist(),'planted':planted,'support_id':token,'mesh_path':sole.path,'vertex_id':sole.vertex}
        local=self.cache.anatomy.from_global(physical_p,physical_q);local.translations[self.cache.anatomy.free]=source.translations[self.cache.anatomy.free]
        return self.cache.anatomy.forward(local),ledger


def bend_fingers(bank,p,q,side,amount):
    # Actual articulated fingers, not a rigid claw attached to the wrist.
    across=p[bank.index(side+'_Index1')]-p[bank.index(side+'_Pinky1')];across/=max(np.linalg.norm(across),1e-8)
    along=p[bank.index(side+'_Index2')]-p[bank.index(side+'_Index1')]
    sign=1 if quat_apply(axis_q(across,.2),along)[2]<quat_apply(axis_q(across,-.2),along)[2] else -1
    for digit in ['Index','Mid','Ring','Pinky']:
        for suffix,gain in [('1',.5),('2',.8),('3',.4)]:p,q=rotate_branch(bank,p,q,side+'_'+digit+suffix,axis_q(across,sign*amount*gain))
    return p,q


def grab_wrist(bank,p,q,side,weight):
    """Bounded pronation, keeping fingertips along the reaching forearm."""
    along=p[bank.index(side+'_Mid3')]-p[bank.index(side+'_Hand')];along/=max(np.linalg.norm(along),1e-8);across=p[bank.index(side+'_Index1')]-p[bank.index(side+'_Pinky1')];across-=along*(across@along);across/=max(np.linalg.norm(across),1e-8)
    desired=np.cross(along,np.array([0.,0.,-1. if side=='R' else 1.]));desired/=max(np.linalg.norm(desired),1e-8);angle=math.atan2(float(along@np.cross(across,desired)),float(across@desired));angle=float(np.clip(angle,-1.20,1.20))*weight
    return rotate_branch(bank,p,q,side+'_Hand',axis_q(along,angle))


class PerformanceLayer:
    def __init__(self,bank,actor,score,aid):
        self.bank=bank;self.actor=actor;self.score=score;self.aid=aid;self.feet=door_feet(score,aid) if aid in ['H01','F02'] else None
        ts=np.linspace(0,10,2001);xy=np.array([score.root(aid,t)[0] for t in ts]);self.ts=ts;self.distance=np.r_[0,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))]

    def travel(self,t):return float(np.interp(t,self.ts,self.distance))

    def evaluate(self,t):
        a=self.actor;b=self.bank;aid=self.aid;xy,yaw,speed=self.score.root(aid,t);distance=self.travel(t);phase=a.phase(distance,'final');pose=b.pose(phase,'final');lift=a.ground_lift('final',phase);p,q=pose;feet_weight=0.
        if self.score.state(aid,t)=='shared_destination':return pose,lift,{},0.,phase
        if aid=='H01':
            # Healthy decisions: brief glance, a short supported brake, then
            # turn chest/eyes toward the new landing before resuming travel.
            look=.48*window(t,4.35,4.68,.12);p,q=b.glance(p,q,-look)
            brake=window(t,4.45,5.55,.18);cut=window(t,5.20,6.15,.16)
            kp,kq=b.pose(0,'idle');kp[b.index('Hip'),2]-=.075*brake+.035*cut
            kp,kq=b.anatomy.forward(b.anatomy.from_global(kp,kq))
            kp,kq=rotate_branch(b,kp,kq,'Hip',axis_q([0,1,0],-.10*brake+.12*cut));kp,kq=rotate_branch(b,kp,kq,'Spine02',axis_q([0,0,1],.22*cut))
            kp,kq=reach(b,kp,kq,'R',[-.15+.35*cut,-.22,1.00+.10*cut]);kp,kq=reach(b,kp,kq,'L',[.04-.10*cut,.14+.20*cut,1.15-.13*cut]);kp,kq=b.glance(kp,kq,.22*cut)
            feet_weight=window(t,4.43,6.25,.16);p,q=b.mix((p,q),(kp,kq),feet_weight);lift=(1-feet_weight)*lift+feet_weight*a.ground_lift('idle',0)
            # Upper body is released again after the cut; arms swing normally.
        elif aid=='F02':
            # A complete phrase: hunted attention, braced stop, loaded shoulder,
            # committed reach, then two separate rescuing steps and late search.
            run=1-smooth((t-3.4)/.4);p,q=rotate_branch(b,p,q,'Spine01',axis_q([0,1,0],.15*run));p,q=rotate_branch(b,p,q,'NeckTwist01',axis_q([0,1,0],-.08*run))
            lock=window(t,.25,2.55,.17);p,q=b.glance(p,q,.48*lock)
            kp,kq=b.pose(0,'idle');brace=window(t,3.4,5.15,.18);lunge=window(t,5.05,6.40,.16);recover=window(t,6.10,7.65,.18);search=smooth((t-8.0)/.5)
            kp[b.index('Hip'),2]-=.075*brace+.13*lunge+.065*recover
            kp,kq=b.anatomy.forward(b.anatomy.from_global(kp,kq))
            tilt=.08*brace+.43*lunge+.18*recover;kp,kq=rotate_branch(b,kp,kq,'Hip',axis_q([0,1,0],tilt));kp,kq=rotate_branch(b,kp,kq,'Spine01',axis_q([0,1,0],.16*lunge));kp,kq=rotate_branch(b,kp,kq,'NeckTwist01',axis_q([0,1,0],-.10*lunge))
            kp,kq=rotate_branch(b,kp,kq,'Spine02',axis_q([0,0,1],-.20*window(t,4.55,5.30,.18)+.18*lunge))
            # No symmetric palms-up "shrug" while waiting or after a miss.
            # The low trailing right arm loads the shoulder, the other stays
            # forward; after recovery both arms lose their reach and drop.
            kp,kq=reach(b,kp,kq,'R',[-.12,-.21,.88]);kp,kq=reach(b,kp,kq,'L',[.16,.22,.98])
            # Draw elbow back before the hand fires; both shoulders participate.
            wind=window(t,4.50,5.08,.16);windpose=reach(b,kp,kq,'R',[-.15,-.28,1.09]);kp,kq=b.mix((kp,kq),windpose,wind)
            target=self.score.attack_target(max(t,self.score.commit_t));target=target.copy();root=np.r_[xy,0.];c,s=math.cos(yaw),math.sin(yaw);v=target-root;goal=np.array([c*v[0]+s*v[1],-s*v[0]+c*v[1],v[2]])
            reach_weight=window(t,5.12,6.25,.18);left_weight=window(t,5.24,6.45,.18)
            rp=a.physical_ik((kp,kq),'R',goal,lift=a.ground_lift('idle',0));kp,kq=b.mix((kp,kq),rp,reach_weight)
            lp=a.physical_ik((kp,kq),'L',goal+[.02,.14,-.12],lift=a.ground_lift('idle',0));kp,kq=b.mix((kp,kq),lp,left_weight*.83)
            for side,w in [('R',reach_weight),('L',left_weight)]:kp,kq=grab_wrist(b,kp,kq,side,w);kp,kq=bend_fingers(b,kp,kq,side,.85*w)
            # The hand stays extended during the first recovery step; it is
            # not magnetically retargeted after the heroine's cut.
            kp,kq=b.glance(kp,kq,-.85*search+.28*window(t,7.8,8.5,.2));kp,kq=rotate_branch(b,kp,kq,'JawRoot',axis_q([0,1,0],.10+.18*lunge))
            feet_weight=smooth((t-3.38)/.24);p,q=b.mix((p,q),(kp,kq),feet_weight);lift=(1-feet_weight)*lift+feet_weight*a.ground_lift('idle',0)
        elif aid=='F01':
            search=window(t,4.2,6.4,.16);p,q=b.mix((p,q),b.pose(0,'idle'),search);lift=(1-search)*lift+search*a.ground_lift('idle',0);p,q=b.glance(p,q,.8*window(t,4.5,5.2,.12)-.9*window(t,5.8,6.4,.14))
        ledger={}
        if feet_weight>.001 and self.feet:
            planted,ledger=a.feet_phrase_pose((p,q),xy,yaw,self.feet,t,lift)
            p,q=b.mix((p,q),planted,feet_weight)
            for v in ledger.values():v['support_is_full_weight']=feet_weight>.999
        return (p,q),lift,ledger,feet_weight,phase
