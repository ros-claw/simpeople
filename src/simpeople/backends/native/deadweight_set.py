"""Original metric cliff railway movie set; no railway dynamics certification."""
import math
from pathlib import Path
from pxr import UsdGeom,UsdShade,UsdLux,UsdPhysics,Gf,Sdf

RUN=112*math.cos(math.pi/6)
FLOOR=2.63
WIDTH=3.7

def box(stage,path,pos,size,color,metal=0,rough=.45):
    # Navigation consumes triangle/quad meshes in this local SDK. Keep the
    # visible floor and the actual navigation floor the very same geometry.
    p=UsdGeom.Mesh.Define(stage,path)
    x,y,z=[v/2 for v in size]
    p.CreatePointsAttr([(-x,-y,-z),(x,-y,-z),(x,y,-z),(-x,y,-z),(-x,-y,z),(x,-y,z),(x,y,z),(-x,y,z)])
    p.CreateFaceVertexCountsAttr([4]*6);p.CreateFaceVertexIndicesAttr([0,3,2,1,4,5,6,7,0,1,5,4,1,2,6,5,2,3,7,6,3,0,4,7]);p.CreateSubdivisionSchemeAttr('none')
    # Dimensions are baked into points so a later rotation cannot be flattened
    # by a nonuniform scale op (T * S * R was a wrong rail transform).
    p.AddTranslateOp().Set(Gf.Vec3d(*pos))
    mat=UsdShade.Material.Define(stage,path+'/Material');shader=UsdShade.Shader.Define(stage,path+'/Material/Surface')
    shader.CreateIdAttr('UsdPreviewSurface');shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color));shader.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(metal);shader.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(rough)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface');UsdShade.MaterialBindingAPI.Apply(p.GetPrim()).Bind(mat)
    return p

def label(stage,path,text,pos,size=.24,color=(1,.7,.2),heading=0):
    # Native USD mesh text, with local cached font outlines, no external image.
    from matplotlib.textpath import TextPath
    import numpy as np
    polygons=TextPath((0,0),text,size=size,prop={'family':'DejaVu Sans','weight':'bold'}).to_polygons()
    points=[];counts=[];indices=[]
    for polygon in polygons:
        if len(polygon)<3:continue
        start=len(points)
        points.extend([(float(x),0,float(y)) for x,y in polygon]);counts.append(len(polygon));indices.extend(range(start,len(points)))
    mesh=UsdGeom.Mesh.Define(stage,path);mesh.CreatePointsAttr(points);mesh.CreateFaceVertexCountsAttr(counts);mesh.CreateFaceVertexIndicesAttr(indices);mesh.CreateSubdivisionSchemeAttr('none');mesh.CreateDoubleSidedAttr(True);mesh.CreateDisplayColorAttr([Gf.Vec3f(*color)]);mesh.AddTranslateOp().Set(Gf.Vec3d(*pos))
    if heading:mesh.AddRotateZOp().Set(heading)
    return mesh

def create_set(stage,root):
    UsdGeom.Xform.Define(stage,'/World');stage.SetDefaultPrim(stage.GetPrimAtPath('/World'));UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z');stage.SetTimeCodesPerSecond(30)
    box(stage,'/World/Sea',(43,0,-.8),(2400,2400,1.2),(.025,.07,.085),.3,.22)
    # Broken triangulated rock face replaces the layout's rectangular blocks.
    import numpy as np
    rng=np.random.default_rng(3102);points=[];nx,nz=76,13
    for i in range(nx):
        x=-24+i*2.1;top=max(4,x*.577+8+2*math.sin(x*.2))
        for j in range(nz):
            f=j/(nz-1);points.append((x+float(rng.normal(0,.65)),15+1.7*math.sin(x*.38+j*.9)+float(rng.normal(0,.7)), -6+f*(top+6)))
    faces=[]
    for i in range(nx-1):
        for j in range(nz-1):
            a=i*nz+j;faces.extend([a,a+1,a+nz+1,a,a+nz+1,a+nz])
    rockface=UsdGeom.Mesh.Define(stage,'/World/Cliff/RockFace');rockface.CreatePointsAttr(points);rockface.CreateFaceVertexCountsAttr([3]*(len(faces)//3));rockface.CreateFaceVertexIndicesAttr(faces);rockface.CreateDoubleSidedAttr(True);rockface.CreateSubdivisionSchemeAttr('none');rockface.CreateDisplayColorAttr([Gf.Vec3f(.10,.15,.16)])
    cliff=root/'.runtime/deadweight/Deadweight_Feasibility_Assets/coast/coastal_cliff_02_1k.usdc'
    if cliff.exists():
        rock=UsdGeom.Xform.Define(stage,'/World/HeroCliff');rock.GetPrim().GetReferences().AddReference(str(cliff));rock.AddTranslateOp().Set(Gf.Vec3d(51,15,15));rock.AddScaleOp().Set(Gf.Vec3d(.9))
    steel=(.055,.10,.13);concrete=(.16,.20,.22);mark=(.95,.60,.12)
    for i in range(10):
        x=RUN*i/9;z=3+x/math.sqrt(3)
        for j,y in enumerate([-2.4,2.4]):box(stage,f'/World/Viaduct/Pier{i}_{j}',(x,y,z/2-1),(1.0,.85,z-1),concrete)
        box(stage,f'/World/Viaduct/Cap{i}',(x,0,z-.8),(1.2,8.3,.5),steel,.65)
    for tag,y in [('A',-2.4),('B',2.4)]:
        bed=box(stage,f'/World/Track/{tag}Bed',(RUN/2,y,30.2),(120,2.1,.38),steel,.65);bed.AddRotateYOp().Set(-30)
        for j,dy in enumerate([-.85,.85]):
            b=box(stage,f'/World/Track/{tag}Rail{j}',(RUN/2,y+dy,31),(120,.12,.16),(.33,.38,.4),.85,.2);b.AddRotateYOp().Set(-30)
        for k in range(75):
            x=(k/74*112-3)*math.cos(math.pi/6);z=3+x/math.sqrt(3)
            b=box(stage,f'/World/Track/{tag}Sleeper{k}',(x,y,z-.2),(.22,2.1,.18),(.13,.12,.1));b.AddRotateYOp().Set(-30)
    for name,x,z,y in [('Upper',RUN,59,-8.75),('Lower',0,3,8.75)]:
        f=z+FLOOR
        box(stage,f'/World/{name}/Platform',(x,y,f-.23),(19,9,.46),(.23,.28,.30))
        box(stage,f'/World/{name}/Canopy',(x,y+1,f+4.5),(19,8,.22),steel,.65)
        box(stage,f'/World/{name}/Edge',(x,y+(4 if y<0 else -4),f+.012),(18,.14,.024),mark)
        for j,dx in enumerate([-8,-4,0,4,8]):
            if j in (0,4):box(stage,f'/World/{name}/Column{j}',(x+dx,y,f+2.2),(.16,.16,4.4),steel,.65)
            for k in range(8):box(stage,f'/World/{name}/Seam{j}_{k}',(x+dx,y-3.6+k*.9,f+.005),(.018,.018+8/8,.008),(.10,.14,.16))
        label(stage,f'/World/{name}/Sign',('SUMMIT / 02' if name=='Upper' else 'TIDELINE / 01'),(x-5,y+2,f+3.7),.47)
    # Isolated refuge aligns with booth door only at the low stop.
    box(stage,'/World/Refuge/Deck',(-5.1,-6.0,5.40),(3.0,4.7,.46),steel,.8)
    for side,x in [('L',-6.55),('R',-3.65)]:
        box(stage,f'/World/Refuge/{side}Rail',(x,-6,6.4),(.08,4.6,.08),mark,.65)
        for i in range(4):box(stage,f'/World/Refuge/{side}Post{i}',(x,-4.2-i*1.15,5.98),(.06,.06,1.1),steel,.6)
    # Upper maintenance escape is a separate choice, never a lower escape route.
    box(stage,'/World/Upper/MaintenanceDoor',(RUN-8,-11,63),(2.0,.2,2.8),(.08,.36,.30),.3)
    label(stage,'/World/Upper/ExitSign','REFUGE',(RUN-8.8,-11.12,64.8),.27,(.2,1,.55))
    tank=UsdGeom.Cylinder.Define(stage,'/World/Upper/EmptyTank');tank.CreateAxisAttr('Z');tank.CreateRadiusAttr(.6);tank.CreateHeightAttr(2.2);tank.AddTranslateOp().Set(Gf.Vec3d(RUN+7.5,-10,62.9));tank.CreateDisplayColorAttr([Gf.Vec3f(.24,.32,.35)])
    box(stage,'/World/Upper/BrokenSupply',(RUN+6.6,-10,63.7),(1.6,.14,.14),(.34,.18,.10),.8)
    box(stage,'/World/Upper/BrokenEnd',(RUN+5.6,-10,63.4),(.14,.14,.5),(.34,.18,.10),.8).AddRotateYOp().Set(24)
    label(stage,'/World/Upper/TankLabel','SUPPLY / 0%',(RUN+6.7,-10.65,63.0),.17,(1,.38,.15))
    box(stage,'/World/Drain/Rim',(-6,7,5.65),(1.1,.75,.035),(.035,.06,.07),.7)
    for i in range(8):box(stage,f'/World/Drain/Grid{i}',(-6.4+i*.115,7,5.675),(.035,.7,.025),(.25,.30,.31),.8)
    # A distant working lighthouse anchors the seacoast silhouette.
    tower=UsdGeom.Cylinder.Define(stage,'/World/Lighthouse/Tower');tower.CreateAxisAttr('Z');tower.CreateRadiusAttr(1.1);tower.CreateHeightAttr(11);tower.AddTranslateOp().Set(Gf.Vec3d(114,20,69));tower.CreateDisplayColorAttr([Gf.Vec3f(.55,.58,.52)])
    roof=UsdGeom.Cone.Define(stage,'/World/Lighthouse/Roof');roof.CreateAxisAttr('Z');roof.CreateRadiusAttr(1.6);roof.CreateHeightAttr(1.8);roof.AddTranslateOp().Set(Gf.Vec3d(114,20,76.6));roof.CreateDisplayColorAttr([Gf.Vec3f(.12,.16,.18)])
    lamp=UsdLux.SphereLight.Define(stage,'/World/Lighthouse/Lamp');lamp.CreateIntensityAttr(15000);lamp.CreateRadiusAttr(.45);lamp.CreateColorAttr(Gf.Vec3f(1,.68,.24));lamp.AddTranslateOp().Set(Gf.Vec3d(114,20,75.2))
    dome=UsdLux.DomeLight.Define(stage,'/World/Light/Sky');dome.CreateIntensityAttr(650);dome.CreateColorAttr(Gf.Vec3f(.48,.62,.75))
    sky=Path('/data/omniverse/Assets/Isaac/5.1/NVIDIA/Assets/Skies/2022_1/Skies/Storm/approaching_storm.hdr')
    if sky.exists():dome.CreateTextureFileAttr(Sdf.AssetPath(str(sky)));dome.CreateTextureFormatAttr('latlong')
    sun=UsdLux.DistantLight.Define(stage,'/World/Light/Moon');sun.CreateIntensityAttr(2200);sun.CreateAngleAttr(8);sun.CreateColorAttr(Gf.Vec3f(.65,.80,1));sun.AddRotateXYZOp().Set(Gf.Vec3f(28,-32,-45))
    for name,x,z,y in [('Upper',RUN,64,-15),('Lower',0,8,15)]:
        fill=UsdLux.RectLight.Define(stage,f'/World/Light/{name}Softbox');fill.CreateIntensityAttr(1700);fill.CreateWidthAttr(17);fill.CreateHeightAttr(5);fill.CreateColorAttr(Gf.Vec3f(.65,.82,1))
        fill.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(x,y,z),Gf.Vec3d(x,-7 if y<0 else 7,z-1),Gf.Vec3d(0,0,1)).GetInverse())
    photo_fill=UsdLux.RectLight.Define(stage,'/World/Light/PhotoFill');photo_fill.CreateIntensityAttr(1400);photo_fill.CreateWidthAttr(4);photo_fill.CreateHeightAttr(4);photo_fill.CreateColorAttr(Gf.Vec3f(1,.82,.62));photo_fill.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(RUN/2-8,0,38),Gf.Vec3d(RUN/2-5,0,35),Gf.Vec3d(0,0,1)).GetInverse())
    camera=UsdGeom.Camera.Define(stage,'/World/Camera');camera.AddTransformOp();camera.CreateHorizontalApertureAttr(36);camera.CreateVerticalApertureAttr(20.25);camera.CreateFocalLengthAttr(35);camera.CreateClippingRangeAttr(Gf.Vec2f(.06,1000))
    return {'A':create_car(stage,'A',(.08,.28,.35)),'B':create_car(stage,'B',(.75,.36,.075))}

def create_car(stage,name,color):
    root='/World/Cars/'+name;xf=UsdGeom.Xform.Define(stage,root).AddTranslateOp()
    box(stage,root+'/Floor',(0,0,FLOOR-.11),(12.4,WIDTH,.22),(.19,.23,.25),.25)
    box(stage,root+'/Chassis',(0,0,.53),(5.9,2.2,.34),(.05,.08,.1),.8).AddRotateYOp().Set(-30)
    box(stage,root+'/Roof',(0,0,FLOOR+2.5),(12.6,WIDTH+.12,.14),color,.65,.26)
    for j,x in enumerate([-2.8,2.8]):
        for k,y in enumerate([-.85,.85]):
            c=UsdGeom.Cylinder.Define(stage,root+f'/Wheel{j}_{k}');c.CreateAxisAttr('Y');c.CreateRadiusAttr(.34);c.CreateHeightAttr(.2);c.AddTranslateOp().Set(Gf.Vec3d(x,y,x*.577+.41));c.CreateDisplayColorAttr([Gf.Vec3f(.035)])
    doors={};boarding_side=-1 if name=='A' else 1
    for side in [-1,1]:
        side_name='South' if side<0 else 'North'
        y=side*WIDTH/2
        # Two 1.65m passenger doors and one private booth exit on the platform side.
        gaps=[(-5.95,-4.35),(-3.05,-1.35),(2.45,4.15)] if side==boarding_side else []
        boundaries=sorted(set([-6.15,6.15]+[v for g in gaps for v in g]))
        for j,(a,b) in enumerate(zip(boundaries,boundaries[1:])):
            if any(abs(a-l)<.01 and abs(b-r)<.01 for l,r in gaps):continue
            box(stage,root+f'/Side{side_name}/Sill{j}',((a+b)/2,y,FLOOR+.32),(b-a,.08,.64),color,.65)
            box(stage,root+f'/Side{side_name}/Top{j}',((a+b)/2,y,FLOOR+2.35),(b-a,.08,.15),color,.7)
            # Thin stylized glass with low opacity, allows faces to be read.
            glass=box(stage,root+f'/Side{side_name}/Glass{j}',((a+b)/2,y,FLOOR+1.48),(b-a-.04,.012,1.65),(.14,.30,.34),.1,.14)
            glass.GetPrim().GetChild('Material').GetChild('Surface').GetAttribute('inputs:opacity').Set(.07) if glass.GetPrim().GetChild('Material').GetChild('Surface').HasAttribute('inputs:opacity') else UsdShade.Shader(glass.GetPrim().GetChild('Material').GetChild('Surface')).CreateInput('opacity',Sdf.ValueTypeNames.Float).Set(.07)
        for j,x in enumerate([-6.15,-4.1,-3.05,-1.35,.55,2.45,4.15,6.15]):box(stage,root+f'/Side{side_name}/Post{j}',(x,y,FLOOR+1.25),(.055,.07,2.5),color,.75)
        if side==boarding_side:
            for j,(a,b) in enumerate(gaps):
                dp=root+f'/Doors/D{j}';op=UsdGeom.Xform.Define(stage,dp).AddTranslateOp();doors[j]=op
                box(stage,dp+'/Bottom',((a+b)/2,y,FLOOR+.26),(b-a,.06,.5),color,.7)
                for x in [a,b]:box(stage,dp+('/Left' if x==a else '/Right'),(x,y,FLOOR+1.25),(.055,.06,2.5),color,.7)
                box(stage,dp+'/Top',((a+b)/2,y,FLOOR+2.4),(b-a,.06,.12),color,.7)
                glass=box(stage,dp+'/Glass',((a+b)/2,y,FLOOR+1.45),(b-a-.07,.015,1.85),(.10,.24,.27),.1,.15)
                UsdShade.Shader(glass.GetPrim().GetChild('Material').GetChild('Surface')).CreateInput('opacity',Sdf.ValueTypeNames.Float).Set(.08)
                box(stage,dp+'/SafetyStripe',((a+b)/2,y,FLOOR+1.08),(b-a,.024,.04),(.8,.62,.22),.3)
    for j,x in enumerate([-6.15,6.15]):box(stage,root+f'/End{j}',(x,0,FLOOR+.35),(.09,WIDTH,.70),color,.7)
    # True internal passage: solid partition spans y=-.05..1.85; opening -1.8..-.2.
    box(stage,root+'/Partition/Upper',(-4.1,.88,FLOOR+1.22),(.045,1.9,2.44),(.06,.20,.24),.1,.22)
    inner=UsdGeom.Xform.Define(stage,root+'/Partition/Door').AddTranslateOp()
    box(stage,root+'/Partition/Door/Edge',(-4.1,-1.0,FLOOR+1.24),(.05,1.6,2.44),(.13,.29,.32),.3,.22)
    doors['inner']=inner
    label(stage,root+'/Number',('DEADWEIGHT / A' if name=='A' else 'SAFE HAVEN / B'),(-.8,-WIDTH/2-.045,FLOOR+.19),.20,(1,.8,.33))
    light=UsdLux.RectLight.Define(stage,root+'/CabinLight');light.CreateIntensityAttr(800);light.CreateWidthAttr(9);light.CreateHeightAttr(2);light.CreateColorAttr(Gf.Vec3f(*((.30,.65,.85) if name=='A' else (1,.57,.22))));light.AddTranslateOp().Set(Gf.Vec3d(0,0,FLOOR+2.35))
    return {'root':root,'xform':xf,'doors':doors}
