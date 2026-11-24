"""Replay recorded production joint transforms, inspect actual skinned vertices.

No positive simulation steps, no animation reconstructed from root distances.
Reports vertex distances and box penetration, not full contact certification.
"""
import argparse,sys,os,json,shutil,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--source-run',default='platform04-master-01');p.add_argument('--gpu',type=int,default=3);args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);source=ROOT/'runs'/args.source_run;(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));shutil.copy2(__file__,out/Path(__file__).name);shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));sys.path.insert(0,str(out/'source_snapshot/src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});code=0
try:
 import omni.usd,numpy as np
 from pxr import UsdGeom,Gf,Vt
 from scipy.spatial import cKDTree
 from simpeople.backends.native.mesh_intersections import surface_intersections
 from simpeople.backends.native.platform04_scene import create_metro
 from simpeople.backends.native.platform04_animation import MetroMotion,MetroActor
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();scene=create_metro(stage,ROOT);bank=MetroMotion(ROOT);assets=json.loads((ROOT/'configs/assets.json').read_text())['assets'];casting=json.loads((source/'casting.json').read_text());actors={}
 for aid in ['hero','chaser','intercept']:
  asset=next(x for x in assets if x['asset_id']==casting[aid]['base_asset']);uri=ROOT/'assets/characters'/asset['source_uri'].removeprefix('characters://');actors[aid]=MetroActor(stage,'/World/Actors/'+aid,bank,source_uri=str(uri))
 topology={}
 for aid,a in actors.items():
  faces=[];offset=0
  for mesh in a.meshes:
   if str(UsdGeom.Imageable(mesh['prim']).ComputeVisibility())=='invisible':continue
   m=UsdGeom.Mesh(mesh['prim']);ix=list(m.GetFaceVertexIndicesAttr().Get());cursor=0
   for count in m.GetFaceVertexCountsAttr().Get():
    for j in range(1,count-1):faces.append([offset+ix[cursor],offset+ix[cursor+j],offset+ix[cursor+j+1]])
    cursor+=count
   offset+=len(m.GetPointsAttr().Get())
  topology[aid]=np.array(faces,dtype=int)
 rows=[json.loads(l) for l in (source/'frames.jsonl').open()];contacts={};intervals=[];gait_mins={a:{'z_m':1,'frame':None} for a in actors};near=[];penetrations=[];pair_minima={};meshes={};active_clip_min=None;triangle_checks=[]
 for row in rows:
  frame=row['source_tick'];clouds={};feet={};hands={}
  for aid,a in actors.items():
   r=row['actors'][aid];yaw=r['yaw_rad'];matrix=Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0,0,1),math.degrees(yaw)));matrix.SetTranslateOnly(Gf.Vec3d(*r['root_world_m']));m=np.asarray(matrix);world=np.array(r['joints_world_m']);p=(world-m[3,:3])@m[:3,:3].T;q=np.array(r['joint_quaternions_actor']);t,rot=bank.local_trs(p,q);a.animation.GetTranslationsAttr().Set(Vt.Vec3fArray.FromNumpy(t.astype(np.float32)));a.animation.GetRotationsAttr().Set(Vt.QuatfArray([Gf.Quatf(float(v[3]),Gf.Vec3f(*map(float,v[:3]))) for v in rot]));a.xform.Set(matrix);a.joint_p=p;a.joint_q=q
   skinned=a.skin_points();body=[];foot={'L':[],'R':[]};hand=[]
   for mesh in a.meshes:
    if str(UsdGeom.Imageable(mesh['prim']).ComputeVisibility())=='invisible':continue
    vertices=skinned[str(mesh['prim'].GetPath())]@m[:3,:3]+m[3,:3];body.append(vertices)
    for side in ['L','R']:
     if np.any(mesh['feet_sides'][side]):foot[side].append(vertices[mesh['feet_sides'][side]])
    if np.any(mesh['hands']['R']):hand.append(vertices[mesh['hands']['R']])
   clouds[aid]=np.concatenate(body);feet[aid]={s:np.concatenate(v) for s,v in foot.items()};hands[aid]=np.concatenate(hand);meshes[aid]={'vertices':len(clouds[aid]),'skinned_parts':len(a.meshes)}
   z=min(float(v[:,2].min()) for v in feet[aid].values())
   if z<gait_mins[aid]['z_m']:gait_mins[aid]={'z_m':z,'frame':frame}
   for side,pts in feet[aid].items():
    key=aid+side;grounded=float(pts[:,2].min())<=.025 and 132<=frame<=280
    if grounded:
     if key not in contacts:
      mask=pts[:,2]<float(pts[:,2].min())+.008;contacts[key]={'actor':aid,'side':side,'start_frame':frame,'frames':0,'mask':mask,'anchor':pts[mask,:2].copy(),'max_patch_drift_m':0.}
     c=contacts[key];c['frames']+=1;c['max_patch_drift_m']=max(c['max_patch_drift_m'],float(np.linalg.norm(pts[c['mask'],:2]-c['anchor'],axis=1).max()))
    elif key in contacts:
     c=contacts.pop(key);intervals.append({k:v for k,v in c.items() if k not in ['mask','anchor']})
  if 294<=frame<=390:
   tree=cKDTree(clouds['hero']);d,_=tree.query(hands['intercept']);n={'frame':frame,'min_hand_hero_vertex_distance_m':float(d.min())};near.append(n)
   for a,b in [('hero','intercept'),('chaser','intercept'),('hero','chaser')]:
    d,_=cKDTree(clouds[a]).query(clouds[b]);key=a+'/'+b;value=float(d.min())
    if key not in pair_minima or value<pair_minima[key]['distance_m']:pair_minima[key]={'distance_m':value,'frame':frame}
    tri=surface_intersections(clouds[a][topology[a]],clouds[b][topology[b]]);triangle_checks.append({'frame':frame,'pair':key,**tri})
   # World-space skin points against the real axis-aligned door/frame solids.
   cloud=clouds['intercept'];lo=cloud.min(0);hi=cloud.max(0)
   for b in scene['boxes']:
    if b['group']!='Car' or b['kind']!='solid' or b.get('rot_z'):continue
    center=np.array(b['center']);half=np.array(b['size'])/2;low=center-half;high=center+half
    if not np.all(hi>=low) or not np.all(lo<=high):continue
    depth=np.minimum(cloud-low,high-cloud).min(axis=1);ids=np.flatnonzero(depth>.002)
    if len(ids):penetrations.append({'frame':frame,'box':b['name'],'penetrating_vertices':int(len(ids)),'max_depth_m':float(depth[ids].max())})
  if frame%90==0:print('qa frame',frame,flush=True)
 for c in contacts.values():intervals.append({k:v for k,v in c.items() if k not in ['mask','anchor']})
 supported=[x for x in intervals if x['frames']>=2];report={'source_run':args.source_run,'sample_hz':30,'frames':len(rows),'geometry':'fresh UsdSkel skinning from recorded actual production joint world transforms; references to original formal meshes','mesh_coverage':meshes,'shoe_minima':gait_mins,'straight_running_contact_intervals':intervals,'measured_multi_frame_contacts':len(supported),'max_multi_frame_patch_drift_m':max((r['max_patch_drift_m'] for r in supported),default=None),'3cm_contact_target_passed':bool(supported) and all(r['max_patch_drift_m']<=.03 for r in supported),'near_miss':min(near,key=lambda r:r['min_hand_hero_vertex_distance_m']),'minimum_whole_body_vertex_distances':pair_minima,'door_frame_vertex_penetrations_over_2mm':penetrations,'foreground_triangle_surface_checks':{'samples':len(triangle_checks),'intersecting_pairs':sum(x['intersecting_pairs'] for x in triangle_checks),'frames_with_intersections':[x for x in triangle_checks if x['intersecting_pairs']]},'not_measured':['continuous swept-time collision between the 30Hz samples','contact forces','self collision','all background crowd pairs'],'scope':'vertex samples are not an exhaustive collision certificate; single-frame contacts lack a measurable interval'};(out/'geometry_qa.json').write_text(json.dumps(report,indent=2));(out/'near_miss_trace.json').write_text(json.dumps(near,indent=2));(out/'completed.json').write_text(json.dumps({'frames_checked':len(rows),'positive_simulation_steps':0,'report':'geometry_qa.json'},indent=2));print('max drift',report['max_multi_frame_patch_drift_m'],'penetrations',len(penetrations),flush=True)
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:app.close()
raise SystemExit(code)
