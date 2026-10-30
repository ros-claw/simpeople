"""Verify the rendered RGB's SDK timestamp against a known time-sampled signal."""
import json
from pathlib import Path
import sys
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'src'))
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':1,'multi_gpu':False,'limit_cpu_threads':8,
                   'disable_viewport_updates':True})
try:
    import carb
    import omni.usd
    import omni.timeline
    import omni.kit.app
    import omni.replicator.core as rep
    from omni.syntheticdata import SyntheticData
    from pxr import Gf,Usd,UsdGeom,UsdLux
    from simpeople.backends.native.scene import build_scene,mesh_box
    omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate('omni.anim.navigation.core',True)
    omni.usd.get_context().new_stage();build_scene(False)
    stage=omni.usd.get_context().get_stage()
    for p in ['/World/WallA','/World/WallB','/World/DoorPost','/World/MovableBox','/World/Chair','/World/Workbench']:stage.RemovePrim(p)
    cube=mesh_box(stage,'/World/Signal',(0,0,.7),(3,3,1.4),(1,0,0))
    colors=[Gf.Vec3f(1,0,0),Gf.Vec3f(0,1,0),Gf.Vec3f(0,0,1)]
    color=UsdGeom.Mesh(cube).GetDisplayColorAttr()
    stage.SetInterpolationType(Usd.InterpolationTypeHeld)
    for frame in range(100):color.Set([colors[frame%3]],Usd.TimeCode(frame))
    product=rep.create.render_product('/World/Camera',(960,540))
    rgb=rep.AnnotatorRegistry.get_annotator('rgb',device='cuda',do_array_copy=False);rgb.attach([product])
    timeline=omni.timeline.get_timeline_interface();timeline.set_time_codes_per_second(30)
    timeline.set_auto_update(False);timeline.set_end_time(1000);timeline.play()
    carb.settings.get_settings().set('/app/player/useFixedTimeStepping',True)
    results=[]
    for _ in range(30):
        timeline.forward_one_frame();app.update()
        data=rgb.get_data(device='cpu')
        stamp=SyntheticData.Get().get_node_attributes('PostProcessDispatcher',
                    ['outputs:referenceTimeNumerator','outputs:referenceTimeDenominator'])
        if not stamp or not stamp.get('outputs:referenceTimeDenominator') or data.size==0:continue
        render_time=stamp['outputs:referenceTimeNumerator']/stamp['outputs:referenceTimeDenominator']
        pixel=data[260:280,470:490,:3].mean(axis=(0,1));observed=int(pixel.argmax())
        expected=round(render_time*30)%3
        results.append({'sim_time':timeline.get_current_time(),'render_time':render_time,
                        'pixel_mean':pixel.tolist(),'observed_color':observed,'expected_color':expected,'match':observed==expected})
    report={'samples':results,'all_matched':bool(results) and all(s['match'] for s in results),
            'method':'RGB signal sampled at each USD frame and SDK PostProcessDispatcher rational render time'}
    (root/'reports/capture_timestamp_probe.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'all_matched':report['all_matched'],'samples':len(results),'last':results[-3:]}))
finally:app.close()
