"""Director overlay: distinct signs, motivated gate light and small real props."""
import math
import numpy as np
from pxr import UsdGeom,UsdLux,UsdShade,UsdPhysics,Gf,Vt,Sdf
from .platform04_scene import create_metro
from .deadweight_set import box,label
from .deadweight_cinema import quat_apply


def create_director_scene(stage,root,*,collision=False):
    scene=create_metro(stage,root,collision=collision)
    # Recess the service foyer's left wall so the long opening view can see
    # into the open passage instead of mistaking an oblique side wall for a door.
    for b in scene['boxes']:
        if b['name'] in ['ExitPassage_sidewall_0115','ExitPassage_exitGuideStripe_0116']:
            b['center'][1]=14.7;b['size'][1]=5.2;mesh=UsdGeom.Mesh.Get(stage,'/World/Metro/'+b['group']+'/'+b['name']);x,y,z=np.array(b['size'])/2;mesh.GetPointsAttr().Set([(-x,-y,-z),(x,-y,-z),(x,y,-z),(-x,y,-z),(-x,-y,z),(x,-y,z),(x,y,z),(-x,y,z)]);UsdGeom.Xformable(mesh).GetOrderedXformOps()[0].Set(Gf.Vec3d(*b['center']))
    for b in scene['boxes']:
        if ((b['group']=='StationProps' and ('stationID' in b['name'] or '_mark_' in b['name']))
            or (b['group']=='Car' and ('coachNumber' in b['name'] or '_mark_' in b['name']))):
            stage.RemovePrim('/World/Metro/'+b['group']+'/'+b['name'])
    for x in [1.,17.5,35.5]:
        box(stage,f'/World/Director/Signs/WallBack{int(x)}',(x,8.625,2.40),(1.80,.055,.65),(.025,.055,.06),.1)
        label(stage,f'/World/Director/Signs/Wall04_{int(x)}','04',(x-.50,8.585,2.20),.48,(.88,.91,.84))
    for i,x in enumerate([5,14,23,32],1):
        box(stage,f'/World/Director/Signs/DoorBack{i}',(x,-.15,2.30),(1.20,.05,.27),(.035,.06,.065),.3)
        label(stage,f'/World/Director/Signs/Door{i}',f'D{i:02}',(x+.38,-.11,2.21),.20,(.90,.86,.65),180)
    stage.RemovePrim('/World/Metro/ProductionSign');stage.RemovePrim('/World/Metro/TrainSign')
    for i,x in enumerate([25.15,30.85]):
        p=box(stage,f'/World/Director/GateLamp/Strip{i}',(x,8.61,1.50),(.075,.08,2.95),(.035,.65,.36),.05)
        shader=UsdShade.Shader(stage.GetPrimAtPath(str(p.GetPath())+'/Material/Surface'));shader.CreateInput('emissiveColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(.055,2.6,.83))
    box(stage,'/World/Director/GateLamp/Header',(28,8.61,3.00),(5.80,.08,.085),(.045,.65,.37),.05)
    label(stage,'/World/Director/StaffOnly','STAFF  /  THIS WAY',(25.5,8.56,3.25),.30,(.45,.94,.65))
    for name,eye,target,power,color in [
        ('OpeningFaces',[10,4.4,2.8],[8.7,2.4,1.2],1900,(.84,.90,1)),
        ('CompanionFace',[10.0,3.0,2.3],[11.6,3.6,1.3],2400,(.86,.90,.93)),
        ('ChewerFace',[7.0,5.7,2.0],[5.8,7.22,.75],2300,(.93,.84,.72)),
        ('ListenerFace',[19.7,5.1,2.5],[18.4,7.36,1.3],2000,(.79,.88,.93)),
        ('SwayFace',[21.5,-.5,2.3],[20.2,-1.44,1.2],2200,(1,.79,.63)),
        ('GateFace',[28,7.1,2.4],[27.4,8.3,1.3],2700,(.78,1,.87)),
        ('ExitInterior',[28,12.1,2.6],[28,10.2,1.2],1700,(.68,.91,.83)),
        ('BenchAccent',[24,5.1,2.9],[25.4,6.6,.8],2000,(.86,.86,.91))]:
        light=UsdLux.RectLight.Define(stage,'/World/Director/Lights/'+name);light.CreateWidthAttr(2.8);light.CreateHeightAttr(1.25);light.CreateIntensityAttr(power);light.CreateColorAttr(Gf.Vec3f(*color));light.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*target),Gf.Vec3d(0,0,1)).GetInverse())
    # B3 lies beyond the interceptor door, to the wall side, outside the route
    # from the platform to the opening at X25..31. Existing old bench stays.
    center=[25.35,6.70,.47];size=[1.65,.50,.10]
    for name,pos,sz in [('Seat',center,size),('Back',[25.35,6.96,.80],[1.65,.07,.60]),('Leg0',[24.72,6.7,.23],[.10,.40,.46]),('Leg1',[25.98,6.7,.23],[.10,.40,.46])]:
        mesh=box(stage,'/World/Director/B3/'+name,pos,sz,(.22,.26,.25),.25)
        if collision:UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
        scene['boxes'].append({'group':'Director/B3','name':name,'center':pos,'size':sz,'kind':'solid','rot_z':0})
    scene['B3']={'center_m':center,'size_m':size,'minimum_clear_width_to_gate_route_m':1.0,'scope':'authored placement; navigation/hand reach must be measured separately'}
    # A fixed hanging ring gives the sway performance an actual world anchor.
    n,m=28,8;pts=[]
    for i in range(n):
        u=i*2*math.pi/n
        for j in range(m):
            v=j*2*math.pi/m;r=.071+.011*math.cos(v);pts.append([20.20+r*math.cos(u),-1.44+.011*math.sin(v),1.81+r*math.sin(u)])
    mesh=UsdGeom.Mesh.Define(stage,'/World/Director/SwayGrip/Ring');mesh.CreatePointsAttr(pts);mesh.CreateFaceVertexCountsAttr([4]*(n*m));mesh.CreateFaceVertexIndicesAttr([k for i in range(n) for j in range(m) for k in [i*m+j,((i+1)%n)*m+j,((i+1)%n)*m+(j+1)%m,i*m+(j+1)%m]]);mesh.CreateSubdivisionSchemeAttr('none');mesh.CreateDisplayColorAttr([Gf.Vec3f(.72,.72,.65)]);box(stage,'/World/Director/SwayGrip/Hanger',(20.20,-1.44,2.21),(.025,.025,.66),(.18,.21,.20),.6)
    return scene


def ribbon(stage,path,points,width=.026,color=(.18,.15,.10)):
    mesh=UsdGeom.Mesh.Get(stage,path)
    if not mesh:
        mesh=UsdGeom.Mesh.Define(stage,path);mesh.CreateSubdivisionSchemeAttr('none');mesh.CreateDoubleSidedAttr(True);mesh.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    p=np.asarray(points,float);direction=p[-1]-p[0];side=np.cross(direction,[0,1,0])
    if np.linalg.norm(side)<1e-7:side=np.array([1,0,0])
    side=side/np.linalg.norm(side)*width/2;vertices=np.stack([p-side,p+side],1).reshape(-1,3);mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(vertices.astype(np.float32)));mesh.CreateFaceVertexCountsAttr([4]*(len(p)-1));mesh.CreateFaceVertexIndicesAttr([v for i in range(len(p)-1) for v in [2*i,2*i+1,2*i+3,2*i+2]])
    return mesh


class ShoulderBag:
    def __init__(self,stage,actor,color=(.64,.40,.075)):
        self.stage=stage;self.actor=actor;self.path=actor.path+'/Bag';self.mesh=box(stage,self.path+'/Body',(0,0,0),(.21,.075,.22),color,0,.82);self.move=UsdGeom.Xformable(self.mesh).GetOrderedXformOps()[0]
        self.flap=box(stage,self.path+'/Flap',(0,0,0),(.215,.014,.085),tuple(v*.8 for v in color),0,.85);self.flap_move=UsdGeom.Xformable(self.flap).GetOrderedXformOps()[0]
        self.state={};actor.props.append(self.update)
    def update(self,actor):
        hip=actor.joint_p[actor.cache.index('L_Thigh')];shoulder=actor.joint_p[actor.cache.index('L_Upperarm')];center=hip+np.array([-.035,.20,-.10]);self.move.Set(Gf.Vec3d(*center));self.flap_move.Set(Gf.Vec3d(*(center+np.array([0,.045,.061]))))
        a=shoulder+np.array([.015,.035,.045]);b=center+np.array([.06,0,.11]);c=center+np.array([-.06,0,.11]);back=shoulder+np.array([-.045,.025,.025]);ribbon(self.stage,self.path+'/StrapFront',[a,(a+b)/2+np.array([.025,.02,0]),b],color=(.45,.31,.08));ribbon(self.stage,self.path+'/StrapBack',[back,(back+c)/2,c],color=(.41,.29,.07));self.state={'bag_center_actor_m':center.tolist(),'shoulder_anchor_actor_m':a.tolist()}


class FloorBag:
    def __init__(self,stage,actor):
        self.stage=stage;self.actor=actor;self.path=actor.path+'/OldBag';self.body=box(stage,self.path+'/Body',(0,0,0),(.30,.15,.21),(.13,.10,.07),0,.88);self.op=UsdGeom.Xformable(self.body).GetOrderedXformOps()[0];self.state={};self.release_tip=None
        vertices=[]
        for z,scale in [(-.105,.80),(-.075,1),(.055,1),(.105,.85)]:
            for x,y,start in [(.125,.05,0),(-.125,.05,math.pi/2),(-.125,-.05,math.pi),(.125,-.05,3*math.pi/2)]:
                for a in np.linspace(start,start+math.pi/2,4,endpoint=False):vertices.append([(x+.025*math.cos(a))*scale,(y+.025*math.sin(a))*scale,z])
        faces=[[k*16+i,k*16+(i+1)%16,(k+1)*16+(i+1)%16,(k+1)*16+i] for k in range(3) for i in range(16)]+[list(range(15,-1,-1)),list(range(48,64))];self.body.GetPointsAttr().Set(vertices);self.body.GetFaceVertexCountsAttr().Set([len(f) for f in faces]);self.body.GetFaceVertexIndicesAttr().Set([i for f in faces for i in f])
        self.pocket=box(stage,self.path+'/Pocket',(0,0,0),(.23,.025,.095),(.10,.075,.05),0,.88);self.pocket_op=UsdGeom.Xformable(self.pocket).GetOrderedXformOps()[0]
    def update(self,t,bite=1.):
        actor=self.actor;head=actor.joint_p[actor.cache.index('Head')];center=np.array([.35-.10*bite,.04,.115]);self.op.Set(Gf.Vec3d(*center));self.pocket_op.Set(Gf.Vec3d(*(center+[0,-.075,-.015])));mouth=head+np.array([.075,0,-.055]);base=center+np.array([0,0,.105])
        if t>=11 and self.release_tip is None:self.release_tip=mouth.copy()
        dt=max(0,t-11);released=(mouth if self.release_tip is None else self.release_tip)+np.array([.04*math.sin(dt*9)*math.exp(-dt*4),.01,-.5*9.81*dt*dt]);released[2]=max(.245,released[2]);tip=mouth*bite+released*(1-bite);mid=(base+tip)/2+np.array([0,.015,-.12*(1-bite)]);ribbon(self.stage,self.path+'/TensionedStrap',[base,mid,tip],.026,(.35,.27,.15));self.state={'bag_center_actor_m':center.tolist(),'strap_tip_actor_m':tip.tolist(),'mouth_design_point_actor_m':mouth.tolist(),'tip_to_mouth_design_gap_m':float(np.linalg.norm(tip-mouth)),'scope':'directed prop and mouth marker, not actual skin contact or cloth-force simulation'}
