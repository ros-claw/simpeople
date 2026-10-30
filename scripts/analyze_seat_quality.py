"""Aggregate actual native seat proxies and skinned-vertex evidence by rig/phase."""
import argparse,json
from collections import defaultdict
from pathlib import Path

def analyze(directory):
 d=Path(directory);actors={};worst_frames=[]
 for line in (d/'trajectories.jsonl').open():
  row=json.loads(line);aid=row.get('asset_id')
  if not row.get('ready') or not aid:continue
  for seat,quality in row.get('seat_quality',{}).items():
   x=actors.setdefault(aid,{'actor_id':row['actor_id'],'asset_id':aid,'seat':seat,'proxy_samples':0,'fine_samples':0,'fine_unavailable':[],
         'head_neck_proxy_min_m':None,'skinned_vertex_min_m':None,'frames_with_penetrating_vertices':0,'max_penetrating_vertices':0,'phases':{},'worst':None})
   x['proxy_samples']+=1
   tests=[v for k,v in quality.get('proxy_clearance_m',{}).items() if k!='chest_back_capsule']
   if tests:x['head_neck_proxy_min_m']=min(tests+[x['head_neck_proxy_min_m']] if x['head_neck_proxy_min_m'] is not None else tests)
   fine=quality.get('skinned_vertices')
   if fine is None:continue
   if not fine['available']:
    if fine.get('reason') not in x['fine_unavailable']:x['fine_unavailable'].append(fine.get('reason'))
    continue
   x['fine_samples']+=1;distance=fine['worst']['clearance_m'];phase=row.get('task_step_phase',row.get('action','unknown'))
   record=x['phases'].setdefault(phase,{'samples':0,'vertex_min_m':distance,'frames_with_penetration':0});record['samples']+=1;record['vertex_min_m']=min(record['vertex_min_m'],distance)
   if fine['penetrating_vertices']:
    x['frames_with_penetrating_vertices']+=1;record['frames_with_penetration']+=1
   x['max_penetrating_vertices']=max(x['max_penetrating_vertices'],fine['penetrating_vertices'])
   if x['skinned_vertex_min_m'] is None or distance<x['skinned_vertex_min_m']:
    x['skinned_vertex_min_m']=distance;x['worst']={'sim_time':row['sim_time'],'frame_identity':row.get('frame_identity'),'detail':fine,'joints_m':row['joints_m']}
 result={'actors':actors,'rigs_sampled':len(actors),'rigs_without_vertex_penetration':sum(x['fine_samples']>0 and x['frames_with_penetrating_vertices']==0 for x in actors.values()),
         'measurement':'actual native joint-driven linear-skinned head/neck vertices every third audit observation; OBB signed distance',
         'limitations':['vertex tests are not exhaustive triangle intersections','fixed calibrated seat geometry; arbitrary chairs remain unverified','runtime head/neck spheres are conservative proxies'],
         'fine_all_available':all(x['fine_samples']>0 and not x['fine_unavailable'] for x in actors.values())}
 (d/'seat_quality.json').write_text(json.dumps(result,indent=2));return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args();r=analyze(a.directory)
 print(json.dumps({k:v for k,v in r.items() if k!='actors'},indent=2))
 print(json.dumps({a:{k:x[k] for k in ['fine_samples','head_neck_proxy_min_m','skinned_vertex_min_m','frames_with_penetrating_vertices']} for a,x in r['actors'].items()},indent=2))
