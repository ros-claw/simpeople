"""Actual-skin and static-scene R2 audit; fine samples around the action phrase."""
import argparse,json,os,sys,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copy2(__file__,out/Path(__file__).name);sys.path.insert(0,str(out/'source_snapshot/src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});code=0
try:
 import omni.usd,numpy as np
 from simpeople.backends.native.platform04_90_scene import create_director_scene
 from simpeople.backends.native.platform04_r2_director import R2Director
 from simpeople.backends.native.platform04_90_observation import PerformanceReadback
 from simpeople.backends.native.mesh_intersections import surface_intersections
 from simpeople.backends.native.linear_sweep import swept_surface_intersections
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();scene=create_director_scene(stage,ROOT);director=R2Director(stage,scene,ROOT,out,'trio');observer=PerformanceReadback(ROOT,out,director.actors);director.update(0)
 samples=sorted(set(range(0,1200,4))|set(range(round(4.3*120),round(7.7*120)+1)));intersections=[];static=[];sweeps=[];previous=None;min_shoe={};log=(out/'principal_joints_30hz.jsonl').open('w');events=(out/'geometry_events.jsonl').open('w',buffering=1)
 (out/'scene_boxes.json').write_text(json.dumps(scene['boxes'],indent=2))
 def overlaps(a,b):return np.all(a.max((0,1))>=b.min((0,1))) and np.all(b.max((0,1))>=a.min((0,1)))
 for n,tick in enumerate(samples):
  frame=tick/4;row=director.update(frame);read={aid:observer.read_actor(aid) for aid in director.actors};critical=4.3<=tick/120<=7.7
  for aid,a in read.items():
   actor=director.actors[aid];parts=dict(zip(a['part_paths'],a['parts']));shoes=np.concatenate([parts[str(m['prim'].GetPath())][m['feet']] for m in actor.meshes if str(m['prim'].GetPath()) in parts and m['feet'].any()]);z=float(shoes[:,2].min())
   if aid not in min_shoe or z<min_shoe[aid]['z_m']:min_shoe[aid]={'z_m':z,'frame':frame}
   cloud=a['cloud'];lo=cloud.min(0);hi=cloud.max(0)
   for b in scene['boxes']:
    if b['kind'] in ['glass','light','wet'] or b.get('rot_z'):continue
    center=np.array(b['center']);half=np.array(b['size'])/2;low=center-half;high=center+half
    if not np.all(hi>low) or not np.all(lo<high):continue
    depth=np.minimum(cloud-low,high-cloud).min(axis=1);ix=np.flatnonzero(depth>.003)
    if len(ix):
     event={'frame':frame,'time_s':tick/120,'actor':aid,'box':b['name'],'group':b['group'],'inside_vertices':int(len(ix)),'max_depth_m':float(depth[ix].max())};static.append(event);events.write(json.dumps({'type':'static',**event})+'\n')
  for a,b in [('H01','F02'),('F01','F02'),('H01','F01')]:
   aa,bb=read[a]['triangles'],read[b]['triangles']
   check=surface_intersections(aa,bb) if overlaps(aa,bb) else {'candidate_pairs':0,'intersecting_pairs':0}
   if check['intersecting_pairs']:
    event={'frame':frame,'pair':[a,b],**check};intersections.append(event);events.write(json.dumps({'type':'pair',**event})+'\n')
   if critical and previous is not None and tick-previous['tick']==1:
    a0,b0=previous['read'][a]['triangles'],previous['read'][b]['triangles'];sa=np.concatenate([a0,aa],1);sb=np.concatenate([b0,bb],1)
    swept=swept_surface_intersections(a0,aa,b0,bb) if overlaps(sa,sb) else {'candidate_pairs':0,'contact_pairs':0,'contacts':[],'unresolved_coplanar_pairs':0};sweeps.append({'frame':frame,'pair':[a,b],**swept})
  if tick%4==0:log.write(json.dumps({'source_tick':int(frame),'actors':{aid:a['joints_world_m'].tolist() for aid,a in read.items()}})+'\n')
  previous={'tick':tick,'read':read}
  if n%80==0:print('R2 geometry',n,'t',tick/120,'static',len(static),'intersections',len(intersections),'sweep contacts',sum(x['contact_pairs'] for x in sweeps),flush=True)
 log.close();events.close();result={'samples':len(samples),'critical_window_s':[4.3,7.7],'critical_hz':120,'outside_hz':30,'principals':list(director.actors),'minimum_actual_shoe_height':min_shoe,'sampled_triangle_intersections':intersections,'static_box_intrusions_deeper_than_3mm':static,'linear_sweep_intervals':len(sweeps),'linear_sweep_contacts':[x for x in sweeps if x['contact_pairs']],'unresolved_coplanar_pairs':sum(x['unresolved_coplanar_pairs'] for x in sweeps),'scope':'actual deformed skin/attached bags; actual authored boxes used as static proxies. Triangle sweeps approximate vertex motion linearly between samples, not nonlinear CCD or PhysX forces. Self-collision not measured.'};(out/'geometry_qa.json').write_text(json.dumps(result,indent=2));(out/'completed.json').write_text(json.dumps({'quality_passed':not intersections and not static and not result['linear_sweep_contacts'] and not result['unresolved_coplanar_pairs'],'samples':len(samples),'positive_simulation_steps':0,'human_reviewers':0},indent=2))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:app.close()
raise SystemExit(code)
