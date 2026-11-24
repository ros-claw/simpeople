"""Production metro from the kit's measured boxes; meshes also serve NavMesh."""
import json,math
from pathlib import Path
import numpy as np
from pxr import UsdGeom,UsdShade,UsdLux,UsdPhysics,Sdf,Gf,Vt
from .deadweight_set import box,label

def linear(rgb):
    a=np.asarray(rgb)/255.;return np.where(a<=.04045,a/12.92,((a+.055)/1.055)**2.4)

def create_metro(stage,root,*,collision=False):
    root=Path(root);kit=root/'.runtime/platform04/kit';data=json.loads((kit/'station/station_boxes.json').read_text());UsdGeom.Xform.Define(stage,'/World');stage.SetDefaultPrim(stage.GetPrimAtPath('/World'));UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z');stage.SetTimeCodesPerSecond(30);stage.SetFramesPerSecond(30)
    looks={};glass=[];colliders=[]
    def material(col,kind,group):
        key=(tuple(col),kind,group if group in ['Car','Platform'] else 'other')
        if key in looks:return looks[key]
        path=f'/World/Metro/Looks/M{len(looks)}';mat=UsdShade.Material.Define(stage,path);sh=UsdShade.Shader.Define(stage,path+'/Surface');sh.CreateIdAttr('UsdPreviewSurface');sh.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*linear(col)));sh.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(.28 if group=='Car' else .54);sh.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(.62 if group=='Car' and kind!='glass' else .05)
        if kind=='light':sh.CreateInput('emissiveColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*(linear(col)*2)))
        if kind=='glass':
            sh.GetInput('roughness').Set(.12);sh.GetInput('metallic').Set(0);sh.CreateInput('opacity',Sdf.ValueTypeNames.Float).Set(.055);sh.CreateInput('ior',Sdf.ValueTypeNames.Float).Set(1.45)
        mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(),'surface');looks[key]=mat;return mat
    for b in data['boxes']:
        if b['group']=='Columns' and b['center'][0] in [10.5,18.]:b['center'][1]=7.1
        path='/World/Metro/'+b['group']+'/'+b['name'];mesh=UsdGeom.Mesh.Define(stage,path);x,y,z=np.asarray(b['size'])/2
        mesh.CreatePointsAttr([(-x,-y,-z),(x,-y,-z),(x,y,-z),(-x,y,-z),(-x,-y,z),(x,-y,z),(x,y,z),(-x,y,z)]);mesh.CreateFaceVertexCountsAttr([4]*6);mesh.CreateFaceVertexIndicesAttr([0,3,2,1,4,5,6,7,0,1,5,4,1,2,6,5,2,3,7,6,3,0,4,7]);mesh.CreateSubdivisionSchemeAttr('none');mesh.AddTranslateOp().Set(Gf.Vec3d(*b['center']))
        if b.get('rot_z'):mesh.AddRotateZOp().Set(b['rot_z'])
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(material(b['color'],b['kind'],b['group']))
        if b['kind']=='glass':glass.append(mesh.GetPrim())
        if collision and b['kind']!='light':UsdPhysics.CollisionAPI.Apply(mesh.GetPrim());colliders.append(path)
    # Visible low-contrast tile joints provide a real foot-speed reference.
    for i,x in enumerate(np.arange(-7.5,42,.75)):box(stage,f'/World/Metro/Detail/GroutX{i}',(x,4.5,.001),(.012,8.35,.002),(.15,.19,.18),0,.85)
    for i,y in enumerate(np.arange(.35,8.7,.75)):box(stage,f'/World/Metro/Detail/GroutY{i}',(17,y,.001),(50,.012,.002),(.15,.19,.18),0,.85)
    # Uneven small wet patches; no blanket fog or strobe hides the performance.
    rng=np.random.default_rng(4011)
    for i,(x,y) in enumerate([(1,3),(8,1.0),(16,2.7),(22,4.8),(30,2.4)]):
        a=np.arange(22)*2*np.pi/22;r=rng.uniform(.45,.9,22);pts=np.column_stack([x+np.cos(a)*r*1.5,y+np.sin(a)*r*.55,np.full(22,.006)]);m=UsdGeom.Mesh.Define(stage,f'/World/Metro/Detail/Puddle{i}');m.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(pts.astype(np.float32)));m.CreateFaceVertexCountsAttr([22]);m.CreateFaceVertexIndicesAttr(list(range(22)));m.CreateSubdivisionSchemeAttr('none');mat=material((86,100,98),'wet','Platform');sh=UsdShade.Shader(stage.GetPrimAtPath(str(mat.GetPath())+'/Surface'));sh.GetInput('roughness').Set(.42);UsdShade.MaterialBindingAPI.Apply(m.GetPrim()).Bind(mat)
    for i,x in enumerate([-2,6,14,22,30,38]):
        for j,y in enumerate([-1.6,2.1,6.7]):
            l=UsdLux.RectLight.Define(stage,f'/World/Metro/Lights/Bay{i}_{j}');l.CreateWidthAttr(2.6);l.CreateHeightAttr(.35);l.CreateIntensityAttr(5280 if j else 4640);l.CreateColorAttr(Gf.Vec3f(*((.68,.83,.88) if j else (1,.78,.57))));l.AddTranslateOp().Set(Gf.Vec3d(x,y,4.03 if j else 2.47))
        # Motivated soft face fill from the opposite platform's light boxes.
        l=UsdLux.RectLight.Define(stage,f'/World/Metro/Lights/WindowFace{i}');l.CreateWidthAttr(3.5);l.CreateHeightAttr(.9);l.CreateIntensityAttr(2720);l.CreateColorAttr(Gf.Vec3f(.78,.87,.93));l.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(x,4.8,2.25),Gf.Vec3d(x,-1.4,1.3),Gf.Vec3d(0,0,1)).GetInverse())
        l=UsdLux.RectLight.Define(stage,f'/World/Metro/Lights/CarEyeline{i}');l.CreateWidthAttr(3.0);l.CreateHeightAttr(.28);l.CreateIntensityAttr(3500);l.CreateColorAttr(Gf.Vec3f(1,.79,.63));l.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(x,-.55,2.12),Gf.Vec3d(x,-1.35,1.35),Gf.Vec3d(0,0,1)).GetInverse())
    dome=UsdLux.DomeLight.Define(stage,'/World/Metro/Lights/Ambient');dome.CreateIntensityAttr(20);dome.CreateColorAttr(Gf.Vec3f(.48,.62,.70))
    label(stage,'/World/Metro/ProductionSign','PLATFORM 04 / LAST SERVICE',(19,8.53,2.8),.25,(.86,.89,.79));label(stage,'/World/Metro/TrainSign','04 / NOT IN SERVICE',(21,-.16,.47),.16,(.83,.87,.72),180)
    # Bench and advertisement give the low attacker a physical hiding place.
    box(stage,'/World/Metro/LowBench/Seat',(29.6,6.55,.47),(2.1,.6,.10),(.32,.29,.23),.15)
    box(stage,'/World/Metro/LowBench/Back',(29.6,6.82,.85),(2.1,.10,.72),(.25,.28,.26),.2)
    for i,x in enumerate([28.8,30.4]):box(stage,f'/World/Metro/LowBench/Leg{i}',(x,6.55,.22),(.10,.4,.44),(.08,.11,.12),.7)
    gate=UsdGeom.Xform.Define(stage,'/World/Metro/StationGate');gate_op=gate.AddTranslateOp()
    for i in range(29):box(stage,f'/World/Metro/StationGate/Bar{i}',(25.1+i*.207,9.65,1.35),(.028,.06,2.7),(.20,.26,.25),.8)
    for i,z in enumerate([.08,1.35,2.7]):box(stage,f'/World/Metro/StationGate/Rail{i}',(28,9.65,z),(6,.065,.045),(.25,.30,.28),.8)
    gate_op.Set(Gf.Vec3d(-6.35,0,0))
    camera=UsdGeom.Camera.Define(stage,'/World/Camera');camera.AddTransformOp();camera.CreateHorizontalApertureAttr(36);camera.CreateVerticalApertureAttr(20.25);camera.CreateClippingRangeAttr(Gf.Vec2f(.06,180));camera.CreateFocalLengthAttr(28)
    return {'glass':glass,'gate_op':gate_op,'boxes':data['boxes'],'collision_meshes':colliders}

def aim(stage,eye,target,fov=67):
    camera=stage.GetPrimAtPath('/World/Camera');UsdGeom.Xformable(camera).GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float,eye)),Gf.Vec3d(*map(float,target)),Gf.Vec3d(0,0,1)).GetInverse());camera.GetAttribute('focalLength').Set(36/(2*math.tan(math.radians(fov)/2)))

def technical_view(stage,scene):
    """After baking only: hide roof leaves, retaining every collider and NavMesh.

    Source box-group ancestors are untyped USD prims. Hiding their parent alone
    did not hide their render leaves in this RC; author leaf visibility instead.
    """
    hidden=[]
    for b in scene['boxes']:
        if b['group']=='Canopy' or 'roof' in b['name'].lower():
            path='/World/Metro/'+b['group']+'/'+b['name'];UsdGeom.Imageable(stage.GetPrimAtPath(path)).MakeInvisible();hidden.append(path)
    light=UsdLux.DistantLight.Define(stage,'/World/Metro/Lights/TechnicalOnly');light.CreateIntensityAttr(1800);light.AddRotateXYZOp().Set(Gf.Vec3f(20,-25,0))
    aim(stage,[25,12,12],[25,4.4,.6],75)
    return {'hidden_render_leaves':hidden,'colliders_removed':0,'scope':'technical overhead only; movie lighting and camera unchanged'}
