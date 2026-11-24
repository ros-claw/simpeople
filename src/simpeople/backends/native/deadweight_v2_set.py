"""Readable coast and metrically measured wheel/rail movie geometry (not contact physics)."""
import math
from pathlib import Path
import numpy as np
from pxr import Usd,UsdGeom,UsdShade,UsdLux,Gf,Sdf,Vt
from .deadweight_set import create_car,box,label,RUN,FLOOR

LENGTH=112.;SLOPE=math.pi/6;T=np.array([math.cos(SLOPE),0,math.sin(SLOPE)]);N=np.array([-math.sin(SLOPE),0,math.cos(SLOPE)])

def terrain_height(x,y):
    x=np.asarray(x);y=np.asarray(y);rail=3+np.clip(x,0,111)*math.tan(SLOPE)
    front=np.clip((y+36)/30,0,1);front=front*front*(3-2*front)
    high=(rail+2.65)*front-4+np.clip((y-5)/10,0,1)*8
    ravine=14*np.exp(-((x-52)/14)**6)*np.clip((8-y)/7,0,1)
    noise=(.48*np.sin(x*.23+y*.31)+.30*np.sin(x*.67-y*.38))*np.clip((-y-5)/7,0,1)*front
    return np.maximum(-3,high-ravine+noise)

def surface_material(stage,mesh,color,texture=None,water=False):
    path=str(mesh.GetPath())+'/Material';mat=UsdShade.Material.Define(stage,path);shader=UsdShade.Shader.Define(stage,path+'/Surface');shader.CreateIdAttr('UsdPreviewSurface')
    shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color));shader.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(.38 if water else .94);shader.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(0.);shader.CreateInput('ior',Sdf.ValueTypeNames.Float).Set(1.333 if water else 1.5)
    if texture:
        reader=UsdShade.Shader.Define(stage,path+'/UV');reader.CreateIdAttr('UsdPrimvarReader_float2');reader.CreateInput('varname',Sdf.ValueTypeNames.Token).Set('st')
        tex=UsdShade.Shader.Define(stage,path+'/Texture');tex.CreateIdAttr('UsdUVTexture');tex.CreateInput('file',Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(texture)));tex.CreateInput('st',Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(),'result');tex.CreateInput('wrapS',Sdf.ValueTypeNames.Token).Set('repeat');tex.CreateInput('wrapT',Sdf.ValueTypeNames.Token).Set('repeat');tex.CreateInput('sourceColorSpace',Sdf.ValueTypeNames.Token).Set('sRGB');shader.GetInput('diffuseColor').ConnectToSource(tex.ConnectableAPI(),'rgb')
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface');UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(mat)

def surface(stage,path,xs,ys,zfunc,color):
    x,y=np.meshgrid(xs,ys);z=zfunc(x,y);points=np.stack([x,y,z],axis=-1)
    nx,ny=len(xs),len(ys);indices=[]
    for j in range(ny-1):
        for i in range(nx-1):
            a=j*nx+i;indices.extend([a,a+1,a+nx+1,a+nx])
    mesh=UsdGeom.Mesh.Define(stage,path);mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(points.reshape(-1,3).astype(np.float32)));mesh.CreateFaceVertexCountsAttr([4]*((nx-1)*(ny-1)));mesh.CreateFaceVertexIndicesAttr(indices);mesh.CreateSubdivisionSchemeAttr('none');mesh.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    dx=np.gradient(z,xs,axis=1);dy=np.gradient(z,ys,axis=0);norm=np.stack([-dx,-dy,np.ones_like(z)],axis=-1);norm/=np.linalg.norm(norm,axis=-1)[...,None];mesh.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(norm.reshape(-1,3).astype(np.float32)));mesh.SetNormalsInterpolation('vertex');return mesh

def wheel_mesh(stage,path,radius=.34,width=.18):
    count=64;theta=np.arange(count)*2*np.pi/count
    points=np.array([[radius*np.sin(a),y,radius*np.cos(a)] for y in [-width/2,width/2] for a in theta]);faces=[]
    for i in range(count):faces.extend([i,(i+1)%count,(i+1)%count+count,i+count])
    mesh=UsdGeom.Mesh.Define(stage,path);mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(points.astype(np.float32)));mesh.CreateFaceVertexCountsAttr([4]*count);mesh.CreateFaceVertexIndicesAttr(faces);mesh.CreateSubdivisionSchemeAttr('none');mesh.CreateDisplayColorAttr([Gf.Vec3f(.15,.17,.18)])
    for end,y in [('Outer',-width/2),('Inner',width/2)]:
        disk=UsdGeom.Cylinder.Define(stage,path+'/'+end);disk.CreateAxisAttr('Y');disk.CreateRadiusAttr(radius);disk.CreateHeightAttr(.012);disk.AddTranslateOp().Set(Gf.Vec3d(0,y,0));disk.CreateDisplayColorAttr([Gf.Vec3f(.16,.18,.19)])
    # A genuine geometry witness. It rolls with the same axle, not an overlay.
    box(stage,path+'/WearMark',(0,-width/2-.009,radius*.58),(.035,.01,radius*.78),(.88,.64,.18),.1,.35)
    box(stage,path+'/WearMarkInner',(0,width/2+.009,radius*.58),(.035,.01,radius*.78),(.88,.64,.18),.1,.35)
    return mesh

class RailGeometry:
    def __init__(self,stage,cars):
        self.stage=stage;self.cars=cars;self.wheels={};self.previous_angles={}
        for name,car in cars.items():
            root=car['root']
            remove=[p.GetPath() for p in Usd.PrimRange(stage.GetPrimAtPath(root)) if p.GetName().startswith('Wheel') or p.GetName()=='Chassis']
            for path in remove:stage.RemovePrim(path)
            bogie=UsdGeom.Xform.Define(stage,root+'/Bogie');bogie.AddRotateYOp().Set(-30)
            box(stage,root+'/Bogie/Spine',(0,0,.25),(6.4,1.45,.20),(.17,.20,.21),.6)
            # Level cabin floor over a 30 degree running frame: visibly carry
            # the floor on the axles instead of leaving an unsupported gap.
            for side,y in enumerate([-.65,.65]):
                ends=[]
                for ax,x in enumerate([-2.8,2.8]):
                    bottom=T*x+N*.45;topz=FLOOR-.24;ends.append(np.array([bottom[0],y,bottom[2]]));height=topz-bottom[2]
                    box(stage,root+f'/Suspension/Post{ax}_{side}',(bottom[0],y,(topz+bottom[2])/2),(.14,.14,height),(.17,.20,.21),.65)
                box(stage,root+f'/Suspension/FloorBeam{side}',(0,y,FLOOR-.26),(10.8,.18,.20),(.17,.20,.21),.65)
                start=ends[0];finish=np.array([ends[1][0],y,FLOOR-.28]);vec=finish-start;beam=box(stage,root+f'/Suspension/Brace{side}',(start+finish)/2,(float(np.linalg.norm(vec)),.12,.12),(.17,.20,.21),.65);beam.AddRotateYOp().Set(-math.degrees(math.atan2(vec[2],vec[0])))
            self.wheels[name]={}
            for ax,x in enumerate([-2.8,2.8]):
                box(stage,root+f'/Bogie/Axle{ax}',(x,0,.42),(.11,2.04,.11),(.3,.32,.33),.8)
                for side,y in enumerate([-.85,.85]):
                    path=root+f'/Bogie/Wheel{ax}_{side}';xf=UsdGeom.Xform.Define(stage,path);xf.AddTranslateOp().Set(Gf.Vec3d(x,y,.08+.34));spin=xf.AddRotateYOp()
                    mesh=wheel_mesh(stage,path+'/Tread')
                    flange=UsdGeom.Cylinder.Define(stage,path+'/Flange');flange.CreateAxisAttr('Y');flange.CreateRadiusAttr(.385);flange.CreateHeightAttr(.025);flange.AddTranslateOp().Set(Gf.Vec3d(0,.11 if y<0 else -.11,0));flange.CreateDisplayColorAttr([Gf.Vec3f(.10,.13,.15)])
                    self.wheels[name][f'{ax}_{side}']={'mesh':mesh,'spin':spin,'rail':f'/World/Track/{name}Rail{side}'}

    def apply(self,q):
        for name,car in self.cars.items():
            s=LENGTH-q if name=='A' else q;y=-2.4 if name=='A' else 2.4
            car['xform'].Set(Gf.Vec3d(s*T[0],y,3+s*T[2]))
            for wheel in self.wheels[name].values():wheel['spin'].Set(math.degrees(((-q) if name=='A' else q)/.34))

    def calibration(self):
        xf=UsdGeom.XformCache();lanes={}
        for name,y in [('A',-2.4),('B',2.4)]:
            wheels={}
            for wid,w in self.wheels[name].items():
                points=np.array(w['mesh'].GetPointsAttr().Get());center=points.mean(0);radius=float(np.max(np.linalg.norm((points-center)[:,[0,2]],axis=1)))
                rail=self.stage.GetPrimAtPath(w['rail']);world=np.array([xf.GetLocalToWorldTransform(rail).Transform(Gf.Vec3d(*map(float,v))) for v in UsdGeom.Mesh(rail).GetPointsAttr().Get()]);top=world[np.argsort(world@N)[-4:]].mean(0)
                wheels[wid]={'rail_top_point_m':top.tolist(),'radius_m':radius,'angle_sign':1,'lateral_design_offset_m':0}
            lanes[name]={'low_datum_m':[0,y,3],'high_datum_m':[RUN,y,59],'wheels':wheels}
        return {'lanes':lanes,'limits':{'contact_m':.01,'lateral_m':.01,'roll_m':.003,'roll_cumulative_m':.02,'cable_m':.01},'min_observed_travel_m':5,'provenance':'rail top from transformed mesh vertices; tread radius and witness from real wheel mesh; no contact force measurement'}

    def read(self):
        xf=UsdGeom.XformCache();result={}
        for name,car in self.cars.items():
            values={}
            for wid,w in self.wheels[name].items():
                points=np.asarray(w['mesh'].GetPointsAttr().Get());matrix=xf.GetLocalToWorldTransform(w['mesh'].GetPrim());m=np.asarray(matrix);world=points@m[:3,:3]+m[3,:3];center=world.mean(0)
                # Vertex 0 is a radial witness at +normal in the unspun tread.
                radial=world[0]-center;radial[1]=0;angle=math.atan2(float(radial@T),float(radial@N));key=name+wid
                prev=self.previous_angles.get(key,angle);angle+=2*math.pi*round((prev-angle)/(2*math.pi));self.previous_angles[key]=angle
                values[wid]={'center_world_m':center.tolist(),'angle_rad':angle}
            datum=xf.GetLocalToWorldTransform(self.stage.GetPrimAtPath(car['root'])).ExtractTranslation();result[name]={'datum_world_m':list(datum),'wheels':values}
        return result

def create_scene(stage,root,*,storm=False,rocks=True):
    root=Path(root);UsdGeom.Xform.Define(stage,'/World');stage.SetDefaultPrim(stage.GetPrimAtPath('/World'));UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z');stage.SetTimeCodesPerSecond(30)
    ground=surface(stage,'/World/Coast/ContinuousGround',np.linspace(-90,210,280),np.linspace(-85,150,200),terrain_height,(.31,.30,.26))
    pts=np.asarray(ground.GetPointsAttr().Get());uv=np.column_stack([pts[:,0]/11,(pts[:,1]*.45+pts[:,2])/11]);UsdGeom.PrimvarsAPI(ground).CreatePrimvar('st',Sdf.ValueTypeNames.TexCoord2fArray,'vertex').Set(Vt.Vec2fArray.FromNumpy(uv.astype(np.float32)))
    surface_material(stage,ground,(.31,.30,.26),root/'.runtime/deadweight/Deadweight_Feasibility_Assets/coast/textures/coastal_cliff_02_diff_1k.jpg')
    sea=surface(stage,'/World/Sea',np.linspace(-250,300,180),np.linspace(-300,-20,120),lambda x,y:.07*np.sin(x*.23+y*.14)+.025*np.cos(x*.6-y*.21),(.075,.15,.17));surface_material(stage,sea,(.008,.025,.033),water=True)
    if rocks:
        asset=root/'.runtime/deadweight/Deadweight_Feasibility_Assets/coast/coastal_cliff_02_1k.usdc'
        for i,x in enumerate([7,39,71,103]):
            rock=UsdGeom.Xform.Define(stage,f'/World/Coast/Scan{i}');rock.GetPrim().GetReferences().AddReference(str(asset));rock.AddTranslateOp().Set(Gf.Vec3d(x,-17,float(terrain_height(x,-17))-3));rock.AddRotateXYZOp().Set(Gf.Vec3f(0,-30,0));rock.GetPrim().SetInstanceable(True)
    for name,y in [('A',-2.4),('B',2.4)]:
        bed=box(stage,f'/World/Track/{name}Bed',(RUN/2,y,30.46),(120,2.25,.48),(.23,.23,.21),.3);bed.AddRotateYOp().Set(-30)
        for side,dy in enumerate([-.85,.85]):
            rail=box(stage,f'/World/Track/{name}Rail{side}',(RUN/2,y+dy,31),(120,.12,.16),(.33,.34,.33),.8,.22);rail.AddRotateYOp().Set(-30)
        for i in range(83):
            s=-3+i*118/82;point=T*s+np.array([0,y,3]);part=box(stage,f'/World/Track/{name}Sleeper{i}',point+N*(-.21),(.21,2.1,.18),(.26,.23,.19));part.AddRotateYOp().Set(-30)
    # Retaining shoulders on the ground; only the central ravine is bridged.
    for i,x in enumerate([5,20,35,47,62,77,92]):
        for j,y in enumerate([-3.5,3.5]):
            ground=float(terrain_height(x,y));top=3+x*math.tan(SLOPE)-.7;height=top-ground
            bottom=min(float(terrain_height(x+dx,y+dy)) for dx in [-1.3,1.3] for dy in [-1.3,1.3])-.4;topbase=ground+.2
            box(stage,f'/World/Foundations/Foot{i}_{j}',(x,y,(bottom+topbase)/2),(2.6,2.6,topbase-bottom),(.36,.36,.32))
            if height>.1:box(stage,f'/World/Foundations/Pier{i}_{j}',(x,y,ground+height/2),(1.1,1.2,height),(.42,.41,.36))
        box(stage,f'/World/Foundations/Cap{i}',(x,0,3+x*math.tan(SLOPE)-.74),(1.4,8.2,.5),(.39,.38,.34))
    # Visible seawall and tide scale, separately from the isolated refuge.
    box(stage,'/World/Lower/Seawall',(0,-13,1.8),(23,1.3,7.1),(.40,.40,.36))
    for z in range(6):
        box(stage,f'/World/Lower/TideMark{z}',(-7,-13.69,z),(.65,.018,.035),(.9,.85,.65));label(stage,f'/World/Lower/TideText{z}',str(z)+'m',(-6.1,-13.71,z-.08),.19,(.12,.15,.15))
    for name,x,y,z in [('Upper',RUN,-8.75,59+FLOOR),('Lower',0,8.75,3+FLOOR)]:
        box(stage,f'/World/{name}/Platform',(x,y,z-.24),(19,9,.48),(.48,.46,.41))
        box(stage,f'/World/{name}/Edge',(x,y+(4.45 if y<0 else -4.45),z+.008),(18,.16,.016),(.88,.68,.21))
        for j,dx in enumerate([-8,8]):
            for k,dy in enumerate([-3.8,3.8]):
                ground=float(terrain_height(x+dx,y+dy));height=max(.4,z-ground-.25)
                bottom=min(float(terrain_height(x+dx+sx,y+dy+sy)) for sx in [-1.2,1.2] for sy in [-1.2,1.2])-.4;topbase=ground+.2
                box(stage,f'/World/{name}/Foot{j}_{k}',(x+dx,y+dy,(bottom+topbase)/2),(2.4,2.4,topbase-bottom),(.40,.39,.34));box(stage,f'/World/{name}/Support{j}_{k}',(x+dx,y+dy,ground+height/2),(.7,.7,height),(.42,.41,.36))
        box(stage,f'/World/{name}/Kiosk',(x-5,y-2,z+1.3),(3.4,2.0,2.6),(.26,.31,.29))
        box(stage,f'/World/{name}/KioskWindow',(x-5,y-3.02,z+1.5),(2.4,.04,1.15),(.11,.17,.18),.1)
        box(stage,f'/World/{name}/Canopy',(x-5,y-1.8,z+2.85),(4.1,2.8,.16),(.21,.26,.25),.3)
        label(stage,f'/World/{name}/Sign','SUMMIT / PHOTO' if name=='Upper' else 'TIDELINE / TICKETS',(x-6.35,y-3.06,z+2.3),.20,(.9,.82,.60))
        for i in range(17):
            px=x-8+i
            box(stage,f'/World/{name}/RailPost{i}',(px,y-4.35,z+.52),(.045,.045,1.04),(.28,.31,.29),.6)
        box(stage,f'/World/{name}/Handrail',(x,y-4.35,z+1.05),(16.5,.055,.055),(.47,.45,.35),.6)
        for i in range(9):box(stage,f'/World/{name}/Joint{i}',(x-8+i*2,y,z+.003),(.012,8,.006),(.30,.30,.28))
    # Isolated lower refuge: no connection to the public B platform.
    box(stage,'/World/Refuge/Deck',(-5.1,-6,5.40),(3,4.7,.46),(.43,.45,.42),.3)
    for j,x in enumerate([-6.55,-3.65]):
        for i in range(4):box(stage,f'/World/Refuge/Post{j}_{i}',(x,-4.2-i*1.15,6.15),(.055,.055,1.05),(.43,.42,.33),.6)
        box(stage,f'/World/Refuge/Rail{j}',(x,-6,6.68),(.06,4.6,.06),(.78,.64,.27),.6)
        box(stage,f'/World/Refuge/Base{j}',(x,-6,2.55),(.6,.8,5.2),(.40,.40,.36))
    box(stage,'/World/Upper/WaterTank',(RUN+7,-10,63.0),(1.4,1.2,2.6),(.31,.36,.35),.4)
    box(stage,'/World/Upper/SupplyPipe',(RUN+5.8,-10.2,63.7),(2.3,.11,.11),(.42,.32,.20),.7)
    valve=UsdGeom.Cylinder.Define(stage,'/World/Upper/Valve');valve.CreateAxisAttr('Y');valve.CreateRadiusAttr(.15);valve.CreateHeightAttr(.04);valve.AddTranslateOp().Set(Gf.Vec3d(RUN+5.2,-10.3,63.7));valve.CreateDisplayColorAttr([Gf.Vec3f(.52,.17,.10)])
    for i in range(5):box(stage,f'/World/Upper/WaterLevel{i}',(RUN+6.28,-10.62,62.1+i*.4),(.025,.015,.02),(.9,.8,.5))
    label(stage,'/World/Upper/WaterCaption','SUPPLY / EMPTY',(RUN+6.4,-10.63,64.1),.16,(.96,.72,.3))
    camera=UsdGeom.Camera.Define(stage,'/World/Camera');camera.AddTransformOp();camera.CreateHorizontalApertureAttr(36);camera.CreateVerticalApertureAttr(20.25);camera.CreateClippingRangeAttr(Gf.Vec2f(.06,700));camera.CreateFocalLengthAttr(35)
    dome=UsdLux.DomeLight.Define(stage,'/World/Lights/Sky');dome.CreateIntensityAttr(650 if not storm else 430);dome.CreateColorAttr(Gf.Vec3f(.9,.92,.94))
    sky=Path('/data/omniverse/Assets/Isaac/5.1/Isaac/Materials/Textures/Skies/PolyHaven/kloofendal_43d_clear_puresky_4k.hdr')
    if sky.exists():dome.CreateTextureFileAttr(Sdf.AssetPath(str(sky)));dome.CreateTextureFormatAttr('latlong')
    sun=UsdLux.DistantLight.Define(stage,'/World/Lights/Day');sun.CreateIntensityAttr(1700 if not storm else 950);sun.CreateColorAttr(Gf.Vec3f(.97,.94,.87));sun.CreateAngleAttr(8);sun.AddRotateXYZOp().Set(Gf.Vec3f(30,-35,-30))
    cars={'A':create_car(stage,'A',(.13,.30,.35)),'B':create_car(stage,'B',(.64,.40,.12))};geometry=RailGeometry(stage,cars);geometry.apply(0)
    # Both branches are visible; the upper drive is a passive brake sheave.
    for name,y in [('A',-2.4),('B',2.4)]:
        cable=UsdGeom.BasisCurves.Define(stage,f'/World/Cable/{name}');cable.CreateTypeAttr('linear');cable.CreateCurveVertexCountsAttr([2]);cable.CreateWidthsAttr([.045]);cable.SetWidthsInterpolation('constant');cable.CreatePointsAttr([Gf.Vec3f(0,y,3.14),Gf.Vec3f(RUN,y,59.14)]);cable.CreateDisplayColorAttr([Gf.Vec3f(.17,.18,.17)])
    for name,car in cars.items():
        for key,op in car['doors'].items():op.Set(Gf.Vec3d(0,0,2.6) if key=='inner' else Gf.Vec3d(1.85,0,0))
        stage.RemovePrim(car['root']+'/Number')
    # Explicit fixture lights, neutral face fill; no green panorama horizon.
    for name,car in cars.items():
        light=stage.GetPrimAtPath(car['root']+'/CabinLight');light.GetAttribute('inputs:intensity').Set(450);light.GetAttribute('inputs:color').Set(Gf.Vec3f(*((.75,.84,.92) if name=='A' else (1,.75,.45))))
    return cars,geometry

def aim(stage,eye,target,lens=40):
    camera=stage.GetPrimAtPath('/World/Camera');UsdGeom.Xformable(camera).GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float,eye)),Gf.Vec3d(*map(float,target)),Gf.Vec3d(0,0,1)).GetInverse());camera.GetAttribute('focalLength').Set(lens)

class Weather:
    """Explicit cinematic rain, never used to hide the dry geometry review."""
    def __init__(self,stage):
        rng=np.random.default_rng(8822);self.seeds=np.column_stack([rng.uniform(-16,118,1400),rng.uniform(-24,18,1400),rng.uniform(0,78,1400)])
        self.curves=UsdGeom.BasisCurves.Define(stage,'/World/Weather/Rain');self.curves.CreateTypeAttr('linear');self.curves.CreateCurveVertexCountsAttr([2]*len(self.seeds));self.curves.CreateWidthsAttr([.002]);self.curves.SetWidthsInterpolation('constant');self.curves.CreateDisplayColorAttr([Gf.Vec3f(.40,.49,.52)]);self.curves.CreatePointsAttr();self.update(0)
    def update(self,t):
        a=self.seeds.copy();a[:,2]=(a[:,2]-t*15)%78;b=a+np.array([.1,.02,-.65]);self.curves.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(np.stack([a,b],axis=1).reshape(-1,3).astype(np.float32)))
