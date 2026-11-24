"""Selected actual deformed-surface samples from a frozen feature take."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--take',required=True);p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);args=p.parse_args();take=ROOT/'runs'/args.take;out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}));part=json.loads((take/'bootstrap.json').read_text())['part'];sys.path.insert(0,str(take/'source_snapshot/src'));sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});code=0
try:
 import omni.usd,numpy as np
 from simpeople.backends.native.platform04_90_scene import create_director_scene
 from simpeople.backends.native.platform04_feature_director import FeatureDirector
 from simpeople.backends.native.platform04_90_observation import PerformanceReadback
 from simpeople.backends.native.mesh_intersections import surface_intersections
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();scene=create_director_scene(stage,ROOT);director=FeatureDirector(stage,scene,ROOT,out,part);observer=PerformanceReadback(ROOT,out,director.actors)
 times=np.arange(65.,71.01,.1) if part=='after' else np.arange(77.,80.51,.1) if part=='gate' else np.arange(57.4,61.01,.1);ids=[a for a in ['H01','H02','H03','F01','F02','F03','F04'] if a in director.actors];hits=[];tested=0;log=(out/'actual_joints.jsonl').open('w')
 for t in times:
  director.update(float(t*30));actual={aid:observer.read_actor(aid) for aid in ids}
  log.write(json.dumps({'time_s':float(t),'actors':{aid:a['joints_world_m'].tolist() for aid,a in actual.items()}})+'\n')
  for i,a in enumerate(ids):
   for b in ids[i+1:]:
    if not (a.startswith('H') or b.startswith('H')):continue
    aa,bb=actual[a]['triangles'],actual[b]['triangles'];tested+=1
    if not np.all(aa.max((0,1))>=bb.min((0,1))) or not np.all(bb.max((0,1))>=aa.min((0,1))):continue
    check=surface_intersections(aa,bb)
    if check['intersecting_pairs']:hits.append({'time_s':float(t),'actors':[a,b],**check})
 log.close();(out/'geometry_qa.json').write_text(json.dumps({'take':args.take,'part':part,'source_snapshot':str(take/'source_snapshot'),'sample_times_s':times.tolist(),'pair_tests':tested,'intersections':hits,'scope':'selected 10Hz actual deformed actor surfaces; survivor-vs-character pairs only; no self collision, continuous CCD, contact forces or all-cast all-frame guarantee'},indent=2));(out/'completed.json').write_text(json.dumps({'sampled_surface_check_passed':not hits,'positive_simulation_steps':0,'human_reviewers':0},indent=2));print('sampled feature surfaces',part,'hits',len(hits),flush=True)
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:app.close()
raise SystemExit(code)
