"""Full-length, cache-owned metro film. No native pursuit claims."""
import json,math
from pathlib import Path
import numpy as np
from pxr import UsdGeom,UsdLux,UsdShade,Sdf,Gf
from .platform04_feature_score import FeatureScore,PARTS
from .platform04_r2_motion import PerformanceMotion,PerformanceActor,PerformanceLayer,bend_fingers,grab_wrist
from .platform04_90_director import Director90,close_fingers
from .platform04_90_animation import pulse
from .platform04_90_scene import ShoulderBag,FloorBag,ribbon
from .platform04_animation import axis_q,rotate_branch,reach
from .performance_score import smooth,window
from .sole_floor import SoleFloor
from .platform04_scene import aim


class FeatureDirector:
    def __init__(self,stage,scene,root,out,part):
        self.stage=stage;self.scene=scene;self.root=Path(root);self.out=Path(out);self.part=part
        self.score=FeatureScore();self.bank=PerformanceMotion(root);self.actors={};self.bags={};self.layers={};self.floor=SoleFloor(scene['boxes']);self.sway_foot_world=None
        self.first,self.last,ids=PARTS[part];assets=json.loads((self.root/'configs/assets.json').read_text())['assets']
        for n,aid in enumerate(ids):
            ix=Director90.CAST[aid];color=Director90.COLORS.get(aid,[(.24,.28,.31),(.31,.24,.17),(.18,.29,.23),(.34,.29,.24),(.31,.15,.17),(.18,.23,.34)][n%6]);source=self.root/'assets/characters'/assets[ix]['source_uri'].removeprefix('characters://')
            a=PerformanceActor(stage,'/World/Cast/'+aid,self.bank,color,str(source));self.actors[aid]=a
            for clip in ['idle','walk','final','zslow']+(['crouch'] if aid in ['F03','A03'] else []):a.fit(clip)
            a.calibrate_soles()
            if aid in ['H01','H02']:self.bags[aid]=ShoulderBag(stage,a,(.63,.39,.065) if aid=='H01' else (.10,.16,.16))
            if part=='door' and aid in ['H01','F01','F02']:
                layer=PerformanceLayer(self.bank,a,self.score.door,aid);self.layers[aid]=layer
                if layer.feet:self.floor.set_phrase(layer.feet)
        self.floorbag=None;self.bag_anchor=None;self.floorbag_frozen=False
        if 'A03' in self.actors:
            self.floorbag=FloorBag(stage,self.actors['A03']);self.oldbag_op=UsdGeom.Xform.Define(stage,self.floorbag.path).AddTransformOp()
        if part in ['reaction','burst']:self.make_floor_bottle()
        for name,eye,target,power,color in [
          ('FeatureBench',[27.7,4.8,2.8],[25.0,6.1,1.0],2300,(.76,.85,.95)),
          ('FeatureRefuge',[28,13.1,2.8],[27.1,11.2,1.2],3000,(.78,.91,.85)),
          ('FeatureGate',[28,10.7,2.7],[28,9.0,1.1],2100,(.79,.91,.87)),
          ('FeatureBag',[16,5.4,2.5],[14.1,7.2,.7],2200,(.94,.83,.71))]:
            light=UsdLux.RectLight.Define(stage,'/World/Director/Lights/'+name);light.CreateWidthAttr(2.5);light.CreateHeightAttr(1.2);light.CreateIntensityAttr(power);light.CreateColorAttr(Gf.Vec3f(*color));light.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*target),Gf.Vec3d(0,0,1)).GetInverse())
        (self.out/'casting.json').write_text(json.dumps({'part':part,'actual_instances':len(ids),'actors':{aid:{'asset_index':Director90.CAST[aid],'source':assets[Director90.CAST[aid]]['source_uri']} for aid in ids},'root_owner':'exclusive authored feature score','autonomous_pursuit':False},indent=2))
        (self.out/'support_windows.json').write_text(json.dumps({aid:{s:[{**k,'anchor':k['anchor'].tolist()} for k in slots] for s,slots in layer.feet.slots.items()} for aid,layer in self.layers.items() if layer.feet},indent=2))

    def make_floor_bottle(self):
        material=UsdShade.Material.Define(self.stage,'/World/Props/OnlyBottleMaterial');shader=UsdShade.Shader.Define(self.stage,str(material.GetPath())+'/Surface');shader.CreateIdAttr('UsdPreviewSurface');shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set((.62,.65,.66));shader.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(.60);shader.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(.24);material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
        p=UsdGeom.Xform.Define(self.stage,'/World/Props/OnlyBottle');m=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0,1,0),90));m.SetTranslateOnly(Gf.Vec3d(17.30,4.695,.042));p.AddTransformOp().Set(m)
        for name,radius,height,z in [('Body',.038,.24,0),('Cap',.030,.035,.1375)]:
            c=UsdGeom.Cylinder.Define(self.stage,str(p.GetPath())+'/'+name);c.CreateRadiusAttr(radius);c.CreateHeightAttr(height);c.CreateAxisAttr('Z');c.AddTranslateOp().Set(Gf.Vec3d(0,0,z));UsdShade.MaterialBindingAPI.Apply(c.GetPrim()).Bind(material)

    def generic(self,aid,t):
        a=self.actors[aid];b=self.bank;xy,yaw,speed=self.score.root(aid,t);clip='final' if speed>1.1 else 'zslow' if aid[0] in ['L','A','F'] else 'walk';distance=self.score.distance(aid,t)
        offset=(int(aid[1:])*.127 if aid[0] in ['L','P'] else 0);phase=a.phase(distance+offset,clip)
        p,q=b.pose(phase,clip) if speed>.04 else b.pose(0,'idle');lift=a.ground_lift(clip,phase) if speed>.04 else a.ground_lift('idle',0);state='travel' if speed>.04 else 'listen'
        if aid[0] in ['F','P'] and speed>1.1:
            p,q=rotate_branch(b,p,q,'Spine01',axis_q([0,1,0],.17));p,q=rotate_branch(b,p,q,'NeckTwist01',axis_q([0,1,0],-.09));p,q=rotate_branch(b,p,q,'JawRoot',axis_q([0,1,0],.16));state='stimulus_committed_pursuit'
            if aid in ['P03','P05']:
                p,q=reach(b,p,q,'R',[.02,-.14,1.03]);state='protect_ribs_other_arm_swing'
            elif aid=='P06':p,q=b.glance(p,q,.40*window(t,39,40,.14));state='short_search_then_burst'
            elif aid=='P02':p,q=rotate_branch(b,p,q,'Spine02',axis_q([0,0,1],.10*window(t,33,35,.2)))
        if aid=='H01':
            state='escape_to_companion' if speed>1.1 else 'hiding_and_finding_route'
            if t<53:p,q=b.glance(p,q,.52*window(t,41.2,42,.2)-.44*window(t,49.7,50.4,.16))
            if 63<=t<69:
                danger=window(t,64.7,67.1,.18);p,q=b.glance(p,q,-.60*danger);p,q=reach(b,p,q,'L',[.10,.22,1.18+.12*danger]);state='bench_threat_choose_other_side'
            if t>=84:
                p,q=b.glance(p,q,-.65*smooth((t-86.2)/.75));state='hears_companion_strap';yaw=.1
        elif aid=='H02':
            state='returns_to_help' if 65<t<77 else 'looks_back_for_companion'
            if (speed<.15 or 69<t<72) and t<79:
                gesture=.5+.5*math.sin(t*2.1);p,q=reach(b,p,q,'R',[.28,-.20,1.25+.14*gesture]);p,q=b.glance(p,q,.35*math.sin(t*.8))
            if t>=84:
                bite=smooth((t-85.7)/1.2);p,q=rotate_branch(b,p,q,'NeckTwist01',axis_q([0,1,0],.24*bite));p,q=rotate_branch(b,p,q,'Spine01',axis_q([0,1,0],.08*bite));physical,_=a.physical_pose((p,q),lift);mouth=physical[b.index('Head')]+[.075,0,-.055];p,q=a.physical_ik((p,q),'R',mouth+[.025,-.045,-.14],lift=lift);p,q=rotate_branch(b,p,q,'JawRoot',axis_q([0,1,0],(.12+.065*math.sin(t*15))*bite));state='chews_own_shoulder_strap';yaw=-2.5
        elif aid=='H03':
            if speed<.1:p,q=reach(b,p,q,'R',[.32,-.20,1.3+.13*math.sin(t*2.7)]);p,q=reach(b,p,q,'L',[.16,.18,1.0]);p,q=b.glance(p,q,.24*math.sin(t*.9));state='holds_way_open_then_checks_outside'
        elif aid=='A03':
            if t<24.3:
                rise=smooth((t-23.7)/.75);crouch=b.pose(20,'crouch');p,q=b.mix(crouch,(p,q),rise);lift=a.ground_lift('crouch',20)*(1-rise)+lift*rise;p,q=rotate_branch(b,p,q,'Spine01',axis_q([0,1,0],.28*(1-rise)));p,q=a.physical_ik((p,q),'L',[.27,.08,.28],lift=lift);p,q=rotate_branch(b,p,q,'NeckTwist01',axis_q([0,1,0],-.15));physical,_=a.physical_pose((p,q),lift);mouth=physical[b.index('Head')]+[.075,0,-.055];p,q=a.physical_ik((p,q),'R',mouth+[.01,-.06,-.25],lift=lift);bite=1-smooth((t-23.18)/.3);p,q=rotate_branch(b,p,q,'JawRoot',axis_q([0,1,0],.13+.075*math.sin(t*14)*bite));p,q=b.glance(p,q,.45*window(t,11.2,12,.2));state='chews_then_releases_old_bag'
            else:
                p,q=b.glance(p,q,.40*window(t,28.2,29.1,.16));p,q=reach(b,p,q,'R',[.42,-.15,1.02]);state='search_noise_after_abandoning_bag'
        elif aid=='A01':
            p,q=b.glance(p,q,.80*pulse(t,12.3,1.1)-.72*pulse(t,13.6,1.2));p,q=reach(b,p,q,'L',[.12,.17,1.30+.04*math.sin(t*2)]);p,q=rotate_branch(b,p,q,'Spine02',axis_q([0,0,1],.18*smooth((t-14.1)/.5)));state='listen_wrong_side_then_lock'
        elif aid=='A02':
            # One actual fixed ring and a delayed second grip, with a measured
            # right-foot anchor rather than a free-floating pendulum.
            base,_=a.physical_pose((p,q),lift);c,s=math.cos(yaw),math.sin(yaw);rot=np.array([[c,s,0],[-s,c,0],[0,0,1]])
            if self.sway_foot_world is None:self.sway_foot_world=base[b.index('R_Foot')]@rot+[*xy,0]
            sway=.10*math.sin((t-15)*1.9);p,q=rotate_branch(b,p,q,'Hip',axis_q([1,0,0],sway));p,q=a.physical_ik((p,q),'R',(self.sway_foot_world-[*xy,0])@rot.T,lift=lift,foot=True);goal=(np.array([20.20,-1.39,1.74])-[*xy,0])@rot.T;p,q=a.physical_ik((p,q),'L',goal,lift=lift);p,q=close_fingers(b,p,q,'L',goal+[-.05,0,.07-lift]);p,q=reach(b,p,q,'R',[.17,-.18,1.29+.25*pulse(t,16.4,1.5)]);state='ring_holds_body_then_late_release'
        elif aid.startswith('L'):
            i=int(aid[1:])-1;trigger=[25.15,25.8,26.2,26.75,27.1,27.65][i];w=.5+.5*math.sin((t-9)*1.5+i*1.17);lock=smooth((t-trigger)/.32)
            if i%3==0:p,q=reach(b,p,q,'R',[.20,.12,1.07+.17*w]);p,q=reach(b,p,q,'L',[.22,.27,1.15])
            elif i%3==1:p,q=reach(b,p,q,'L',[.20,.27,1.42+.08*w])
            else:p,q=reach(b,p,q,'R',[.17,-.30,1.05+.18*w])
            p,q=b.glance(p,q,.23*math.sin(t*.65+i)+.62*lock);p,q=rotate_branch(b,p,q,'JawRoot',axis_q([0,1,0],.09+.08*lock));state='paired_slow_task' if not lock else 'reaction_to_bottle_partner_or_motion'
        elif aid=='F03':
            rise=smooth((t-65.2)/1.15);p,q=b.mix(b.pose(20,'crouch'),(p,q),rise);lift=a.ground_lift('crouch',20)*(1-rise)+lift*rise
            if 64<t<66.6:
                c,s=math.cos(yaw),math.sin(yaw);v=np.array([25.15,6.47,.53])-[*xy,0];goal=np.array([c*v[0]+s*v[1],-s*v[0]+c*v[1],v[2]]);target=a.physical_ik((p,q),'L',goal,lift=lift);p,q=b.mix((p,q),target,window(t,64,66.05,.12));p,q=reach(b,p,q,'R',[.30,-.21,1.02])
            p,q=rotate_branch(b,p,q,'Spine01',axis_q([0,1,0],.2*window(t,66,68,.2)));state='low_bench_support_rise_block'
        elif aid=='F04' and t>79:
            hit=window(t,81.3,82.2,.1);p,q=rotate_branch(b,p,q,'Hip',axis_q([0,1,0],.12*hit));p,q=rotate_branch(b,p,q,'Spine01',axis_q([0,1,0],.10*hit));p,q=reach(b,p,q,'R',[.40,-.20,1.38]);p,q=reach(b,p,q,'L',[.37,.20,1.17]);p,q=bend_fingers(b,p,q,'R',.5);p,q=b.glance(p,q,-.55*window(t,82.3,83.0,.2));state='gate_impact_rebound_listen_retry'
        elif aid=='F01' and t<30:
            start=smooth((t-28.6)/.6);p,q=b.glance(p,q,.45*start);p,q=rotate_branch(b,p,q,'Spine01',axis_q([0,1,0],.16*start));state='locks_companion_then_first_steps'
        elif aid=='F01' and 67<t<71:
            p,q=reach(b,p,q,'R',[.42,-.08,1.22]);p,q=b.glance(p,q,-.65*window(t,68,69,.16));state='overshoot_column_then_search'
        elif aid=='A04':
            p,q=reach(b,p,q,'L',[.40,.20,1.27]);p,q=b.glance(p,q,.28*math.sin(t*.6));state='touches_wall_follows_distant_movement'
        elif speed<.1 and not aid.startswith('H'):
            p,q=b.glance(p,q,.45*math.sin(t*.65+int(aid[1:])));state='lost_target_search'
        p,q=rotate_branch(b,p,q,'Spine02',axis_q([0,1,0],.011*math.sin(t*2.2+int(aid[1:])*.7)))
        return xy,yaw,speed,(p,q),lift,phase,clip,state

    def update(self,f):
        t=float(f)/30;row={'source_tick':f,'story_time_s':t,'shot':self.score.shot(t),'actors':{},'gate_translation_x_m':self.score.gate(t),'events':[]};self.scene['gate_op'].Set(Gf.Vec3d(self.score.gate(t),0,0));b=self.bank
        for aid,a in self.actors.items():
            support={};weight=0.
            if aid in self.layers:
                xy,yaw,speed=self.score.door.root(aid,t-53);pose,lift,support,weight,phase=self.layers[aid].evaluate(t-53);clip='authored_phrase' if weight>.5 else 'final';state=self.score.door.state(aid,t-53)
            else:xy,yaw,speed,pose,lift,phase,clip,state=self.generic(aid,t)
            a.safe_update(pose,[*xy,0],yaw,lift);m=np.asarray(a.matrix);shoe=np.concatenate(list(a.foot_points().values()));adjust=self.floor.correction(shoe@m[:3,:3]+m[3,:3])
            if adjust>.2:raise ValueError(f'excessive floor correction {aid}:{t}:{adjust}')
            if adjust:lift+=adjust;a.safe_update(pose,[*xy,0],yaw,lift)
            if aid=='A03' and self.floorbag:
                if self.bag_anchor is None:
                    anchor=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0,0,1),math.degrees(-.65)));anchor.SetTranslateOnly(Gf.Vec3d(14.1,7.22,0));self.bag_anchor=anchor

                if not self.floorbag_frozen:self.floorbag.update(11+(min(t,24.1)-23.35),1-smooth((t-23.18)/.3))
                self.floorbag_frozen=t>=24.1;self.oldbag_op.Set(self.bag_anchor*Gf.Matrix4d(a.matrix).GetInverse())
            if aid=='H02' and t>=85.7:
                head=a.joint_p[b.index('Head')]+[.075,0,-.055];hand=a.joint_p[b.index('R_Hand')];shoulder=a.joint_p[b.index('R_Upperarm')];bite=smooth((t-85.7)/1.2);tip=shoulder*(1-bite)+head*bite;ribbon(self.stage,a.path+'/Bag/OwnStrapInMouth',[shoulder,hand,tip],.035,(.38,.43,.36))
            row['actors'][aid]={'root_world_m':[*map(float,xy),0.],'yaw_rad':float(yaw),'speed_mps':speed,'phase':float(phase),'gait':clip,'behavior':state,'state':state,'support':support,'foot_phrase_weight':weight,'ground_adjustment_m':adjust,'root_owner':'exclusive authored feature score','committed_target_m':self.score.door.attack_target(t-53).tolist() if aid=='F02' and 57.65<=t<63 else None}
        self.camera(t,row);cam=self.stage.GetPrimAtPath('/World/Camera');row['camera_matrix']=np.asarray(UsdGeom.Xformable(cam).GetOrderedXformOps()[0].Get()).tolist();row['camera_focal_mm']=float(cam.GetAttribute('focalLength').Get());return row

    def camera(self,t,row):
        h=np.array(row['actors'].get('H01',{'root_world_m':[8,3,0]})['root_world_m']);teal=np.array(row['actors'].get('H02',{'root_world_m':[16,5,0]})['root_world_m'])
        if t<12:eye=[14.85,5.2,.62];target=[14.30,7.10,.56];fov=43
        elif t<15:eye=[20.8+.25*smooth((t-12)/3),4.9,1.55];target=[19.05,7.3,1.25];fov=42
        elif t<18:eye=[23.55,-.65,1.25];target=[20.20,-1.44,1.0];fov=60
        elif t<21:eye=[21.8,6.0,1.70];target=[18.3,3.3,1.0];fov=76
        elif t<28:eye=[23.0,6.5,1.7];target=[18.8,3.7,1.0];fov=78
        elif t<33:eye=[12.8,2.1,1.20];target=[12.8,5.65,1.0];fov=100
        elif t<37:eye=[teal[0]+1.5,1.7,1.5];target=[teal[0]-2.5,4.4,1.0];fov=80
        elif t<41:
            center=np.mean([self.score.root(a,t)[0] for a in ['P04','P05','P06']],axis=0);eye=[center[0]+3.5,center[1]-3.0,1.4];target=[*center,1.0];fov=82
        elif t<46:eye=[18.,.7,2.8];target=[18.,7.2,1.0];fov=115
        elif t<51:eye=[h[0]+2.8,max(.8,h[1]-3.1),1.4];target=h+[0,0,1.0];fov=60
        elif t<53:eye=[h[0]+2.3,6.0,1.3];target=[h[0],.6,1.0];fov=70
        elif t<63:
            u=t-53;red=np.array(row['actors']['F02']['root_world_m']);pre=smooth((u-2)/2.2);eye=np.array([h[0]+1.8,6.2,1.4])*(1-pre)+np.array([26.8,7.8,1.5])*pre;eye[2]+=1.0*smooth((u-6.8)/.9);late=smooth((u-7.0)/2.0);eye=eye*(1-late)+np.array([22.5,7.7,2.1])*late;target=.55*h+.45*red+[0,0,1.0];fov=64
        elif t<65:eye=[25.0,5.25,1.45];target=[23.7,3.36,1.17];fov=48
        elif t<69:eye=[27.8,4.8,.95];target=[24.7,6.10,.78];fov=65
        elif t<73:eye=[22.4,8.1,1.55];target=[24.5,6.6,1.03];fov=80
        elif t<77:eye=[28.5,10.2,1.55];target=[25.4,7.9,1.0];fov=75
        elif t<80:eye=[28.,12.4+.15*(t-77),1.5];target=[27.7,8.8,.98];fov=74
        elif t<84:eye=[28.9,11.7,1.55];target=[27.9,9.25,1.12];fov=70
        elif t<87:eye=[27.4,13.0,1.52];target=[26.9,11.15,1.32];fov=62
        else:
            u=smooth((t-88.7)/.7);eye=np.array([26.55,12.4,1.43])*(1-u)+np.array([27.6,12.6,1.58])*u;target=np.array([27.38,11.2,1.48])*(1-u)+np.array([26.3,11.1,1.52])*u;fov=46
        aim(self.stage,np.asarray(eye).tolist(),np.asarray(target).tolist(),fov)
