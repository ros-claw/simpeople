"""Director's cut: normal anatomy first, transient infected performance second."""
import json
import math
from pathlib import Path

import numpy as np

from .deadweight_cinema import FilmPoseCache, quat_apply, quat_mul
from .local_pose import FixedAnatomy,LocalPose
from .platform04_animation import MetroActor, axis_q, rotate_branch, fit_stride,reach


def canonical_capture(run,logname='frames.jsonl'):
    rows=[json.loads(x) for x in (run/logname).read_text().splitlines()]
    data=np.load(run/'native_bones.npz')
    heading=np.arctan2([r['facing_direction'][1] for r in rows],
                       [r['facing_direction'][0] for r in rows])
    turn=np.zeros((len(rows),4));turn[:,2]=np.sin(-heading/2);turn[:,3]=np.cos(heading/2)
    p=quat_apply(turn[:,None],data['positions']-np.array([r['position_m'] for r in rows])[:,None])
    q=quat_mul(turn[:,None],data['rotations'])
    return p,q


def pulse(t,start,duration):
    u=float(np.clip((t-start)/duration,0,1))
    return math.sin(math.pi*u)**2 if 0<u<1 else 0.


class DirectorMotion(FilmPoseCache):
    """No world-point blending, .36 stride compression or constant hooked arm."""
    def __init__(self,root):
        root=Path(root);sdk=root/'runs/platform04-motion-01';jog=root/'runs/platform04-90-jog-02'
        self.rig=json.loads((sdk/'rig.json').read_text());self.names=self.rig['joints']
        self.parents=[self.names.index(n.rsplit('/',1)[0]) if '/' in n else -1 for n in self.names]
        self.parent_indices=np.array(self.parents);depth=[]
        for p in self.parents:depth.append(0 if p<0 else depth[p]+1)
        self.levels=[np.flatnonzero(np.array(depth)==d) for d in range(1,max(depth)+1)]
        self.toes=[self.index(s+'_ToeBase') for s in ['L','R']]
        p,q=canonical_capture(sdk);self.anatomy=FixedAnatomy(self.names,p[45],q[45])
        self.banks={'sdk':[self.anatomy.from_global(p[k],q[k]) for k in range(45,62)],
                    'old_infected':[self.anatomy.from_global(p[k],q[k]) for k in range(135,152)],
                    'idle':[self.anatomy.from_global(p[295],q[295])],
                    'crouch':[self.anatomy.from_global(p[k],q[k]) for k in range(205,258)]}
        assert json.loads((jog/'rig.json').read_text())['joints']==self.names
        jp,jq=canonical_capture(jog);legs=[i for i,n in enumerate(self.names) if any(x in n for x in ['Thigh','Calf','Foot','Toe'])]
        from scipy.signal import find_peaks
        difference=jp[:,self.index('L_Foot'),0]-jp[:,self.index('R_Foot'),0];peaks=find_peaks(difference,distance=22,prominence=.25)[0];stable=[]
        for start,end in zip(peaks,peaks[1:]):
            closure=float(np.linalg.norm(jp[end]-jp[start],axis=1).max())
            if start>=120 and closure<.008:stable.append((int(start),int(end),closure))
        if not stable:raise ValueError('no stable complete same-side Native Jog cycle')
        start,end,closure=stable[-1];self.jog_period=end-start;overlap=min(self.jog_period,len(jp)-end);self.jog_loop_error_m=float(np.abs(jp[start:start+overlap,legs]-jp[end:end+overlap,legs]).mean())
        # Integer-frame phase extrema have a one-sample timing uncertainty.
        # Check the actual wrap boundary separately (above, <=8 mm); comparing
        # the next half-cycle is a drift diagnostic, not a 3 mm repeatability
        # requirement for independently sampled native motion.
        if self.jog_loop_error_m>.020:raise ValueError('Native Jog overlap drifts by more than 20 mm')
        self.jog_calibration={'start_source_tick':start,'end_source_tick_exclusive':end,'period_frames':self.jog_period,'same_side_extrema_ticks':peaks.tolist(),'overlap_frames':overlap,'overlap_mean_leg_error_m':self.jog_loop_error_m,'max_cycle_boundary_joint_error_m':closure,'scope':'same-side L-minus-R ankle maxima define a full alternating cycle; not a contact-force measurement'}
        self.banks['jog']=[self.anatomy.from_global(jp[k],jq[k]) for k in range(start,end)]
        walk=root/'runs/deadweight-zombie-probe-05'
        assert json.loads((walk/'cache_rig.json').read_text())['joints']==self.names
        wp,wq=canonical_capture(walk,'zombie_frames.jsonl')
        self.banks['walk']=[self.anatomy.from_global(wp[k],wq[k]) for k in range(42,84)]
        self.clips={name:(0,len(value)) for name,value in self.banks.items()}
        self.clips.update({name:(0,17) for name in ['leg_ik','old_leg_ik','gaze']})
        self.clips.update({name:(0,self.jog_period) for name in ['infected','final']})
        self.clips['sprint']=(0,17)

    def pose(self,frame,action='idle'):
        source='sdk' if action in ['sprint','leg_ik','old_leg_ik','gaze'] else 'jog' if action in ['infected','final'] else action
        bank=self.banks[source];phase=float(frame)%len(bank);i=int(phase)
        local=self.anatomy.blend(bank[i],bank[(i+1)%len(bank)],phase-i)
        p,q=self.anatomy.forward(local)
        if action=='old_leg_ik':
            p,q=fit_stride(self,p,q,.36)
        if action=='leg_ik':
            # An isolated, bounded plant correction for diagnosis. It never
            # compresses stride or lifts the ankle trajectory toward the hip.
            for side in ['L','R']:
                foot=self.index(side+'_Foot')
                if p[foot,2]<.15:
                    p,q=self.foot_ik(p,q,side,p[foot]+np.array([.012,0,-.006]))
        if action=='infected':
            # Preserve ordinary reciprocal arm swing. The extra reach is a
            # short beat, rather than a fixed hand target for the whole run.
            u=phase/len(bank);weight=math.sin(math.pi*np.clip((u-.16)/.34,0,1))**2
            p,q=rotate_branch(self,p,q,'R_Upperarm',axis_q([0,1,0],-.17*weight))
            p,q=rotate_branch(self,p,q,'NeckTwist01',axis_q([1,0,0],.10*weight))
        if action=='gaze':
            weight=math.sin(math.pi*np.clip((phase/17-.22)/.42,0,1))**2
            p,q=self.glance(p,q,.70*weight)
        return p,q

    def mix(self,a,b,weight):
        a=self.anatomy.from_global(*a);b=self.anatomy.from_global(*b)
        return self.anatomy.forward(self.anatomy.blend(a,b,float(np.clip(weight,0,1))))

    def glance(self,p,q,angle):
        angle=float(np.clip(angle,-.95,.95))
        p,q=rotate_branch(self,p,q,'Spine02',axis_q([0,0,1],angle*.12))
        p,q=rotate_branch(self,p,q,'NeckTwist01',axis_q([0,0,1],angle*.76))
        for side in ['L','R']:
            p,q=rotate_branch(self,p,q,side+'_Eye',axis_q([0,0,1],angle*.12))
        return p,q

    def foot_ik(self,p,q,side,target):
        p=p.copy();q=q.copy();j,k,l=[self.index(side+'_'+s) for s in ['Thigh','Calf','Foot']]
        start=p[j].copy();a=np.linalg.norm(p[k]-start);b=np.linalg.norm(p[l]-p[k]);v=np.asarray(target)-start;distance=np.clip(np.linalg.norm(v),abs(a-b)+.004,a+b-.004);direction=v/np.linalg.norm(v)
        pole=p[k]-start;pole-=direction*(pole@direction);pole/=max(np.linalg.norm(pole),1e-8)
        if np.linalg.norm(pole)<.1:
            pole=np.array([1.,0,0])-direction*direction[0];pole/=max(np.linalg.norm(pole),1e-8)
        along=(a*a+distance*distance-b*b)/(2*distance);knee=start+direction*along+pole*math.sqrt(max(0,a*a-along*along))
        for bone,child,goal in [(side+'_Thigh',k,knee),(side+'_Calf',l,start+direction*distance)]:
            origin=p[self.index(bone)];v=p[child]-origin;w=goal-origin;v/=np.linalg.norm(v);w/=np.linalg.norm(w);axis=np.cross(v,w);length=np.linalg.norm(axis)
            if length>1e-8:p,q=rotate_branch(self,p,q,bone,axis_q(axis,math.atan2(length,float(v@w))))
        return p,q


class DirectorActor(MetroActor):
    def physical_pose(self,pose,lift=0):
        local=self.cache.anatomy.from_global(*pose);translations=local.translations*self.length_ratio[:,None];translations[0,2]+=lift;return self.cache.anatomy.forward(LocalPose(translations,local.rotations))

    def physical_ik(self,pose,side,target,*,lift=0,foot=False):
        source=self.cache.anatomy.from_global(*pose);physical=self.physical_pose(pose,lift)
        p,q=(self.cache.foot_ik(*physical,side,target) if foot else reach(self.cache,*physical,side,target));local=self.cache.anatomy.from_global(p,q);local.translations[self.cache.anatomy.free]=source.translations[self.cache.anatomy.free];return self.cache.anatomy.forward(local)

    def fit(self,action):
        if action!='walk':return super().fit(action)
        if action in self.fits:return self.fits[action]
        # Walking has no flight phase. Reusing the sprint fitter had left the
        # entire walk above its support tolerance and produced no plant samples.
        # Ground the actual lowest shoe for this walking clip, keeping every
        # long bone fixed; sprint/Jog continue to retain their flight phases.
        period=self.cache.clips[action][1];feet=[];lifts=[]
        for k in range(period):
            self.safe_update(self.cache.pose(k,action),[0,0,0]);cloud=self.foot_points();lifts.append(.003-min(float(v[:,2].min()) for v in cloud.values()))
        for k in range(period):
            self.safe_update(self.cache.pose(k,action),[0,0,0],lift=lifts[k]);feet.append(self.foot_points())
        dx=np.full(period,np.nan);support=[]
        for k in range(period):
            candidates=[]
            for side in ['L','R']:
                a,b=feet[k][side],feet[(k+1)%period][side];mask=(a[:,2]<.035)&(b[:,2]<.045)
                if mask.sum()>2:
                    delta=float(np.median(a[mask,0]-b[mask,0]))
                    if delta>0:candidates.append((delta,side))
            if candidates:dx[k],side=max(candidates);support.append(side)
            else:support.append(None)
        known=np.flatnonzero(np.isfinite(dx))
        if not len(known):raise ValueError('walking has no measured backwards plant motion')
        dx=np.interp(np.arange(period),np.r_[known-period,known,known+period],np.tile(dx[known],3));travel=np.r_[0,np.cumsum(dx)];result={'period':period,'feet':feet,'lifts':np.array(lifts),'travel':travel,'support':support,'stride_m':float(travel[-1]),'flight_frames':0,'scope':'walk-only actual shoe grounding; flight preservation is used for Jog/Sprint'};self.fits[action]=result;return result

    def safe_update(self,pose,position,heading=0,lift=0):
        # Reconstruct from local rotations after optional movie IK, preventing
        # any later transition from silently reintroducing shortened limbs.
        p,q=self.cache.anatomy.forward(self.cache.anatomy.from_global(*pose))
        self.update(p,q,position,heading,lift=lift)
