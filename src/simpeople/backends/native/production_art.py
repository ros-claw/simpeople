"""Source-authored shift-change art over the existing industrial behavior scene."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from pxr import Gf, Sdf, Tf, UsdGeom, UsdLux, UsdPhysics, UsdShade
import omni.usd
from .scene import mesh_box
from .environments import industrial_scene, anchor


def shift_change_scene(directory):
    semantics = industrial_scene()
    stage = omni.usd.get_context().get_stage()
    directory = Path(directory) / 'production_art'
    directory.mkdir(exist_ok=True)
    materials = {}

    def material(name, color, metallic=0., rough=.7, texture=None, emission=0):
        if name in materials:
            return materials[name]
        path = '/World/Production/Materials/' + name
        mat = UsdShade.Material.Define(stage, path)
        shader = UsdShade.Shader.Define(stage, path + '/Surface')
        shader.CreateIdAttr('UsdPreviewSurface')
        shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(rough)
        shader.CreateInput('metallic', Sdf.ValueTypeNames.Float).Set(metallic)
        if emission:
            shader.CreateInput('emissiveColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*(c * emission for c in color)))
        if texture:
            reader = UsdShade.Shader.Define(stage, path + '/UV')
            reader.CreateIdAttr('UsdPrimvarReader_float2')
            reader.CreateInput('varname', Sdf.ValueTypeNames.Token).Set('st')
            tex = UsdShade.Shader.Define(stage, path + '/Texture')
            tex.CreateIdAttr('UsdUVTexture')
            tex.CreateInput('file', Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(texture)))
            tex.CreateInput('sourceColorSpace', Sdf.ValueTypeNames.Token).Set('sRGB')
            tex.CreateInput('st', Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), 'result')
            shader.GetInput('diffuseColor').ConnectToSource(tex.ConnectableAPI(), 'rgb')
        mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
        materials[name] = mat
        return mat

    floor = material('slate_floor', (.095, .12, .15), .05, .84)
    concrete = material('concrete', (.25, .29, .34), 0, .95)
    steel = material('steel', (.09, .13, .18), .65, .38)
    light_metal = material('light_metal', (.36, .44, .5), .5, .45)
    dark = material('rubber', (.025, .035, .045), 0, .9)
    blue = material('a_blue', (.025, .16, .32), .2, .52)
    amber = material('b_amber', (.72, .36, .055), .15, .5)
    line = material('floor_seam', (.065, .08, .10), 0, .95)
    window = material('high_window', (.41, .59, .72), .12, .32, emission=.2)
    warm = material('warm_light', (1, .75, .45), .0, .6, emission=2)

    def bind(prim, mat):
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(mat)

    def box(name, pos, size, mat, collision=False):
        name='/'.join(Tf.MakeValidIdentifier(part) for part in name.split('/'))
        prim = mesh_box(stage, '/World/Production/' + name, pos, size, (.5, .5, .5))
        if not collision:
            prim.RemoveAPI(UsdPhysics.CollisionAPI)
        bind(prim, mat)
        return prim

    bind(stage.GetPrimAtPath('/World/Ground'), floor)
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if prim.IsA(UsdGeom.Mesh) and any(s in path for s in ['/WallA', '/WallB', '/DoorPost', '/NarrowDoor']):
            bind(prim, concrete)
        if prim.IsA(UsdGeom.Mesh) and '/Workstations/Desk_' in path:
            bind(prim, light_metal)
    # Art stays above 2.6 m, outside the perimeter, or within existing equipment
    # footprints. Only new B consoles deliberately add ground obstacles.
    for i in range(12):
        v = -22 + i * 4
        box(f'Seams/X{i}', (v, 0, .0014), (.014, 44, .002), line)
        box(f'Seams/Y{i}', (0, v, .0014), (44, .014, .002), line)
    for side in [-1, 1]:
        x = side * 22.35
        box(f'Shell/Side{side}', (x, 0, 1.25), (.35, 45, 2.5), concrete, True)
        box(f'Shell/Top{side}', (x, 0, 9.8), (.35, 45, 2.4), concrete)
        for i in range(9):
            y = -20 + i * 5
            box(f'Shell/Pillar{side}_{i}', (side * 22.05, y, 5.5), (.55, .55, 11), steel, True)
            box(f'Shell/Window{side}_{i}', (x, y + 2.4, 6.2), (.09, 4.5, 5.5), window)
            for z in [3.7, 6.3, 8.8]:
                box(f'Shell/Mullion{side}_{i}_{z}', (side * 22.15, y + 2.4, z), (.18, 4.7, .09), steel)
        box(f'CableTray{side}', (side * 20.7, 0, 7.6), (.7, 43, .22), steel)
        box(f'WarmStrip{side}', (side * 21.1, 0, 7.5), (.07, 42, .05), warm)
    box('Shell/NorthWall', (0, 22.35, 4.5), (45, .35, 9), concrete, True)
    # Leave a generous central opening in the south wall for the opening move.
    for side in [-1, 1]:
        box(f'Shell/SouthBay{side}', (side * 16.5, -22.35, 4.5), (11.5, .35, 9), concrete, True)
    for i, x in enumerate([-20, -10, 0, 10, 20]):
        box(f'Roof/Beam{i}', (x, 0, 11), (.28, 44.4, .55), steel)
        for j, y in enumerate([-18, -6, 6, 18]):
            box(f'Roof/Cross{i}_{j}', (x + 4.7, y, 10.7), (9.4, .18, .22), light_metal)
    for i in range(8):
        x = [-14, -7, 7, 14][i % 4]
        y = 7 + (i // 4) * 7
        box(f'Equipment/Top{i}', (x, y, 1.15), (2.45, 1.25, .12), dark)
        box(f'Equipment/Control{i}', (x, y+.2, 1.55), (.85, .18, .65), steel)
        box(f'Equipment/Screen{i}', (x, y+.095, 1.57), (.64, .02, .38), blue)
        for j in range(5):
            box(f'Equipment/Vent{i}_{j}', (x-.8+j*.16, y-.61, .75), (.055, .01, .27), dark)
    for i in range(3):
        x = -15 + i*6.25
        box(f'Service/Top{i}', (x, -13, 1.24), (2.5, 1.3, .08), light_metal)
        box(f'Service/Terminal{i}', (x+.55, -13, 1.55), (.5, .35, .55), steel)
        box(f'Service/Screen{i}', (x+.55, -13.19, 1.6), (.38, .018, .3), blue)
        for j in range(4):
            box(f'Service/QueueMark{i}_{j}', (x, -15-j*1.25, .006), (.8, .06, .004), amber)
    for i in range(4):
        # Racks at the rear remain away from current work anchors and paths.
        x = -16+i*10
        for j, z in enumerate([.25, 2.8, 5.1]):
            box(f'Racks/Shelf{i}_{j}', (x, 20.5, z), (7.5, 1.9, .16), light_metal, j==0)
            for k in range(3):
                box(f'Racks/Crate{i}_{j}_{k}', (x-2.3+k*2.2, 20.5, z+.6), (1.6, 1.3, 1.05), concrete)
        for dx in [-3.6, 3.6]:
            box(f'Racks/Leg{i}_{dx}', (x+dx, 20.5, 2.7), (.13, 1.9, 5.5), amber, True)
    # B work anchors are distinct, reachable, and do not occupy the EW corridor.
    for n, x in [(1, 12.5), (2, 17.5)]:
        y=-2.5 if n==1 else -1.25
        box(f'B{n}/Machine', (x, y, .65), (2.2, 1.5, 1.3), light_metal, True)
        box(f'B{n}/Cap', (x, y, 1.34), (2.3, 1.6, .08), dark)
        box(f'B{n}/Display', (x, y, 1.8), (1.0, .25, .8), steel)
        box(f'B{n}/Screen', (x, y-.15, 1.85), (.8, .02, .5), blue)
        anchor(stage, semantics, f'B{n}', [x, y-2.5, 0])
        anchor(stage, semantics, f'B{n}_device', [x, y, 1.5])
    for n, x in [(1, 2.5), (2, 5)]:
        anchor(stage, semantics, f'A{n}', [x, -1.25, 0])
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 100)

    def sign(name, text, position, width, height, color):
        image = Image.new('RGB', (1024, 256), color)
        draw = ImageDraw.Draw(image)
        bounds = draw.textbbox((0, 0), text, font=font)
        draw.text(((1024-bounds[2])/2, (256-bounds[3])/2-6), text, font=font, fill=(240,244,247))
        path = directory / (name+'.png')
        image.save(path)
        mat = material('sign_'+name, (1,1,1), 0, .7, path)
        x,y,z = position
        prim = UsdGeom.Mesh.Define(stage, '/World/Production/Signs/'+name)
        prim.CreatePointsAttr([(-width/2,0,-height/2),(width/2,0,-height/2),(width/2,0,height/2),(-width/2,0,height/2)])
        prim.CreateFaceVertexCountsAttr([4]);prim.CreateFaceVertexIndicesAttr([0,1,2,3])
        prim.CreateSubdivisionSchemeAttr('none');prim.CreateDoubleSidedAttr(True)
        prim.AddTranslateOp().Set(Gf.Vec3d(x,y,z))
        uv=UsdGeom.PrimvarsAPI(prim).CreatePrimvar('st',Sdf.ValueTypeNames.TexCoord2fArray,UsdGeom.Tokens.vertex)
        uv.Set([(0,0),(1,0),(1,1),(0,1)])
        bind(prim.GetPrim(), mat)
        box('Signs/'+name+'_back', (x,y+.07,z), (width+.1,.05,height+.1), steel)

    sign('A', 'A  /  OPERATIONS', (2,4.3,3.3), 5, 1.25, (22,65,102))
    sign('B1', 'B1  /  INSPECTION', (12.5,-2.55,3), 3.8,.95,(151,91,20))
    sign('B2', 'B2  /  INSPECTION', (17.5,-1.3,3), 3.8,.95,(151,91,20))
    box('StoryService/Counter',(-5,0,.6),(2.4,1.2,1.2),light_metal,True)
    box('StoryService/Top',(-5,0,1.24),(2.5,1.3,.08),dark)
    anchor(stage,semantics,'production_counter',[-5,-2,0])
    semantics['production_queue']={'kind':'queue','prim_path':'/World/Locations/production_counter',
        'slots_m':[[-5,-2-i*1.25,0] for i in range(4)],'egress_targets':[[-7.5,-2,0],[-2.5,-2,0]],'capacity':4}
    sign('Service', 'SHIFT  /  CHECK IN', (-5,.7,2.8), 4.6,1.15,(26,60,77))
    sign('Rest', 'REST  BAY', (6.25,-7.9,3.2), 1.8,.45,(31,73,75))
    for i,(x,y) in enumerate([(2.5,-5),(5,-5)]):
        box(f'Route/Blue{i}', (x,-2.6,.006), (.07,4,.004), blue)
    box('Route/Amber', (12,-5,.006), (15,.07,.004), amber)
    for i,(x,y) in enumerate([(-9,-6),(6,-6),(16,8),(-15,8)]):
        lamp=UsdLux.RectLight.Define(stage, f'/World/Production/Light{i}')
        lamp.AddTranslateOp().Set(Gf.Vec3d(x,y,8))
        lamp.CreateWidthAttr(5);lamp.CreateHeightAttr(1.6);lamp.CreateIntensityAttr(800)
        lamp.CreateColorAttr(Gf.Vec3f(.8,.88,1))
    dome=UsdLux.DomeLight(stage.GetPrimAtPath('/World/Dome'));dome.GetIntensityAttr().Set(450)
    dome.CreateColorAttr(Gf.Vec3f(.76,.85,1))
    sun=UsdLux.DistantLight(stage.GetPrimAtPath('/World/Sun'));sun.GetIntensityAttr().Set(1900)
    sun.CreateColorAttr(Gf.Vec3f(1,.84,.66))
    semantics['_production']={'kind':'metadata','art':'shift-change-v1','chair_geometry':'unchanged generated-chair-v3',
                              'navigation':'rebake and validate cast routes before capture'}
    return semantics
