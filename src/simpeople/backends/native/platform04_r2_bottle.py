"""One bottle release, two consequential reactions. Authored film props."""
import json,math
from pathlib import Path
import numpy as np
from pxr import UsdGeom,UsdShade,Sdf,Gf,UsdLux
from .platform04_r2_motion import PerformanceMotion,PerformanceActor,bend_fingers,grab_wrist
from .platform04_90_scene import FloorBag,ShoulderBag
from .platform04_animation import axis_q,rotate_branch,reach
from .performance_score import Trajectory,smooth,window
from .platform04_scene import aim


class BottleDirector:
    duration=12.
    def __init__(self,stage,scene,root,out,*_):
        self.stage=stage;self.scene=scene;self.root=Path(root);self.out=Path(out);self.bank=PerformanceMotion(root);self.actors={};self.layers={};self.bags={};assets=json.loads((self.root/'configs/assets.json').read_text())['assets']
        for aid,index,color in [('H01',0,(.78,.45,.06)),('H02',9,(.025,.33,.34)),('A03',10,(.27,.23,.19))]:
            source=self.root/'assets/characters'/assets[index]['source_uri'].removeprefix('characters://');a=PerformanceActor(stage,'/World/Cast/'+aid,self.bank,color,str(source));self.actors[aid]=a
            for clip in ['idle','walk','final','zslow','crouch']:a.fit(clip)
            a.calibrate_soles()
        self.bags['H01']=ShoulderBag(stage,self.actors['H01'],(.63,.39,.065));self.floorbag=FloorBag(stage,self.actors['A03']);oldbag=UsdGeom.Xform.Define(stage,self.floorbag.path);self.oldbag_world_op=oldbag.AddTransformOp();self.bag_anchor=None;self.frozen_bag=False
        self.paths={
            'H01':Trajectory([(0,(13.25,5.40),(.12,0)),(2.0,(13.50,5.40),(.12,0)),(5.,(14.25,5.50),(.35,.10)),(9.,(15.30,6.25),(.30,.20)),(12.,(16.25,6.75),(.35,.15))]),
            'H02':Trajectory([(0,(16.,5.20),(0,0)),(1.45,(16.,5.20),(0,0)),(3.,(15.65,5.95),(0,0)),(6.,(15.65,5.95),(0,0)),(9.,(16.,6.50),(.20,.20)),(12.,(16.80,6.90),(.30,.12))]),
            'A03':Trajectory([(0,(14.1,7.22),(0,0)),(3.2,(14.1,7.22),(0,0)),(4.2,(14.6,6.75),(.75,-.7)),(5.8,(16.9,5.40),(1.1,-.65)),(6.6,(17.5,5.08),(0,0)),(8.2,(17.5,5.08),(0,0)),(9.3,(17.35,5.25),(-.1,.1)),(12.,(17.1,5.55),(-.1,.1))])}
        self.tables={}
        for aid,path in self.paths.items():
            ts=np.linspace(0,12,2401);xy=np.array([path.sample(t)[0] for t in ts]);self.tables[aid]=(ts,np.r_[0,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))])
        material=UsdShade.Material.Define(stage,'/World/Props/BottleMetal');shader=UsdShade.Shader.Define(stage,'/World/Props/BottleMetal/Surface');shader.CreateIdAttr('UsdPreviewSurface');shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set((.62,.65,.66));shader.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(.60);shader.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(.24);material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
        bottle=UsdGeom.Xform.Define(stage,'/World/Props/OnlyBottle');self.bottle_op=bottle.AddTransformOp()
        for name,radius,height,z in [('Body',.038,.24,0),('Cap',.030,.035,.1375),('Rim',.040,.025,-.118)]:
            cylinder=UsdGeom.Cylinder.Define(stage,'/World/Props/OnlyBottle/'+name);cylinder.CreateRadiusAttr(radius);cylinder.CreateHeightAttr(height);cylinder.CreateAxisAttr('Z');cylinder.AddTranslateOp().Set(Gf.Vec3d(0,0,z));UsdShade.MaterialBindingAPI.Apply(cylinder.GetPrim()).Bind(material)
        fill=UsdLux.RectLight.Define(stage,'/World/Metro/Lights/R2_BagFace');fill.CreateWidthAttr(2.);fill.CreateHeightAttr(1.);fill.CreateIntensityAttr(2300);fill.CreateColorAttr(Gf.Vec3f(.85,.80,.70));fill.AddTranslateOp().Set(Gf.Vec3d(15.5,7.7,2.0));fill.AddRotateXYZOp().Set(Gf.Vec3f(15,0,45))
        edge=UsdLux.RectLight.Define(stage,'/World/Metro/Lights/R2_BottleEdge');edge.CreateWidthAttr(1.0);edge.CreateHeightAttr(.6);edge.CreateIntensityAttr(1200);edge.CreateColorAttr(Gf.Vec3f(.70,.85,.95));edge.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(17.4,3.,2.1),Gf.Vec3d(16.,5.,1.),Gf.Vec3d(0,0,1)).GetInverse())
        self.events=[{'t':.85,'actor':'H02','event':'bottle_released','count':1},{'t':1.30,'actor':'OnlyBottle','event':'first_floor_impact'},{'t':1.45,'actor':'H02','event':'abandons_retrieval_looks_for_companion'},{'t':2.1,'actor':'OnlyBottle','event':'final_rolling_tap'},{'t':2.18,'actor':'A03','event':'chewing_stops_attention_to_bottle'},{'t':2.35,'actor':'A03','event':'strap_released'},{'t':3.2,'actor':'A03','event':'leaves_old_bag_in_place'},{'t':4.2,'actor':'A03','event':'pushes_toward_stimulus_ignores_offered_hand'},{'t':5.8,'actor':'A03','event':'grabs_former_noise_position'},{'t':6.6,'actor':'A03','event':'missed_reach_recovery'},{'t':7.,'actor':'H02','event':'returns_attention_to_companion'}]
        (self.out/'event_score.json').write_text(json.dumps({'events':self.events,'bottle_release_count':1,'prop_motion':'authored analytic gravity/bounce/roll, not PhysX contact','bag':'retains its world transform after abandonment, never carried along by moving character root'},indent=2));(self.out/'casting.json').write_text(json.dumps({'actors':list(self.actors),'full_group_expanded':False,'scope':'three-actor controlled bottle reaction sample; no claimed 24-person chain'},indent=2))

    def bottle(self,t):
        release=.85;impact=1.30
        if t<release:return np.array([16.16,5.02,1.05]),0.
        if t<impact:
            u=t-release;return np.array([16.16+.8*u,5.02-.5*u,1.05-.5*9.81*u*u]),1.3*(t-release)/(impact-release)
        u=t-impact;travel=.78*(1-math.exp(-u/ .48));bounce=.11*math.exp(-u*4)*abs(math.sin(u*17));return np.array([16.52+travel,4.795-.10*(1-math.exp(-u/.5)),.042+bounce]),math.pi/2+travel/.038

    def update(self,f):
        t=f/30;row={'source_tick':f,'story_time_s':21+t,'mode':'bottle','shot':'B01' if t<1.7 else 'B02' if t<4.1 else 'B03','actors':{},'events':[e for e in self.events if t-1/30<e['t']<=t]};b=self.bank;noise=np.array([17.30,4.695,.65])
        point,spin=self.bottle(t);matrix=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0,1,0),math.degrees(spin)));matrix.SetTranslateOnly(Gf.Vec3d(*point));self.bottle_op.Set(matrix);row['bottle_world_m']=point.tolist();row['actual_bottle_world_m']=list(UsdGeom.XformCache().GetLocalToWorldTransform(self.stage.GetPrimAtPath('/World/Props/OnlyBottle')).ExtractTranslation());row['bottle_released']=t>=.85
        for aid,a in self.actors.items():
            xy,v=self.paths[aid].sample(t);speed=float(np.linalg.norm(v));yaw=math.atan2(v[1],v[0]) if speed>.05 else -.65 if aid=='A03' else math.pi if aid=='H02' else 0.;ts,ds=self.tables[aid];distance=float(np.interp(t,ts,ds));clip='walk' if aid!='A03' else 'zslow';phase=a.phase(distance,clip);p,q=b.pose(phase,clip) if speed>.05 else b.pose(0,'idle');lift=a.ground_lift(clip,phase) if speed>.05 else a.ground_lift('idle',0)
            if aid=='H02' and t<1.45:yaw=0.
            if aid=='H01':state='moves_to_waiting_companion';p,q=b.glance(p,q,.2*window(t,1.5,2.4,.2))
            elif aid=='H02':
                if t<1.45:p,q=a.physical_ik((p,q),'R',[.16,-.18,1.12-.25*smooth((t-1.0)/.3)],lift=lift);p,q=b.glance(p,q,-.55*smooth((t-1.0)/.3));p,q=rotate_branch(b,p,q,'NeckTwist01',axis_q([0,1,0],.25*window(t,1.05,1.45,.12)))
                else:
                    p,q=b.glance(p,q,.45*window(t,1.5,3.2,.2));p,q=reach(b,p,q,'L',[.30,.22,1.25]);p,q=reach(b,p,q,'R',[.20,-.18,1.20+.08*math.sin((t-1.45)*3)])
                state='holds_bottle' if t<.85 else 'starts_to_retrieve' if t<1.45 else 'chooses_companion_not_bottle'
            else:
                rise=smooth((t-2.7)/.75);crouch=b.pose(20,'crouch');p,q=b.mix(crouch,(p,q),rise);lift=(1-rise)*a.ground_lift('crouch',20)+rise*lift;bite=1-smooth((t-2.18)/.30)
                if t<3.5:
                    p,q=rotate_branch(b,p,q,'Spine01',axis_q([0,1,0],.28*(1-rise)));p,q=a.physical_ik((p,q),'L',[.27,.08,.28],lift=lift);physical,_=a.physical_pose((p,q),lift);mouth=physical[b.index('Head')]+[.075,0,-.055];p,q=a.physical_ik((p,q),'R',mouth+[.01,-.06,-.25],lift=lift);p,q=rotate_branch(b,p,q,'JawRoot',axis_q([0,1,0],.13+.075*math.sin(t*14)*bite));p,q=b.glance(p,q,.6*smooth((t-2.3)/.35))
                grab=window(t,4.5,6.3,.20);p,q=rotate_branch(b,p,q,'Spine01',axis_q([0,1,0],.28*grab));p,q=rotate_branch(b,p,q,'JawRoot',axis_q([0,1,0],.25*grab))
                delta=noise-[*xy,0];c,s=math.cos(yaw),math.sin(yaw);goal=np.array([c*delta[0]+s*delta[1],-s*delta[0]+c*delta[1],delta[2]]);target=a.physical_ik((p,q),'R',goal,lift=lift);p,q=b.mix((p,q),target,grab);p,q=grab_wrist(b,p,q,'R',grab);p,q=bend_fingers(b,p,q,'R',.75*grab)
                state='chews_old_bag' if t<2.18 else 'abandons_strap_for_stimulus' if t<3.2 else 'approaches_noise_ignores_help' if t<5.8 else 'missed_grab_recovery' if t<7.0 else 'searches_old_noise_location'
            a.safe_update((p,q),[*xy,0],yaw,lift);z=min(float(x[:,2].min()) for x in a.foot_points().values());adjust=max(0,.003-z)
            if adjust:lift+=adjust;a.safe_update((p,q),[*xy,0],yaw,lift)
            if aid=='A03':
                if self.bag_anchor is None:self.bag_anchor=Gf.Matrix4d(a.matrix)
                if t<3.2:self.floorbag.update(11.+(t-2.35),1-smooth((t-2.18)/.3))
                else:self.frozen_bag=True
                self.oldbag_world_op.Set(self.bag_anchor*Gf.Matrix4d(a.matrix).GetInverse())
                row['old_bag_world_matrix']=np.asarray(self.bag_anchor).tolist();row['old_bag_detached_from_root']=self.frozen_bag
                row['actual_old_bag_center_world_m']=list(UsdGeom.XformCache().GetLocalToWorldTransform(self.floorbag.body.GetPrim()).ExtractTranslation())
            row['actors'][aid]={'root_world_m':[*map(float,xy),0.],'yaw_rad':yaw,'speed_mps':speed,'phase':phase,'gait':clip,'behavior':state,'state':state,'support':{},'ground_adjustment_m':adjust,'root_owner':'R2 film trajectory'}
        if t<1.7:aim(self.stage,[17.8,2.3,1.25],[15.3,5.5,.65],60)
        elif t<4.1:aim(self.stage,[17.0,8.0,1.25],[14.4,7.0,.85],58)
        else:aim(self.stage,[19.0,2.2,1.65],[15.7,5.6,.9],68)
        camera=self.stage.GetPrimAtPath('/World/Camera');row['camera_matrix']=np.asarray(UsdGeom.Xformable(camera).GetOrderedXformOps()[0].Get()).tolist();row['camera_focal_mm']=float(camera.GetAttribute('focalLength').Get());return row
