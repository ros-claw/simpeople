"""First-round formal performances for the 90-second director's cut.

These are cache-owned cinematic performances, never Native pursuit claims.
"""
import json,math
from pathlib import Path
import numpy as np
from pxr import Usd,UsdGeom,UsdSkel,Gf
from .platform04_90_animation import DirectorMotion,DirectorActor,pulse
from .platform04_animation import axis_q,rotate_branch,reach
from .platform04_90_scene import ShoulderBag,FloorBag,ribbon
from .platform04_scene import aim
from .deadweight_cinema import quat_apply


def smooth(x):
    x=float(np.clip(x,0,1));return x*x*(3-2*x)


def yaw_mix(a,b,u):return a+((b-a+math.pi)%(2*math.pi)-math.pi)*smooth(u)


def hermite(a,b,va,vb,u,duration):
    u=float(np.clip(u,0,1));a,b,va,vb=map(np.asarray,[a,b,va,vb]);p=(2*u**3-3*u*u+1)*a+(u**3-2*u*u+u)*duration*va+(-2*u**3+3*u*u)*b+(u**3-u*u)*duration*vb;v=(6*u*u-6*u)/duration*a+(3*u*u-4*u+1)*va+(-6*u*u+6*u)/duration*b+(3*u*u-2*u)*vb;return p,float(math.atan2(v[1],v[0]))


def close_fingers(cache,p,q,side,target):
    across=p[cache.index(side+'_Index1')]-p[cache.index(side+'_Pinky1')];across/=np.linalg.norm(across);v=p[cache.index(side+'_Index2')]-p[cache.index(side+'_Index1')];desired=np.asarray(target)-p[cache.index(side+'_Index1')];sign=1 if quat_apply(axis_q(across,.2),v)@desired>quat_apply(axis_q(across,-.2),v)@desired else -1
    for digit in ['Index','Mid','Ring','Pinky']:
        for suffix,amount in [('1',.40),('2',.65),('3',.35)]:p,q=rotate_branch(cache,p,q,side+'_'+digit+suffix,axis_q(across,sign*amount))
    return p,q


class Director90:
    MODES={'opening':['H01','H02','H03'],
           'character':['A03','A01','A02','L01','L02','L03','L04','L05','L06'],
           'door':['H01','H02','H03','F01','F02','F03','P01','P02','P03']}
    CAST={'H01':0,'H02':9,'H03':4,'F01':9,'F02':3,'F03':7,'F04':10,'F05':2,
          'L01':0,'L02':6,'L03':1,'L04':8,'L05':4,'L06':5,
          'P01':6,'P02':1,'P03':8,'P04':7,'P05':5,'P06':3,
          'A01':2,'A02':0,'A03':10,'A04':1}
    COLORS={'H01':(.76,.43,.055),'H02':(.025,.33,.34),'H03':(.11,.29,.21),
            'F01':(.74,.76,.70),'F02':(.48,.048,.025),'F03':(.12,.16,.15),
            'A01':(.13,.18,.23),'A02':(.27,.27,.23),'A03':(.27,.23,.19)}
    def __init__(self,stage,scene,root,out,mode):
        self.stage=stage;self.scene=scene;self.root=Path(root);self.out=Path(out);self.mode=mode;self.bank=DirectorMotion(root);self.actors={};self.bags={};self.actor_state={};self.sway_foot_world=None;assets=json.loads((self.root/'configs/assets.json').read_text())['assets']
        self.opening=Usd.Stage.Open(str(self.root/'.runtime/platform04_90/kit/layout/OPEN_0_9s.usda'));self.source_camera=UsdGeom.Camera.Get(self.opening,'/Opening/Cameras/PROGRAM_0_9s')
        for number,aid in enumerate(self.MODES[mode]):
            asset=assets[self.CAST[aid]];color=self.COLORS.get(aid,[(.21,.25,.28),(.29,.24,.17),(.17,.25,.22),(.32,.29,.24),(.26,.16,.17),(.18,.23,.30)][number%6]);source=self.root/'assets/characters'/asset['source_uri'].removeprefix('characters://');a=DirectorActor(stage,'/World/Cast/'+aid,self.bank,color,str(source));self.actors[aid]=a
            for action in ['idle','walk','final']+(['crouch'] if aid in ['A03','F03'] else []):a.fit(action)
            if aid in ['H01','H02']:self.bags[aid]=ShoulderBag(stage,a,(.63,.39,.065) if aid=='H01' else (.10,.16,.16))
        if 'A03' in self.actors:self.floorbag=FloorBag(stage,self.actors['A03'])
        self.distance_tables={};times=np.linspace(0,90,9001)
        for aid in self.actors:
            if mode=='door':start,end=53,63
            elif mode=='character':start,end=9,21
            else:start,end=0,9
            ts=np.linspace(start,end,round((end-start)*100)+1);xy=np.array([self.root_pose(aid,t)[0] for t in ts]);self.distance_tables[aid]=(ts,np.r_[0,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))])
        score=json.loads((self.root/'.runtime/platform04_90/kit/cast/cast_score_90s.json').read_text());(self.out/'casting.json').write_text(json.dumps({'mode':mode,'actual_instances':len(self.actors),'full_90s_roster_is_plan_only':24,'actors':{aid:{'asset_id':assets[self.CAST[aid]]['asset_id'],'base_asset_index':self.CAST[aid],'controller':'exclusive local-rotation cinematic cache','infection_layer':False if aid.startswith('H') else 'event-based performance'} for aid in self.actors},'planned_id_alias':{a['id']:a['identity'] for a in score['actors']}},ensure_ascii=False,indent=2))

    def root_pose(self,aid,t):
        if self.mode=='opening':
            if aid=='H01':
                prim=self.opening.GetPrimAtPath('/Opening/BlockingGuides/Hero_YellowBag');xy=np.array(UsdGeom.XformCache(Usd.TimeCode(t*30)).GetLocalToWorldTransform(prim).ExtractTranslation())[:2];return xy,.28
            if aid=='H02':
                prim=self.opening.GetPrimAtPath('/Opening/BlockingGuides/Companion_Teal');xy=np.array(UsdGeom.XformCache(Usd.TimeCode(t*30)).GetLocalToWorldTransform(prim).ExtractTranslation())[:2];return xy,yaw_mix(.32,-2.82,(t-3.7)/1.4)
            return np.array([27.4,8.32]),-2.82
        if self.mode=='character':
            if aid=='A03':return np.array([5.8,7.22]),-.65
            if aid=='A01':return np.array([18.40+.12*smooth((t-13.0)/1.4),7.36]),-math.pi/2
            if aid=='A02':return np.array([20.20,-1.44+.13*math.sin((t-15)*1.9)]),math.pi/2
            i=int(aid[1:])-1;dt=t-9;start=np.array([14+(i//2)*2.3+(.42 if i%2 else 0),2.7+(i%2)*.62]);start[0]-=.48 if i==0 else 0;return start+np.array([.13*dt,.035*math.sin(dt*.7+i)+(.12*pulse(t,19.4,1.3) if i==5 else 0)]),.04*math.sin(dt*.6+i)
        # A ten-second continuous traversal, physically inside a 48m platform.
        # Main speeds are 2.8–3.5m/s. No old world-point interpolation is used.
        u=t-53
        if aid=='H01':
            if u<4.7:return np.array([8.2+2.80*u,1.82]),0.
            if u<6.3:return hermite([21.36,1.82],[24.2,2.8],[2.8,0],[.8,1.0],(u-4.7)/1.6,1.6)
            v=u-6.3
            # Shallow, late sidestep: pass west of the pillar, accelerate north.
            d=max(0,v-.6);a=min(1,d/1.2);integral=1.2*(a**3-.5*a**4)+max(0,d-1.2);north_speed=1-.5*smooth(d/1.2);x=24.2+.42*(1-math.exp(-v/.525));y=2.8+v-.5*integral
            return np.array([x,y]),math.atan2(north_speed,.8*math.exp(-v/.525))
        if aid=='F02':
            if u<3.4:return np.array([4.9+4.5*u,-1.35]),0.
            if u<4.35:return hermite([20.2,-1.35],[22.33,-1.35],[4.5,0],[0,0],(u-3.4)/.95,.95)
            if u<=5.0:return np.array([22.33,-1.35]),yaw_mix(0.,math.atan2(10.528,3.2576),(u-4.35)/.65)
            if u<6.25:return hermite([22.33,-1.35],[23.72,2.1],[0,0],[1.30,1.70],(u-5.0)/1.25,1.25)
            v=u-6.25;return np.array([23.72+.45*(1-math.exp(-v/(.45/1.3))),2.1+1.2*(1-math.exp(-v/(1.2/1.7)))]),math.atan2(1.7*math.exp(-v/(1.2/1.7)),1.3*math.exp(-v/(.45/1.3)))
        if aid=='F01':
            if u<6.0:
                a=float(np.clip((u-3.5)/2.5,0,1));dy=2.5*(6*a-6*a*a)/2.5;return np.array([4.35+2.88*u,2.05+2.5*smooth((u-3.5)/2.5)]),math.atan2(dy,2.88)
            v=u-6.;a=min(1,v/.8);integral=.8*(a**3-.5*a**4)+max(0,v-.8);x=21.63+2.88*v-1.23*integral;y=4.55+.18*smooth(v/1.4)-.10*(1-math.cos(v));dy=.18*(6*min(1,v/1.4)-6*min(1,v/1.4)**2)/1.4-.1*math.sin(v);return np.array([x,y]),math.atan2(dy,2.88-1.23*smooth(v/.8))
        if aid=='F03':return np.array([25.30,6.44]),-1.75
        if aid=='H02':return np.array([28.3,7.0]),-2.3
        if aid=='H03':return np.array([27.4,8.32]),-2.8
        i=int(aid[1:])-1;return np.array([3.0+2.55*max(0,u-.55*i),5.05+.76*i]),.03

    def motion(self,aid,t):
        xy,yaw=self.root_pose(aid,t);eps=.005;a=self.root_pose(aid,max(0,t-eps))[0];b=self.root_pose(aid,t+eps)[0];speed=float(np.linalg.norm(b-a)/(.01 if t>=eps else .005));ts,ds=self.distance_tables[aid];distance=float(np.interp(t,ts,ds));gait='final' if self.mode=='door' and aid not in ['H02','H03','F03'] else 'walk';actor=self.actors[aid];phase=actor.phase(distance,gait);weight=smooth((speed-.025)/(.55 if gait=='walk' else 1.1));pose=self.bank.mix(self.bank.pose(0,'idle'),self.bank.pose(phase,gait),weight);lift=actor.ground_lift('idle',0)*(1-weight)+actor.ground_lift(gait,phase)*weight
        if self.mode=='character' and aid.startswith('L'):
            # A slow actor must advance the full fitted walk at a slow phase.
            # Blending 90% Idle while using the full walk's distance/phase
            # suppresses the legs and visibly slides the translated body.
            offsets=[.03,.42,.67,.19,.85,.51];phase=actor.phase(distance+offsets[int(aid[1:])-1]*actor.fit('walk')['stride_m'],'walk')
            pose=self.bank.pose(phase,'walk');lift=actor.ground_lift('walk',phase)
        if self.mode=='door' and aid in ['H01','F01','F02']:
            # Deceleration changes distance-driven phase speed. Do not dilute
            # the fitted leg excursion with Idle while translating the root.
            weight=smooth((speed-.025)/.12)
            pose=self.bank.mix(self.bank.pose(0,'idle'),self.bank.pose(phase,gait),weight)
            lift=actor.ground_lift('idle',0)*(1-weight)+actor.ground_lift(gait,phase)*weight
        return xy,yaw,speed,distance,gait,phase,pose,lift

    def update(self,f):
        t=f/30.;result={'source_tick':f,'story_time_s':t,'mode':self.mode,'actors':{},'events':[]}
        for number,(aid,actor) in enumerate(self.actors.items()):
            xy,yaw,speed,distance,gait,phase,pose,lift=self.motion(aid,t);p,q=pose
            if self.mode=='opening':
                if aid=='H01':
                    second_sound=pulse(t,8.10,.85);physical,_=actor.physical_pose((p,q),lift);anchor=physical[self.bank.index('L_Upperarm')]+[.015,.055,-.13+.045*second_sound];p,q=actor.physical_ik((p,q),'L',anchor,lift=lift)
                    across=p[self.bank.index('L_Index1')]-p[self.bank.index('L_Pinky1')];across/=np.linalg.norm(across);v=p[self.bank.index('L_Index2')]-p[self.bank.index('L_Index1')];desired=anchor-p[self.bank.index('L_Index1')];sign=1 if np.dot(quat_apply(axis_q(across,.2),v),desired)>np.dot(quat_apply(axis_q(across,-.2),v),desired) else -1
                    for digit in ['Index','Mid','Ring','Pinky']:
                        for bone,amount in [('1',.40),('2',.65),('3',.35)]:p,q=rotate_branch(self.bank,p,q,'L_'+digit+bone,axis_q(across,sign*amount))
                    listen=smooth((t-7.28)/.65);p,q=self.bank.glance(p,q,.88*listen-.14*smooth((t-8.15)/.45)+.04*smooth((t-8.65)/.25));p,q=rotate_branch(self.bank,p,q,'NeckTwist01',axis_q([1,0,0],.08*second_sound))
                    for s in ['L','R']:p,q=rotate_branch(self.bank,p,q,s+'_Eye',axis_q([0,0,1],.13*smooth((t-7.08)/.20)*(1-smooth((t-7.5)/.3))))
                elif aid=='H02':
                    beckon=pulse(t,4.05,1.95);p,q=reach(self.bank,p,q,'R',[.27,-.22,1.20+.17*beckon]);p,q=self.bank.glance(p,q,.25*beckon)
                else:
                    p,q=reach(self.bank,p,q,'L',[.20,.16,1.12]);p,q=reach(self.bank,p,q,'R',[.27,-.20,1.39+.12*math.sin(t*3.4)]);p,q=rotate_branch(self.bank,p,q,'R_Hand',axis_q([0,1,0],.7+.25*math.sin(t*3.4)));p,q=rotate_branch(self.bank,p,q,'Hip',axis_q([1,0,0],.025*math.sin(t*1.1)))
            elif self.mode=='character':
                if aid=='A03':
                    p,q=self.bank.pose(20,'crouch');lift=actor.ground_lift('crouch',20);p,q=rotate_branch(self.bank,p,q,'Spine01',axis_q([0,1,0],.32));p,q=actor.physical_ik((p,q),'L',[.27,.08,.28],lift=lift);physical,_=actor.physical_pose((p,q),lift);mouth=physical[self.bank.index('Head')]+[.075,0,-.055];p,q=actor.physical_ik((p,q),'R',mouth+[.01,-.06,-.25],lift=lift);bite=1-smooth((t-11.0)/.65);p,q=rotate_branch(self.bank,p,q,'JawRoot',axis_q([0,1,0],.13+.075*math.sin(t*14)*bite));p,q=self.bank.glance(p,q,.55*smooth((t-10.5)/.65));p,q=rotate_branch(self.bank,p,q,'NeckTwist01',axis_q([0,1,0],.05*math.sin(t*12)*bite))
                elif aid=='A01':
                    angle=.70*pulse(t,11.8,1.45)-.60*pulse(t,13.3,1.45);p,q=self.bank.glance(p,q,angle);p,q=reach(self.bank,p,q,'L',[.12,.17,1.30+.06*math.sin(t*2)]);p,q=rotate_branch(self.bank,p,q,'Spine02',axis_q([0,0,1],.12*smooth((t-13.4)/.6)))
                elif aid=='A02':
                    base,_=actor.physical_pose((p,q),lift);c,s=math.cos(yaw),math.sin(yaw);rotation=np.array([[c,s,0],[-s,c,0],[0,0,1]])
                    if self.sway_foot_world is None:self.sway_foot_world=base[self.bank.index('R_Foot')]@rotation+[*xy,0]
                    foot=(self.sway_foot_world-[*xy,0])@rotation.T;sway=.11*math.sin((t-15)*1.9)+.045*math.sin((t-15)*3.3);p,q=rotate_branch(self.bank,p,q,'Hip',axis_q([1,0,0],sway));p[self.bank.index('Hip'),2]-=.025;local=self.bank.anatomy.from_global(p,q);p,q=self.bank.anatomy.forward(local);p,q=actor.physical_ik((p,q),'R',foot,lift=lift,foot=True);goal=np.array([20.20-xy[0],-1.39-xy[1],1.74]);goal=goal@rotation.T;p,q=actor.physical_ik((p,q),'L',goal,lift=lift);p,q=close_fingers(self.bank,p,q,'L',goal+[-.05,0,.07-lift]);p,q=reach(self.bank,p,q,'R',[.17,-.18,1.29+.25*pulse(t,16.4,1.5)]);p,q=self.bank.glance(p,q,.18*math.sin(t*1.3))
                else:
                    i=int(aid[1:])-1;dt=t-9;w=.5+.5*math.sin(dt*1.9+i*1.17);other=.5+.5*math.sin(dt*1.37+i*.81+.7)
                    if i==0:p,q=reach(self.bank,p,q,'R',[.23,.14,1.10+.12*w]);p,q=actor.physical_ik((p,q),'L',[.35,.32,1.12],lift=lift)
                    elif i==1:p,q=reach(self.bank,p,q,'R',[-.08,-.23,1.13]);p,q=reach(self.bank,p,q,'L',[.34,.05,1.25+.12*other])
                    elif i==2:p,q=reach(self.bank,p,q,'L',[.26,.34,1.34+.15*w])
                    elif i==3:
                        for side,sign in [('L',1),('R',-1)]:p,q=reach(self.bank,p,q,side,[.10,sign*.23,1.53+.06*w])
                    elif i==4:p,q=reach(self.bank,p,q,'L',[.16,.40,1.19+.22*w])
                    else:p,q=reach(self.bank,p,q,'R',[.25,-.37,1.11+.10*w]);p,q=rotate_branch(self.bank,p,q,'Hip',axis_q([1,0,0],.07*math.sin(dt*1.5+.4)))
                    p,q=self.bank.glance(p,q,.20*math.sin(dt*.65+i))
            else:
                u=t-53
                if aid=='H01':
                    angle=.74*pulse(u,.7,.65)-.72*pulse(u,4.55,.65);p,q=self.bank.glance(p,q,angle)
                    if u>4.8:p,q=rotate_branch(self.bank,p,q,'Spine01',axis_q([0,1,0],-.08*pulse(u,4.8,1.6)))
                elif aid=='F02':
                    target=self.root_pose('H01',t)[0];delta=target-xy;angle=float(np.clip((math.atan2(delta[1],delta[0])-yaw+math.pi)%(2*math.pi)-math.pi,-1.60,1.60))
                    p,q=rotate_branch(self.bank,p,q,'Spine02',axis_q([0,0,1],angle*.22));p,q=rotate_branch(self.bank,p,q,'NeckTwist01',axis_q([0,0,1],angle*.64))
                    for side in ['L','R']:p,q=rotate_branch(self.bank,p,q,side+'_Eye',axis_q([0,0,1],angle*.14))
                    attack=pulse(u,5.5,1.7)
                    p,q=rotate_branch(self.bank,p,q,'Spine01',axis_q([0,1,0],.08*attack));hero=self.actors['H01'];hm=np.asarray(hero.matrix);point=(hero.joint_p[self.bank.index('Spine02')]+[0,0,.03])@hm[:3,:3]+hm[3,:3];away=np.r_[xy-self.root_pose('H01',t)[0],0.];away/=max(np.linalg.norm(away),1e-8);point+=away*.43;v=point-[*xy,0];c,s=math.cos(yaw),math.sin(yaw);goal=np.array([c*v[0]+s*v[1],-s*v[0]+c*v[1],v[2]]);target=actor.physical_ik((p,q),'R',goal,lift=lift);p,q=self.bank.mix((p,q),target,attack);p,q=rotate_branch(self.bank,p,q,'JawRoot',axis_q([0,1,0],.09+.06*attack))
                elif aid=='F03':
                    rise=smooth((t-65.5)/1.1);p,q=self.bank.mix(self.bank.pose(20,'crouch'),self.bank.pose(0,'idle'),rise);lift=actor.ground_lift('crouch',20)*(1-rise)+actor.ground_lift('idle',0)*rise;p,q=reach(self.bank,p,q,'L',[.19,.16,.69]);p,q=self.bank.glance(p,q,.22*math.sin(u*.7))
                elif aid in ['H02','H03']:
                    p,q=reach(self.bank,p,q,'R',[.32,-.18,1.28+.10*math.sin(u*2.4)]);p,q=self.bank.glance(p,q,.35*math.sin(u*.7))
                else:
                    p,q=self.bank.glance(p,q,.27*pulse(u,2.3+number*.15,.8))
            # Breathing changes the chest and shoulder masses, not white noise.
            p,q=rotate_branch(self.bank,p,q,'Spine02',axis_q([0,1,0],.012*math.sin(t*2.2+number*.7)))
            actor.safe_update((p,q),[*xy,0],yaw,lift)
            ground_adjustment=0.
            if self.mode=='door' and aid in ['H01','F01','F02']:
                shoe_min=min(float(v[:,2].min()) for v in actor.foot_points().values())
                ground_adjustment=max(0.,.003-shoe_min)
                if ground_adjustment>.06:raise ValueError(f'excessive shoe grounding correction {aid}: {ground_adjustment}')
                if ground_adjustment:lift+=ground_adjustment;actor.safe_update((p,q),[*xy,0],yaw,lift)
            if aid=='A03':self.floorbag.update(t,1-smooth((t-11.0)/.65))
            if aid=='L05':
                hand=actor.joint_p[self.bank.index('L_Hand')];ribbon(self.stage,actor.path+'/Scarf',[hand,hand+[.22,.09,.02],hand+[.42,.14,-.05],hand+[.60,.12+.12*math.sin(t*3),-.16]],.055,(.39,.22,.18))
            result['actors'][aid]={'root_world_m':[*xy,0],'yaw_rad':yaw,'speed_mps':speed,'gait':gait,'phase':phase,'ground_adjustment_m':ground_adjustment,'behavior':('chew' if aid=='A03' else 'watch' if aid in ['A01','H03'] else 'slow_group' if aid.startswith('L') else 'run' if self.mode=='door' and speed>.7 else 'walk'),'infection_layer':not aid.startswith('H'),'purpose':{'opening':'walk together to visible gate; react to offscreen strap noise','character':'individual object/listening/partner performance','door':'escape/intercept/recovery'}[self.mode]}
        if self.mode=='opening':
            time=Usd.TimeCode(f);matrix=UsdGeom.XformCache(time).GetLocalToWorldTransform(self.source_camera.GetPrim());camera=UsdGeom.Camera.Get(self.stage,'/World/Camera');UsdGeom.Xformable(camera).GetOrderedXformOps()[0].Set(matrix)
            for name in ['focalLength','horizontalAperture','verticalAperture']:camera.GetPrim().GetAttribute(name).Set(self.source_camera.GetPrim().GetAttribute(name).Get(time))
            result['shot']='C01' if f<120 else 'C02' if f<210 else 'C03'
        elif self.mode=='character':
            if t<12:aim(self.stage,[7.3,4.9,1.0],[5.95,7.15,.58],54);result['shot']='C04'
            elif t<15:aim(self.stage,[17.90+1.25*smooth((t-12)/3),4.10,1.53],[18.42,7.30,1.32],42);result['shot']='C05'
            elif t<18:aim(self.stage,[23.55,-.65,1.25],[20.20,-1.44,1.0],60);result['shot']='C06'
            else:aim(self.stage,[18.6,7.0,1.65],[18.2,3.25,1.05],82);result['shot']='C07'
        else:
            xy=result['actors']['H01']['root_world_m'];u=t-53;retreat=smooth((u-7.20)/2.8);x=min(21.4,xy[0]+.5-2.9*smooth(u/4.5))+5.8*retreat;y=6.8+1.5*retreat;target=[min(23.6,xy[0]),1.30,1.05];target=(np.array(target)*(1-retreat)+(np.array(xy)+[0,0,1.0])*retreat).tolist();aim(self.stage,[x,y,1.75],target,78);result['shot']='C16'
        camera=self.stage.GetPrimAtPath('/World/Camera');result['camera_matrix']=np.asarray(UsdGeom.Xformable(camera).GetOrderedXformOps()[0].Get()).tolist();result['camera_focal_mm']=float(camera.GetAttribute('focalLength').Get());self.actor_state=result
        return result
