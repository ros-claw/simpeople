import math
"""Additional source-authored scenes for rig validation and population trials."""
from pxr import Gf, Sdf, UsdGeom
from .scene import build_scene,mesh_box
import omni.usd
from simpeople.core.seats import SeatProfile

def anchor(stage,semantics,name,position,kind='location'):
    path='/World/Locations/'+name
    UsdGeom.Xform.Define(stage,path).AddTranslateOp().Set(Gf.Vec3d(*position))
    semantics[name]={'prim_path':path,'kind':kind,'position_m':position,'capacity':1}

def chair(stage,semantics,name,position):
    path='/World/Seats/'+name
    parent=UsdGeom.Xform.Define(stage,path);parent.AddTranslateOp().Set(Gf.Vec3d(*position))
    mesh_box(stage,path+'/Seat',(0,0,.43),(.6,.6,.1),(.13,.43,.48))
    back=mesh_box(stage,path+'/Back',(0,.25+.325*math.sin(math.radians(15)),.455+.325*math.cos(math.radians(15))),(.6,.1,.65),(.13,.43,.48))
    UsdGeom.Xformable(back).AddRotateXOp().Set(-15.)
    for i,(x,y) in enumerate([(-.23,-.23),(.23,-.23),(-.23,.23),(.23,.23)]):
        mesh_box(stage,path+f'/Leg{i}',(x,y,.2),(.045,.045,.4),(.08,.1,.12))
    parent.GetPrim().AddAppliedSchema('BehaviorPropAPI')
    effect=stage.DefinePrim(path+'/Behavior/Sit','BehaviorTaskEffectors')
    effect.AddAppliedSchema('BehaviorTaskEffectorAPI')
    effect.CreateAttribute('behavior:task',Sdf.ValueTypeNames.Token).Set('Sit')
    hips=UsdGeom.Xform.Define(stage,path+'/Behavior/Hips')
    hips.AddTranslateOp().Set(Gf.Vec3d(0,-.08,.56));hips.AddRotateXYZOp().Set(Gf.Vec3f(90,0,0))
    effect.CreateRelationship('behavior:task:effectorHips').SetTargets([hips.GetPath()])
    parent.GetPrim().CreateRelationship('behavior:task:effectors').SetTargets([effect.GetPath()])
    approach=name+'_approach';egress=name+'_egress';alt=name+'_egress_alt'
    anchor(stage,semantics,approach,[position[0],position[1]-1.2,0])
    anchor(stage,semantics,egress,[position[0]+1.3,position[1]-1.3,0])
    anchor(stage,semantics,alt,[position[0]-1.3,position[1]-1.3,0])
    semantics[name]={'kind':'seat','prim_path':path,'hips_prim_path':str(hips.GetPath()),
        'hips_tolerance_m':.18,'facing_direction':[0,-1,0],'approach':approach,
        'egress':egress,'egress_targets':[egress,alt],'capacity':1,'allowed_actions':['sit']}
    semantics[name]['seat_profile']=SeatProfile('generated-chair-v3',tuple(position),hips_offset_m=(0,-.08,.56),back_center_local_m=(0,.25+.325*math.sin(math.radians(15)),.455+.325*math.cos(math.radians(15))),back_tilt_rad=math.radians(15),revision='seat-v3').as_dict()

def industrial_scene():
    sem=build_scene(True);stage=omni.usd.get_context().get_stage()
    UsdGeom.Xformable(stage.GetPrimAtPath('/World/MovableBox')).GetOrderedXformOps()[0].Set(Gf.Vec3d(-4,10,.65))
    for i in range(8):
        x=[-14,-7,7,14][i%4];y=7+(i//4)*7
        mesh_box(stage,f'/World/Workstations/Desk_{i}',(x,y,.55),(2.4,1.2,1.1),(.16,.32,.38))
        anchor(stage,sem,f'work_{i:02d}',[x,y-1.3,0])
    for i in range(6):chair(stage,sem,f'seat_{i:02d}',[7.5+(i%3)*3.75,-8.75-(i//3)*5,0])
    for i in range(3):
        x=-15+i*6.25
        mesh_box(stage,f'/World/Counters/Counter_{i}',(x,-13,.6),(2.4,1.2,1.2),(.44,.32,.20))
        slots=[[x,-15-j*1.25,0] for j in range(4)]
        anchor(stage,sem,f'counter_approach_{i}',[x,-15,0])
        sem[f'queue_{i}']={'kind':'queue','prim_path':f'/World/Locations/counter_approach_{i}',
                           'slots_m':slots,'egress_targets':[[x+2.5,-15,0],[x-2.5,-15,0]],'capacity':len(slots)}
        anchor(stage,sem,f'event_station_{i}',[-13+i*12,3,0])
    for name,pos in {'patrol_west':[-18,2,0],'patrol_north':[0,18,0],'patrol_east':[18,2,0],
                     'run_west':[-17,-5,0],'run_east':[17,-5,0],
                     'door_west':[-2,-10,0],'door_east':[2,-10,0]}.items():anchor(stage,sem,name,pos)
    mesh_box(stage,'/World/NarrowDoor/North',(0,-7.8,1),(.3,2.8,2),(.46,.53,.58))
    mesh_box(stage,'/World/NarrowDoor/South',(0,-12.2,1),(.3,2.8,2),(.46,.53,.58))
    sem['narrow_door']={'kind':'passage','capacity':1,'prim_path':'/World/NarrowDoor',
                        'approaches':['door_west','door_east']}
    # Flush floor markings identify two wide corridors without changing navigation geometry.
    mesh_box(stage,'/World/Markings/EW',(0,-5,.003),(40,.08,.005),(.82,.66,.12))
    mesh_box(stage,'/World/Markings/NS',(-3,0,.003),(.08,40,.005),(.82,.66,.12))
    return sem

def gait_quality_scene():
    """Same lighting/ground, independent lanes for comparing twelve rigs."""
    sem=build_scene(True);stage=omni.usd.get_context().get_stage()
    for path in ['/World/WallA','/World/WallB','/World/DoorPost','/World/Workbench','/World/MovableBox','/World/Chair']:
        stage.RemovePrim(path)
    return {k:v for k,v in sem.items() if v.get('kind')=='location'}

def asset_validation_scene(count,portrait=False):
    sem=build_scene(True);stage=omni.usd.get_context().get_stage();slots=[]
    if portrait:
        for path in ['/World/WallA','/World/WallB','/World/DoorPost','/World/Workbench','/World/MovableBox','/World/Chair']:
            stage.RemovePrim(path)
        sem={k:v for k,v in sem.items() if v.get('kind')=='location'}
    for i in range(count):
        x=([-15,-7,7,15] if count<=12 else [-15,-5,5,15])[i%4]
        y=(-12+(i//4)*12) if count<=12 else (-15+(i//4)*6)
        name=f'asset_seat_{i:02d}'
        if not portrait:chair(stage,sem,name,[x,y,0])
        slots.append({'spawn':[x-2.5,y-2.5,0],'walk':[x+2.5,y-2.5,0],
                      'run':[x+2.5,y+2.5,0],'seat':name})
    return sem,slots
