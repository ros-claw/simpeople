import math
"""Small industrial validation scene, authored in metres, Z up."""
import omni.kit.commands
import omni.usd
from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdPhysics
from simpeople.core.seats import SeatProfile

def mesh_box(stage,path,position,size,color):
    x,y,z=[v/2 for v in size]
    p=UsdGeom.Mesh.Define(stage,path)
    p.CreatePointsAttr([(-x,-y,-z),(x,-y,-z),(x,y,-z),(-x,y,-z),
                        (-x,-y,z),(x,-y,z),(x,y,z),(-x,y,z)])
    p.CreateFaceVertexCountsAttr([4]*6)
    p.CreateFaceVertexIndicesAttr([0,3,2,1,4,5,6,7,0,1,5,4,1,2,6,5,2,3,7,6,3,0,4,7])
    p.CreateSubdivisionSchemeAttr('none');p.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    p.AddTranslateOp().Set(Gf.Vec3d(*position))
    UsdPhysics.CollisionAPI.Apply(p.GetPrim())
    return p.GetPrim()

def build_scene(industrial=False):
    stage=omni.usd.get_context().get_stage()
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage,'/World').GetPrim())
    UsdGeom.SetStageMetersPerUnit(stage,1.0);UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
    stage.SetTimeCodesPerSecond(30)
    stage.GetRootLayer().customLayerData={'navmeshSettings':{
        'agentMaxFloorSlope':30.0,'agentMaxRadius':0.65,'agentMinRadius':0.2,
        'agentMinHeight':1.6,'agentMaxStepHeight':0.2,'agentMinIslandRadius':0.2,
        'agentSamplingDistance':0.15,'excludeRigidBodies':True}}
    half=22 if industrial else 10
    mesh_box(stage,'/World/Ground',(0,0,-.15),(half*2,half*2,.3),(.21,.25,.29))
    # L wall, with an opening wide enough for a human.
    mesh_box(stage,'/World/WallA',(0,2.8,1),(.3,3.6,2),(.46,.53,.58))
    mesh_box(stage,'/World/WallB',(2,4.5,1),(4,.3,2),(.46,.53,.58))
    mesh_box(stage,'/World/DoorPost',(0,-3.8,1),(.3,2.4,2),(.46,.53,.58))
    obstacle=mesh_box(stage,'/World/MovableBox',(2.8,-1.2,.65),(1,1,1.3),(.56,.32,.12))
    rigid=UsdPhysics.RigidBodyAPI.Apply(obstacle)
    rigid.CreateKinematicEnabledAttr(True);rigid.CreateRigidBodyEnabledAttr(True)
    mesh_box(stage,'/World/Workbench',(5.8,3,.55),(1.2,2,1.1),(.16,.32,.38))
    # Seat parent is unscaled. Hip effector is in metres and faces -Y.
    seat='/World/Chair'
    UsdGeom.Xform.Define(stage,seat).AddTranslateOp().Set(Gf.Vec3d(4,-3,0))
    mesh_box(stage,seat+'/Cushion',(0,0,.43),(.6,.6,.10),(.12,.46,.50))
    back=mesh_box(stage,seat+'/Back',(0,.25+.325*math.sin(math.radians(15)),.455+.325*math.cos(math.radians(15))),(.6,.1,.65),(.12,.46,.50))
    UsdGeom.Xformable(back).AddRotateXOp().Set(-15.)
    for i,(x,y) in enumerate([(-.23,-.23),(.23,-.23),(-.23,.23),(.23,.23)]):
        mesh_box(stage,seat+f'/Leg{i}',(x,y,.2),(.045,.045,.4),(.1,.12,.13))
    seat_prim=stage.GetPrimAtPath(seat)
    seat_prim.AddAppliedSchema('BehaviorPropAPI')
    effect=stage.DefinePrim(seat+'/Behavior/Sit','BehaviorTaskEffectors')
    effect.AddAppliedSchema('BehaviorTaskEffectorAPI')
    effect.CreateAttribute('behavior:task',Sdf.ValueTypeNames.Token).Set('Sit')
    hip=UsdGeom.Xform.Define(stage,seat+'/Behavior/Hips')
    hip.AddTranslateOp().Set(Gf.Vec3d(0,-.08,.56))
    # Effector orientation describes the Y-up Human rig in the Z-up stage.
    # Local +Z is the rig's forward direction: +90 X makes it face -Y.
    hip.AddRotateXYZOp().Set(Gf.Vec3f(90,0,0))
    effect.CreateRelationship('behavior:task:effectorHips').SetTargets([hip.GetPath()])
    seat_prim.CreateRelationship('behavior:task:effectors').SetTargets([effect.GetPath()])
    semantics={}
    for name,pos in {'entrance':[-5,-3,0],'workbench_a':[4.7,2.6,0],
                     'machine_a':[5.8,3,1.2],'chair_approach':[4,-4.1,0],
                     'chair_egress':[5.2,-4.2,0],
                     'chair_egress_alt':[2.6,-4.2,0],
                     'chair_egress_far':[5.5,-2.3,0],
                     'exit_a':[-5,3,0],'point_a':[-5,0,0], 'point_b':[5,0,0],
                     'point_c':[5,-5,0],'unreachable':[100,100,0]}.items():
        path='/World/Locations/'+name
        UsdGeom.Xform.Define(stage,path).AddTranslateOp().Set(Gf.Vec3d(*pos))
        semantics[name]={'prim_path':path,'kind':'location','position_m':pos,'capacity':1}
    semantics['chair_01']={'prim_path':seat,'kind':'seat','hips_prim_path':str(hip.GetPath()),
        'hips_tolerance_m':.18,'facing_direction':[0,-1,0],'approach':'chair_approach',
        'egress':'chair_egress','egress_targets':['chair_egress','chair_egress_alt','chair_egress_far'],
        'capacity':1,'allowed_actions':['sit']}
    semantics['chair_01']['seat_profile']=SeatProfile('generated-chair-v3',(4,-3,0),hips_offset_m=(0,-.08,.56),back_center_local_m=(0,.25+.325*math.sin(math.radians(15)),.455+.325*math.cos(math.radians(15))),back_tilt_rad=math.radians(15),revision='seat-v3').as_dict()
    semantics['movable_box']={'kind':'obstacle','prim_path':'/World/MovableBox','size_m':[1,1,1.3]}
    omni.kit.commands.execute('CreateNavMeshVolumeCommand',parent_prim_path=Sdf.Path('/World'),volume_type=0)
    volume=stage.GetPrimAtPath('/World/NavMeshVolume')
    UsdGeom.XformCommonAPI(volume).SetScale(Gf.Vec3f(half*2,half*2,5))
    # Lighting, shared across all performance runs.
    dome=UsdLux.DomeLight.Define(stage,'/World/Dome');dome.CreateIntensityAttr(700)
    sun=UsdLux.DistantLight.Define(stage,'/World/Sun');sun.CreateIntensityAttr(2200)
    sun.AddRotateXYZOp().Set(Gf.Vec3f(25,-30,-20))
    camera=UsdGeom.Camera.Define(stage,'/World/Camera')
    camera.CreateClippingRangeAttr(Gf.Vec2f(.1,200))
    camera.CreateFocalLengthAttr(26 if industrial else 28)
    if industrial:
        camera.CreateHorizontalApertureAttr(36);camera.CreateVerticalApertureAttr(20.25)
    eye=Gf.Vec3d(12,-16,13) if not industrial else Gf.Vec3d(38,-48,62)
    view=Gf.Matrix4d().SetLookAt(eye,Gf.Vec3d(0,0,0),Gf.Vec3d(0,0,1))
    camera.AddTransformOp().Set(view.GetInverse())
    return semantics
