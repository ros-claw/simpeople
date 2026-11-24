"""Native diagnostic geometry shared by old and new runtime snapshots."""
import omni.usd
from .environments import industrial_scene
from .scene import mesh_box

def narrow_traffic_probe_scene():
    """Diagnostic layout: the existing industrial door is the only crossing.

    Production industrial_scene stays unchanged. Walls meet the floor boundary,
    so a fairness test cannot silently succeed by walking around a short wall.
    """
    sem=industrial_scene();stage=omni.usd.get_context().get_stage()
    boxes=[{'path':'/World/T2Probe/North','position':[0,6.4,1],'size':[.3,31.2,2]},
           {'path':'/World/T2Probe/South','position':[0,-16.4,1],'size':[.3,11.2,2]}]
    for box in boxes:mesh_box(stage,box['path'],box['position'],box['size'],(.46,.53,.58))
    sem['t2_narrow_layout']={'kind':'layout_revision','revision':'floor_spanning_door_v1','wall_boxes':boxes}
    return sem


def narrow_release_scene():
    """New release fixture revision; original diagnostic geometry is unchanged."""
    from simpeople.core.release_scene import narrow_release_semantics
    return narrow_release_semantics(narrow_traffic_probe_scene())
