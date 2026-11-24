"""18-second Blind Side film choreography; not a reactive-pursuit proof."""
import importlib.util,json,math,sys
from pathlib import Path
import numpy as np
from pxr import UsdGeom,Gf
from scipy.spatial import cKDTree
from .platform04_animation import MetroActor,MetroMotion,blend,rotate_branch,axis_q,look_at,reach
from .platform04_scene import aim
from .deadweight_set import box

def smooth(v):
    u=float(np.clip(v,0,1));return u*u*(3-2*u)
def yaw_difference(a,b):return (a-b+math.pi)%(2*math.pi)-math.pi

class MetroDirector:
    def __init__(self,stage,scene,root,out,*,extras=True):
        self.stage=stage;self.scene=scene;self.root=Path(root);self.out=Path(out);self.bank=MetroMotion(root);self.actors={};self.extras=extras
        spec=importlib.util.spec_from_file_location('platform04_kit_timeline',self.root/'.runtime/platform04/kit/previs/timeline.py');self.timeline=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.timeline)
        self.ids=['hero','chaser','intercept']+(['witness','bystander','extra0','extra1','extra2','extra3','low','stubborn'] if extras else [])
        assets=json.loads((self.root/'configs/assets.json').read_text())['assets'];casting={'hero':0,'chaser':5,'intercept':3,'witness':9,'extra0':6,'extra1':1,'extra2':8,'extra3':4,'low':7,'stubborn':10};colors={'hero':(.76,.43,.055),'chaser':(.72,.77,.73),'intercept':(.46,.045,.025),'witness':(.025,.28,.28),'extra0':(.13,.17,.22),'extra1':(.25,.22,.14),'extra2':(.16,.24,.16),'extra3':(.19,.13,.16),'low':(.12,.15,.15),'stubborn':(.20,.18,.12)}
        casting['bystander']=1;colors['bystander']=(.06,.14,.22);self.normal={'hero','witness','bystander'};self.fit_reports={}
        for aid in self.ids:
            a=assets[casting[aid]];source=self.root/'assets/characters'/a['source_uri'].removeprefix('characters://');actor=MetroActor(stage,'/World/Actors/'+aid,self.bank,colors[aid],str(source));self.actors[aid]=actor
            actions=['idle','sprint' if aid in self.normal else 'infected_sprint']+(['crouch'] if aid=='low' else [])
            self.fit_reports[aid]={}
            for action in actions:
                f=actor.fit(action);self.fit_reports[aid][action]={k:v for k,v in f.items() if k not in ['feet','lifts','travel']};self.fit_reports[aid][action]['lifts_m']=f['lifts'].tolist();self.fit_reports[aid][action]['travel_m']=f['travel'].tolist()
        self.distances={};self.times=np.linspace(0,18,1801)
        for aid in self.ids:
            xy=np.array([self.root_pose(aid,t)[0] for t in self.times]);self.distances[aid]=np.r_[0,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))]
        self.phone=UsdGeom.Xform.Define(stage,'/World/Props/DroppedPhone');self.phone_op=self.phone.AddTransformOp();box(stage,'/World/Props/DroppedPhone/Case',(0,0,0),(.073,.012,.145),(.016,.023,.026),.7,.25);box(stage,'/World/Props/DroppedPhone/BlackScreen',(0,.007,0),(.064,.002,.128),(.002,.006,.007),.35,.12)
        self.phone_release=None;self.camera=UsdGeom.Xformable(stage.GetPrimAtPath('/World/Camera')).GetOrderedXformOps()[0]
        (self.out/'actor_fits.json').write_text(json.dumps(self.fit_reports,indent=2));(self.out/'casting.json').write_text(json.dumps({aid:{'base_asset':assets[casting[aid]]['asset_id'],'controller':'exclusive 101-joint movie cache','costume':'original skinned clothes; no torso shell'} for aid in self.ids},indent=2))
    def root_pose(self,aid,t):
        if aid=='low':
            u=smooth((t-13.35)/1.0);return np.array([29.55-.20*u,6.4-.20*u]),-math.pi/2,0.
        if aid=='stubborn':
            return np.array([15.6+max(0,t-11.8)*.45,-1.01+.15*smooth((t-6)/.4)*(1-smooth((t-7)/.6))]),math.pi/2 if t<10 else 0.,max(0,t-11.8)*.45
        source='extra5' if aid=='bystander' else aid
        xy,yaw,_=self.timeline.sample(source,min(t,17.99));xy=np.array(xy)
        if aid=='chaser':
            xy[1]+=.70*(1-smooth((t-9.6)/1.25));xy[0]-=.35*smooth((t-10.5)/.7)*(1-smooth((t-12.4)/.8))
        if aid=='hero':xy[0]-=.45*smooth((t-12.35)/.45)*(1-smooth((t-13.4)/.65))
        if aid=='intercept':
            xy[1]+=.72*smooth((t-11.7)/1.2)*(1-smooth((t-14.0)/3.2));xy[0]+=.14*smooth((t-10.8)/.45)*(1-smooth((t-12.4)/.7))
        return xy,float(yaw),0.
    def path_state(self,aid,t):
        xy,yaw,_=self.root_pose(aid,t);before=self.root_pose(aid,max(0,t-.015))[0];after=self.root_pose(aid,min(17.999,t+.015))[0];speed=float(np.linalg.norm(after-before)/(.03 if .015<t<17.984 else .015));distance=float(np.interp(t,self.times,self.distances[aid]));yaw=math.atan2(after[1]-before[1],after[0]-before[0]) if speed>.10 and aid not in ['low','stubborn'] else yaw;return xy,yaw,speed,distance
    def actor_world_points(self,aid,*,hands=False):
        actor=self.actors[aid];points=actor.skin_points();matrix=np.asarray(actor.matrix);result=[]
        for mesh in actor.meshes:
            x=points[str(mesh['prim'].GetPath())]
            if hands:
                mask=mesh['hands']['R'];x=x[mask]
            if len(x):result.append(x@matrix[:3,:3]+matrix[3,:3])
        return np.concatenate(result)
    def update(self,f,*,geometry=False):
        t=f/30.;states={};gaits={}
        for aid,a in self.actors.items():
            xy,yaw,speed,distance=self.path_state(aid,t);action='sprint' if aid in self.normal else 'infected_sprint';phase=a.phase(distance,action);weight=smooth((speed-.12)/1.35);pose=blend(self.bank.pose(0,'idle'),self.bank.pose(phase,action),weight);lift=a.ground_lift('idle',0)*(1-weight)+a.ground_lift(action,phase)*weight
            if aid=='hero':
                # Look over the camera-side shoulder first; notice the window
                # runner only late. The audience sees the door before she does.
                yaw_head=2.10*smooth((t-4.1)/.5)*(1-smooth((t-9.55)/.5))
                yaw_head+=-1.20*smooth((t-9.55)/.40)*(1-smooth((t-12.0)/.5));pose=look_at(self.bank,*pose,yaw_head)
            elif aid=='intercept':
                hero=self.path_state('hero',t)[0];angle=math.atan2(hero[1]-xy[1],hero[0]-xy[0]);pose=look_at(self.bank,*pose,yaw_difference(angle,yaw),.90);pose=rotate_branch(self.bank,*pose,'JawRoot',axis_q([0,1,0],.16))
                attack=smooth((t-10.8)/.4)*(1-smooth((t-12.4)/.7))
                if attack:
                    # Coherent reach/grab/recovery, not a hook-punch reset.
                    p,q=pose;desired=np.array([.66,-.16,1.15]);rp=reach(self.bank,p,q,'R',desired);pose=blend(pose,rp,attack);pose=rotate_branch(self.bank,*pose,'Spine01',axis_q([0,1,0],.12*attack))
            elif aid=='chaser' and t<2.85:
                phone_pose=reach(self.bank,*self.bank.pose(0,'idle'),'L',[.34,.12,1.10]);phone_pose=look_at(self.bank,*phone_pose,.35);phone_pose=rotate_branch(self.bank,*phone_pose,'NeckTwist01',axis_q([0,1,0],.22*(1-smooth((t-1.7)/.4))));phone_pose=rotate_branch(self.bank,*phone_pose,'L_Thumb1',axis_q([0,1,0],.32*math.sin(t*12)))
                # A neck/shoulder beat precedes the first actual moving step.
                pulse=smooth((t-1.55)/.16)*(1-smooth((t-2.12)/.3));phone_pose=rotate_branch(self.bank,*phone_pose,'NeckTwist01',axis_q([1,0,0],.33*pulse));pose=blend(phone_pose,pose,smooth((t-2.18)/.56))
            elif aid not in self.normal:
                pose=rotate_branch(self.bank,*pose,'JawRoot',axis_q([0,1,0],.12+.035*math.sin(t*1.5)))
                if aid=='chaser':
                    hero=self.path_state('hero',t)[0];pose=look_at(self.bank,*pose,yaw_difference(math.atan2(hero[1]-xy[1],hero[0]-xy[0]),yaw))
            if aid=='low':
                rise=smooth((t-13.25)/1.05);pose=blend(self.bank.pose(20,'crouch'),self.bank.pose(0,'idle'),rise)
                # Hold a low pose, not crouch-walk in place. Brace one hand at
                # the physical seat edge before the upper body comes up.
                anchor=np.array([29.75-xy[0],6.25-xy[1],.63]);c,s=math.cos(yaw),math.sin(yaw);local=np.array([c*anchor[0]+s*anchor[1],-s*anchor[0]+c*anchor[1],anchor[2]]);pose=reach(self.bank,*pose,'L',local);lift=a.ground_lift('crouch',20)*(1-rise)+a.ground_lift('idle',0)*rise
            if aid=='stubborn' and t<11.8:
                hit=smooth((t-6.1)/.18)*(1-smooth((t-6.9)/.5));pose=reach(self.bank,*self.bank.pose(0,'idle'),'L',[.62,.08,1.18]);pose=rotate_branch(self.bank,*pose,'Spine01',axis_q([0,1,0],.15*hit));lift=a.ground_lift('idle',0)
            a.update(*pose,[*xy,0],yaw,lift=lift);states[aid]={'id':aid,'root_world_m':[*xy,0],'yaw_rad':yaw,'speed_mps':speed,'gait':action,'phase':phase,'motion_weight':weight};gaits[aid]=phase
        # The prop leaves the exact wrist once, then falls independently.
        chaser=self.actors['chaser'];j=self.bank.index('L_Hand');m=np.asarray(chaser.matrix);hand=chaser.joint_p[j]@m[:3,:3]+m[3,:3]
        if t<1.2:
            position=hand+np.array([.045,.02,0]);self.phone_release=position.copy()
        else:
            if self.phone_release is None:self.phone_release=np.array([-.65+.38,2.08,1.1])
            dt=t-1.2;position=self.phone_release+np.array([.12*min(dt,.48),-.04*min(dt,.48),-min(1.1,.5*9.81*dt*dt)]);position[2]=max(.025,position[2])
        transform=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1,0,0),min(85,max(0,(t-1.2)*220))));transform.SetTranslateOnly(Gf.Vec3d(*map(float,position)));self.phone_op.Set(transform)
        if t<2.28:
            xy=states['chaser']['root_world_m'];aim(self.stage,[xy[0]+1.1,xy[1]+2.5,1.35],[xy[0]+.15,xy[1],1.10],50)
        elif t<4.3:aim(self.stage,[1.4,7.35,1.55],[1.2,2.05,.95],71)
        elif 10.2<=t<13.15:aim(self.stage,[25.3,7.7,1.9],[24.1,1.5,1.05],70)
        else:
            eye,target,fov=self.timeline.camera(t);aim(self.stage,eye,target,max(71,fov) if t<11.92 else fov)
        self.scene['gate_op'].Set(Gf.Vec3d(-6.35*(1-smooth((t-16.0)/.75)),0,0))
        result={'source_tick':f,'movie_time_s':t,'scope':'cinematic routes, not autonomous pursuit','camera_matrix':np.asarray(self.camera.Get()).tolist(),'camera_focal_mm':float(self.stage.GetPrimAtPath('/World/Camera').GetAttribute('focalLength').Get()),'actors':states,'phone_world_m':position.tolist()}
        if geometry:
            hero=self.actor_world_points('hero');hand=self.actor_world_points('intercept',hands=True);dist,idx=cKDTree(hero).query(hand);j=int(dist.argmin());result['near_miss']={'sample_frequency_hz':30,'method':'all deformed right-hand vertices to all actual hero mesh vertices','min_vertex_distance_m':float(dist[j]),'hand_world_m':hand[j].tolist(),'hero_vertex_world_m':hero[idx[j]].tolist(),'hand_vertices':len(hand),'hero_vertices':len(hero),'triangle_intersection':'not_measured'}
        return result
