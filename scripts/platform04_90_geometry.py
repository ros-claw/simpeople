"""120 Hz critical-window skin/sweep audit of the formal door choreography."""
import argparse,json,os,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,out/Path(__file__).name);sys.path.insert(0,str(out/'source_snapshot/src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});code=0
try:
 import omni.usd,numpy as np
 from scipy.spatial import cKDTree
 from simpeople.backends.native.platform04_90_scene import create_director_scene
 from simpeople.backends.native.platform04_90_director import Director90
 from simpeople.backends.native.platform04_90_observation import PerformanceReadback
 from simpeople.backends.native.mesh_intersections import surface_intersections
 from simpeople.backends.native.linear_sweep import swept_surface_intersections
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();scene=create_director_scene(stage,ROOT);director=Director90(stage,scene,ROOT,out,'door');observer=PerformanceReadback(ROOT,out,director.actors);director.update(1590)
 samples=sorted(set(range(1590*4,1890*4,4))|set(range(round(57.7*120),round(60.5*120)+1)));trace=[];intersections=[];sweeps=[];door=[];min_shoe={};previous=None;log=(out/'principal_joints_30hz.jsonl').open('w')
 for number,tick in enumerate(samples):
  frame=tick/4;row=director.update(frame);clouds={};read={};parts={}
  for aid in ['H01','F01','F02']:
   a=observer.read_actor(aid);read[aid]=a;clouds[aid]=a['cloud'];parts[aid]=dict(zip(a['part_paths'],a['parts']));actor=director.actors[aid];shoes=np.concatenate([parts[aid][str(m['prim'].GetPath())][m['feet']] for m in actor.meshes if str(m['prim'].GetPath()) in parts[aid] and m['feet'].any()]);z=float(shoes[:,2].min())
   if aid not in min_shoe or z<min_shoe[aid]['z_m']:min_shoe[aid]={'z_m':z,'source_tick':frame}
  actor=director.actors['F02'];hand=np.concatenate([parts['F02'][str(m['prim'].GetPath())][m['hands']['R']] for m in actor.meshes if str(m['prim'].GetPath()) in parts['F02'] and m['hands']['R'].any()]);d,_=cKDTree(clouds['H01']).query(hand);trace.append({'source_tick':frame,'time_s':tick/120,'hand_hero_vertex_distance_m':float(d.min())})
  critical=57.7<=tick/120<=60.5
  if tick%4==0:log.write(json.dumps({'source_tick':int(frame),'actors':{aid:a['joints_world_m'].tolist() for aid,a in read.items()}})+'\n')
  if critical or tick%20==0:
   for a,b in [('H01','F02'),('F01','F02'),('H01','F01')]:
    check=surface_intersections(read[a]['triangles'],read[b]['triangles'])
    if check['intersecting_pairs']:
     intersections.append({'source_tick':frame,'pair':[a,b],**check});print('CONTACT',intersections[-1],flush=True)
    if critical and previous is not None and tick-previous['tick']==1:
     check=swept_surface_intersections(previous['read'][a]['triangles'],read[a]['triangles'],previous['read'][b]['triangles'],read[b]['triangles']);sweeps.append({'source_tick':frame,'pair':[a,b],**check})
  if critical:
   cloud=clouds['F02'];lo=cloud.min(0);hi=cloud.max(0)
   for box in scene['boxes']:
    if box['group']!='Car' or box['kind']!='solid' or box.get('rot_z'):continue
    center=np.array(box['center']);half=np.array(box['size'])/2;low=center-half;high=center+half
    if not np.all(hi>=low) or not np.all(lo<=high):continue
    depth=np.minimum(cloud-low,high-cloud).min(axis=1);which=np.flatnonzero(depth>.002)
    if len(which):door.append({'source_tick':frame,'box':box['name'],'vertices':int(len(which)),'max_depth_m':float(depth[which].max())})
  previous={'tick':tick,'read':read}
  if number%60==0:print('geometry',number,'time',tick/120,'near',trace[-1]['hand_hero_vertex_distance_m'],'intersections',len(intersections),'sweep_hits',sum(x['contact_pairs'] for x in sweeps),flush=True)
 log.close();result={'sample_count':len(samples),'critical_window_s':[57.7,60.5],'critical_hz':120,'outside_hz':30,'near_miss':min(trace,key=lambda r:r['hand_hero_vertex_distance_m']),'minimum_actual_shoe_height':min_shoe,'triangle_intersections':intersections,'door_frame_vertices_deeper_than_2mm':door,'linear_sweep_intervals':len(sweeps),'linear_sweep_contacts':[x for x in sweeps if x['contact_pairs']],'linear_sweep_unresolved_coplanar_pairs':sum(x['unresolved_coplanar_pairs'] for x in sweeps),'scope':'actual deformed formal USD skin and props; linear vertex sweeps between 120Hz samples approximate articulated motion, not a continuous physical contact certificate','not_measured':['all background pairs','self collision','PhysX forces','continuous nonlinear articulated CCD','human naturalness/fear']};(out/'geometry_qa.json').write_text(json.dumps(result,indent=2));(out/'near_miss_trace.json').write_text(json.dumps(trace,indent=2));(out/'completed.json').write_text(json.dumps({'samples':len(samples),'positive_simulation_steps':0,'report':'geometry_qa.json','quality_passed':not intersections and not door and not result['linear_sweep_contacts'] and not result['linear_sweep_unresolved_coplanar_pairs'],'unresolved_sweep_pairs':result['linear_sweep_unresolved_coplanar_pairs']},indent=2))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:app.close()
raise SystemExit(code)
