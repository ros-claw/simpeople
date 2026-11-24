"""24 second repair rehearsal; elapsed travel is cut, never sped up.

Actors: one full-pose movie cache controller. Cars: one numerical 1D dynamics
profile (120 Hz), authored only by RailGeometry. Not Native navigation/PhysX.
"""
import json,math
from pathlib import Path
import numpy as np
from pxr import UsdGeom,Gf
from simpeople.core.funicular import Funicular
from .deadweight_cinema import raised_wings,torso_sway,infected_wait,quat_apply,quat_mul
from .deadweight_v2_actor import ActorV2,SkinnedStride,wrist_turn
from .deadweight_v2_set import aim,Weather,T,RUN,FLOOR

def smooth(x):
    u=float(np.clip(x,0,1));return u*u*(3-2*u)

class RepairDirector:
    def __init__(self,stage,cars,geometry,cache,root,out):
        self.stage=stage;self.cars=cars;self.geometry=geometry;self.cache=cache;self.root=Path(root);self.out=Path(out);self.actors={};self.slots={};self.lifts={};self.events=[];self.boarded=False;self.release_tick=None;self.stable_start=None;self.previous_board=None
        assets=json.loads((self.root/'configs/assets.json').read_text())['assets'][:11]
        def source(k):return str(self.root/'assets/characters'/assets[k%11]['source_uri'].removeprefix('characters://'))
        self.sources={};palette=[(.18,.39,.41),(.61,.25,.10),(.25,.33,.16),(.16,.24,.42),(.49,.16,.19),(.45,.38,.16)]
        for i in range(23):
            aid=f'infected_{i+1:02d}';a=ActorV2(stage,cars['A']['root']+'/Passengers/'+aid,cache,palette[i%6],source(i));self.actors[aid]=a;self.sources[aid]=i%11
            n=i-1;self.slots[aid]=np.array([3.8,-1.05,FLOOR]) if i==0 else np.array([-2.8+n%8*1.1,1.05-(n//8)*1.05,FLOOR])
        hero=ActorV2(stage,cars['A']['root']+'/Passengers/heroine',cache,(.74,.48,.10),source(3));self.actors['heroine']=hero;self.sources['heroine']=3;self.slots['heroine']=np.array([-5.05,.75,FLOOR]);hero.update(*cache.pose(0,'idle'),self.slots['heroine'],math.pi/2);hero.hood(self.root/'.runtime/deadweight/Deadweight_Feasibility_Assets/gull_hood.usda');self.fit=hero.short_mitts(self.root,self.out/'fitted_mitts')
        for i in range(12):
            aid=f'survivor_{i+1:02d}';a=ActorV2(stage,cars['B']['root']+'/Passengers/'+aid,cache,palette[(i+2)%6],source(5+i));self.actors[aid]=a;self.sources[aid]=(5+i)%11;self.slots[aid]=np.array([-5.05,-1.08,FLOOR]) if i==0 else np.array([-2.8+(i-1)%4*2.1,-.8+(i-1)//4*.85,FLOOR])
            if i==0:a.camera_prop()
        # Calibrate original skinned shoes once per target anatomy for background
        # poses. Foreground actors retain actual deformed-vertex grounding.
        for key in range(11):
            a=next(self.actors[aid] for aid in self.actors if self.sources[aid]==key);values=[]
            for f in range(cache.period):
                a.update(*cache.pose(f),[0,0,0]);values.append(float(a.animation.GetTranslationsAttr().Get()[0][2]-cache.local_trs(*cache.pose(f))[0][0,2]))
            # Store the extra correction relative to FilmActor's toe baseline.
            self.lifts[key]=[]
            from .deadweight_cinema import FilmActor
            for f in range(cache.period):
                FilmActor.update(a,*cache.pose(f),[0,0,0]);base=float(a.animation.GetTranslationsAttr().Get()[0][2]);self.lifts[key].append(values[f]+cache.local_trs(*cache.pose(f))[0][0,2]-base)
        self.stride=SkinnedStride(self.actors['infected_01']);self.walk=SkinnedStride(hero,'walk')
        self.profile=json.loads((self.root/'runs/deadweight-v2-rail-01/production_profile.json').read_text());self.meet_index=min(range(len(self.profile)),key=lambda i:abs(self.profile[i]['q_m']-56));self.meet_start=self.meet_index-300
        self.ledger=Funicular();kw=dict(inside=True,feet_supported=True,stable_s=.5,speed_mps=0)
        for aid in self.actors:
            if aid!='infected_01':self.ledger.add_passenger(aid,'A' if aid.startswith('infected') or aid=='heroine' else 'B',76 if aid=='heroine' else 74 if aid.startswith('infected') else 75,**kw)
        self.weather=Weather(stage);self.weather.update(0)
        # Missing labels are communicated by set geometry in the mute review.
        self.camera=UsdGeom.Xformable(stage.GetPrimAtPath('/World/Camera')).GetOrderedXformOps()[0]
        self.out.joinpath('initial_conditions.json').write_text(json.dumps({'initially_preloaded_ids':list(self.ledger.passengers),'initially_outside':'infected_01','initial_load_scope':'configured stationary preload, not Native navigation evidence','profile_run':'deadweight-v2-rail-01','film_controllers':'exclusive cached bones + one numerical 1D car profile','fit':self.fit},indent=2))

    def observe(self,aid):
        a=self.actors[aid];xf=UsdGeom.XformCache();m=xf.GetLocalToWorldTransform(self.stage.GetPrimAtPath(a.path));gp=np.asarray(m);joint=a.joint_p@gp[:3,:3]+gp[3,:3]
        return {'actor_id':aid,'root_world_m':list(m.ExtractTranslation()),'joints_world_m':joint.tolist(),'controller':'cinematic full pose cache','skeleton_translations':np.asarray(a.animation.GetTranslationsAttr().Get()).tolist()}

    def update(self,frame):
        t=frame/30;cache=self.cache;segment='infection' if t<5.5 else 'boarding' if t<10.5 else 'wheel_start' if t<14.5 else 'meeting' if t<19.5 else 'escape';local=t-(0 if segment=='infection' else 5.5 if segment=='boarding' else 10.5 if segment=='wheel_start' else 14.5 if segment=='meeting' else 19.5)
        if segment in ['infection','boarding']:index=0 if self.release_tick is None else min(len(self.profile)-1,(frame-self.release_tick)*4)
        elif segment=='wheel_start':
            if self.release_tick is None:raise RuntimeError('no actual boarding/door release before wheel shot')
            index=min(len(self.profile)-1,(frame-self.release_tick)*4)
        elif segment=='meeting':index=min(len(self.profile)-1,self.meet_start+round(local*120))
        else:index=len(self.profile)-1
        state=self.profile[index];self.geometry.apply(state['q_m'])
        # Every background actor changes bones at 30 Hz, with distinct phases.
        for i,(aid,a) in enumerate(self.actors.items()):
            if aid in ['infected_01','heroine','survivor_01']:continue
            phase=t*30+i*7
            if aid.startswith('infected'):
                p,q=cache.pose(phase);p,q=torso_sway(cache,p,q,.035*math.sin(t*1.4+i));k=int(phase)%cache.period;lift=self.lifts[self.sources[aid]][k]
                if aid in ['infected_21','infected_22','infected_23']:
                    p,q=cache.pose(0,'idle')
                    if aid!='infected_22':
                        amount=.68 if aid=='infected_21' else .61+.10*math.sin(t*1.1);p,q=raised_wings(cache,p,q,amount,('L',));p,q=wrist_turn(cache,p,q,'L',.65*math.sin(t*.9) if aid=='infected_23' else 0)
                    else:
                        j=cache.index('NeckTwist01');branch=[k for k,n in enumerate(cache.names) if n==cache.names[j] or n.startswith(cache.names[j]+'/')];angle=.55+.25*math.sin(t*.6);rot=np.array([0,0,math.sin(angle/2),math.cos(angle/2)]);p[branch]=quat_apply(rot,p[branch]-p[j])+p[j];q[branch]=quat_mul(rot,q[branch])
                    a.update(p,q,self.slots[aid],-math.pi/2)
                else:a.update(p,q,self.slots[aid],math.pi/2,grounding_lift_m=lift)
            else:
                p,q=torso_sway(cache,*cache.pose(0,'idle'),.012*math.sin(t*1.2+i*2));a.update(p,q,self.slots[aid],-math.pi/2,grounding_lift_m=0)
        # Same visitor identity in the infection shot and the last boarding.
        a=self.actors['infected_01']
        if segment=='infection':
            f=frame
            if f<140:
                p,q=cache.p[f],cache.q[f];heading=cache.heading[f];pos=np.array([-7.8,-7.8,FLOOR])+cache.roots[f]-cache.roots[0]
            else:
                p,q=cache.pose(f-140);heading=cache.heading[139];d=self.stride.displacement(f-140);turn=np.array([[math.cos(heading),-math.sin(heading),0],[math.sin(heading),math.cos(heading),0],[0,0,1]]);pos=np.array([-7.8,-7.8,FLOOR])+cache.roots[139]-cache.roots[0]+turn@d
        elif segment=='boarding':
            # A straight 2.8 m threshold crossing, then a short offset to a free
            # front slot. Actual readback speed controls the mass registration.
            u=smooth((local-2.0)/.55);y=min(-.70,-3.50+local*1.40);x=3.3+.5*u;pos=np.array([x,y-.35*u,FLOOR]);heading=math.pi/2;distance=max(0,pos[1]+3.50);phase=self.stride.phase_at_distance(distance);p,q=cache.pose(phase) if local<2.55 else infected_wait(cache,t*18,.8)
        else:pos=self.slots['infected_01'];heading=math.pi/2;p,q=infected_wait(cache,t*22,1.)
        a.update(p,q,pos,heading)
        if segment=='boarding':
            world=np.array(UsdGeom.XformCache().GetLocalToWorldTransform(self.stage.GetPrimAtPath(a.path)).ExtractTranslation());speed=0 if self.previous_board is None else float(np.linalg.norm(world-self.previous_board)*30);self.previous_board=world
            sole=a.foot_points();feet=min(float(v[:,2].min()) for v in sole.values())>=-.005;inside=abs(pos[0])<5.6 and abs(pos[1])<1.45
            if inside and feet and speed<.15:
                if self.stable_start is None:self.stable_start=local
            else:self.stable_start=None
            stable=0 if self.stable_start is None else local-self.stable_start
            if not self.boarded and self.ledger.add_passenger('infected_01','A',74,inside=inside,feet_supported=feet,stable_s=stable,speed_mps=speed):self.boarded=True;self.events.append({'event':'last_boarded','source_tick':frame,'measured_root_speed_mps':speed,'stable_s':stable,'mass_A_B_kg':self.ledger.masses})
        # Close the passenger doors only after the last visitor has settled.
        closing=smooth((local-3.05)/.60) if segment=='boarding' and self.boarded else 1 if segment not in ['infection','boarding'] else 0
        for name,car in self.cars.items():
            for key,op in car['doors'].items():
                opening=0 if name=='B' or key=='inner' or key==0 else 1-closing
                if name=='A' and key==0 and segment=='escape':opening=smooth(local/.40)
                op.Set(Gf.Vec3d(0,0,2.6*opening) if key=='inner' else Gf.Vec3d(1.85*opening,0,0))
        if segment=='boarding' and self.release_tick is None and self.boarded and closing>=1-1e-10:
            self.ledger.doors_closed=all(abs(self.cars[n]['doors'][k].Get()[0])<1e-8 for n in ['A','B'] for k in [0,1,2]);self.ledger.authorized=True
            if self.ledger.release():
                if list(self.ledger.masses)!=[state['mass_A_kg'],state['mass_B_kg']]:raise RuntimeError('profile/actual ledger mass mismatch')
                self.release_tick=frame;self.events.append({'event':'doors_locked_release','source_tick':frame,'mass_A_B_kg':self.ledger.masses})
        hero=self.actors['heroine'];hp=self.slots['heroine'].copy();heading=math.pi/2
        p,q=cache.pose(0,'idle')
        if segment=='meeting':
            p,q=raised_wings(cache,p,q,.68,('L',));p,q=wrist_turn(cache,p,q,'L',.16*math.sin(local*1.3))
        elif segment=='escape':
            elapsed=float(np.clip(local-.45,0,3.8));accel=.30;brake=.35;vmax=3.30/(3.8-(accel+brake)/2)
            if elapsed<accel:d=.5*vmax/accel*elapsed**2
            elif elapsed<3.8-brake:d=vmax*(elapsed-accel/2)
            else:d=3.30-.5*vmax/brake*(3.8-elapsed)**2
            hp[1]-=d;heading=-math.pi/2;wp,wq=cache.pose(self.walk.phase_at_distance(d),'walk');idle_p,idle_q=cache.pose(0,'idle');weight=smooth(elapsed/accel)*(1-smooth((elapsed-(3.8-brake))/brake));p=idle_p*(1-weight)+wp*weight;wq[np.sum(idle_q*wq,axis=1)<0]*=-1;q=idle_q*(1-weight)+wq*weight;q/=np.linalg.norm(q,axis=1)[:,None]
        hero.update(p,q,hp,heading)
        partner=self.actors['survivor_01'];p,q=cache.pose(0,'idle')
        if segment=='meeting':p,q=raised_wings(cache,p,q,.80,('R',))
        partner.update(p,q,self.slots['survivor_01'],-math.pi/2)
        # Keep foam tips inside the window. Measured on transformed mesh points.
        mitt=hero.mitt_world_points();carA=np.array(self.cars['A']['xform'].Get());self.mitt_inside_m=min(1.85-float(np.max(v[:,1]-carA[1])) for v in mitt.values())
        self.weather.update(t)
        aroot=np.array(self.cars['A']['xform'].Get());broot=np.array(self.cars['B']['xform'].Get())
        if segment=='infection':
            target=np.array([RUN-6.0,-10.2,59+FLOOR+.87]);aim(self.stage,target+[-.2,-6.7,1.15],target,43)
        elif segment=='boarding':
            target=aroot+np.array([3.5,-2.1,FLOOR+.90]);aim(self.stage,target+np.array([-1.7,-7,1.05]),target,39)
        elif segment=='wheel_start':
            # Two locked views of the SAME uninterrupted solver progression.
            # The far car is too small through the chassis to read reliably;
            # cut to the lower station rather than misrepresenting this shot.
            if local<2:
                target=np.array([RUN-3.8,-1.55,60.35]);aim(self.stage,target+np.array([6.0,7.5,1.2]),target,28)
            else:aim(self.stage,[-14,-22,13],[4,2.4,8],40)
        elif segment=='meeting':
            target=(aroot+broot)/2+np.array([-5.05,0,FLOOR+1.25]);aim(self.stage,target+np.array([-4.7,0,1]),target,36)
        else:
            target=np.array([-5.05,-4.9,6.5]);aim(self.stage,[-12,-14,9.0],target,43)
        return {'source_tick':frame,'movie_time_s':t,'segment':segment,'segment_time_s':local,'solver_index':index,'solver_state':state,'rail':self.geometry.read(),'mitt_inside_window_m':self.mitt_inside_m,'camera_matrix':np.asarray(self.camera.Get()).tolist(),'actors':[self.observe(aid) for aid in self.actors]}
