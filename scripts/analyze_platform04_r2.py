"""Actual source-frame support, speed, visibility and fixed-target audit."""
import argparse,json
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def analyse(run):
    rs=[json.loads(l) for l in (run/'frames.jsonl').read_text().splitlines()];metadata=json.loads((run/'completed.json').read_text());groups={};roots={};commit=[]
    for row in rs:
        for aid,a in row['actors'].items():
            roots.setdefault(aid,[]).append((row['output_frame'],a['actual_root_matrix'][3][:3]))
            if a.get('committed_target_m') is not None:commit.append(a['committed_target_m'])
            for side,s in a.get('support',{}).items():
                if not s['planted'] or not s['support_is_full_weight']:continue
                key=(aid,side,s['support_id'],s['mesh_path'],s['vertex_id']);groups.setdefault(key,[]).append((row['output_frame'],np.array(s['actual_point_world_m']),np.array(s['point_goal_world_m'])))
    segments=[];short=[]
    for key,values in groups.items():
        chunks=[]
        for v in values:
            if not chunks or v[0]!=chunks[-1][-1][0]+1:chunks.append([])
            chunks[-1].append(v)
        for chunk in chunks:
            who,side,token,path,vertex=key;points=np.array([v[1] for v in chunk]);goals=np.array([v[2] for v in chunk]);r={'actor':who,'side':side,'support_id':token,'mesh_path':path,'vertex_id':int(vertex),'frames':[chunk[0][0],chunk[-1][0]],'samples':len(chunk),'duration_s':len(chunk)/30,'xy_drift_from_first_actual_m':float(np.linalg.norm((points-points[0])[:,:2],axis=1).max()),'xy_goal_residual_max_m':float(np.linalg.norm((points-goals)[:,:2],axis=1).max()),'actual_z_range_m':[float(points[:,2].min()),float(points[:,2].max())]}
            (segments if len(chunk)>=3 else short).append(r)
    motion={}
    for aid,values in roots.items():
        p=np.array([v[1] for v in values]);t=np.array([v[0] for v in values])/30;distance=float(np.linalg.norm(np.diff(p[:,:2],axis=0),axis=1).sum());motion[aid]={'actual_root_distance_m':distance,'mean_speed_over_source_interval_mps':distance/(t[-1]-t[0]) if len(t)>1 else None,'scope':'preview intervals are sparse; only closed full takes used for formal speed matching'}
    result={'run_id':run.name,'preview':metadata['preview'],'actual_motion':motion,'support_segments':segments,'short_or_sparse_support_intervals':short,'worst_xy_plant_drift_m':max((r['xy_drift_from_first_actual_m'] for r in segments),default=None),'worst_xy_goal_residual_m':max((r['xy_goal_residual_max_m'] for r in segments),default=None),'committed_target_range_m':np.ptp(commit,axis=0).tolist() if commit else None,'support_scope':'animator-declared independent fixed mesh vertex + frame windows; actual skinned world coordinates; no contact force, no inference from toe height','human_role_identification':'not measured here','human_reviewers':0}
    (run/'performance_qa.json').write_text(json.dumps(result,indent=2));return result
def main():
    p=argparse.ArgumentParser();p.add_argument('runs',nargs='+');a=p.parse_args()
    for name in a.runs:
        r=analyse(ROOT/'runs'/name);print(name,'plant drift',r['worst_xy_plant_drift_m'],'goal error',r['worst_xy_goal_residual_m'],'target range',r['committed_target_range_m'])
if __name__=='__main__':main()
