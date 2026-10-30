"""Contact-proxy audit. Contact uses height/vertical motion, never horizontal speed.

Points are calibrated against the initial idle floor; these are shoe proxies,
not force contacts or a claim of exact mesh-ground contact.
"""
import argparse
import json
import math
from pathlib import Path
import statistics

def rotate(q,v):
    x,y,z,w=q;u=[x,y,z]
    cross=lambda a,b:[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
    uv=cross(u,v);uuv=cross(u,uv)
    return [v[i]+2*(w*uv[i]+uuv[i]) for i in range(3)]

def audit(directory,actor=None):
    directory=Path(directory);rows=[]
    with (directory/'trajectories.jsonl').open() as f:
        for line in f:
            r=json.loads(line)
            if not r.get('ready') or not r.get('joint_rotations_xyzw_stage'):continue
            if actor is None:actor=r['actor_id']
            if r['actor_id']==actor:rows.append(r)
    if len(rows)<10:raise ValueError('not enough actual quality samples')
    start=rows[0]['sim_time'];idle=[r for r in rows if start+.3<r['sim_time']<start+1.6 and r['action']=='Idle']
    if len(idle)<5:raise ValueError('initial idle calibration missing')
    calibration={};points={}
    for side in ('Left','Right'):
        for tag in (side+'Foot',side+'ToeBase'):
            sample=min(idle,key=lambda r:abs(r['joints_m'][tag][2]-statistics.median(x['joints_m'][tag][2] for x in idle)))
            q=sample['joint_rotations_xyzw_stage'][tag];p=sample['joints_m'][tag]
            world=[0,0,-p[2]]
            if tag.endswith('Foot'):
                toe=sample['joints_m'][side+'ToeBase'];d=[toe[i]-p[i] for i in range(2)];norm=math.hypot(*d)
                if norm>1e-5:world[:2]=[-.04*v/norm for v in d]
            local=rotate([-q[0],-q[1],-q[2],q[3]],world)
            calibration[tag]={'local_offset_m':local,'idle_joint_height_m':p[2],'label':'heel_proxy' if tag.endswith('Foot') else 'forefoot_proxy'}
            pts=[]
            for r in rows:
                if tag not in r['joints_m'] or tag not in r['joint_rotations_xyzw_stage']:pts.append(None);continue
                v=rotate(r['joint_rotations_xyzw_stage'][tag],local);pts.append([r['joints_m'][tag][i]+v[i] for i in range(3)])
            points[tag]=pts
    intervals=[]
    for tag,pts in points.items():
        active=[]
        def finish():
            if len(active)<3:return
            first=active[0];last=active[-1];duration=rows[last]['sim_time']-rows[first]['sim_time']
            if duration<.06:return
            drift=max(math.dist(pts[first][:2],pts[i][:2]) for i in active)
            path=sum(math.dist(pts[a][:2],pts[b][:2]) for a,b in zip(active,active[1:]))
            intervals.append({'point':tag,'start_sim_time':rows[first]['sim_time'],'end_sim_time':rows[last]['sim_time'],
                 'duration_s':duration,'max_drift_m':drift,'path_m':path,'start_frame':rows[first]['frame_identity'].get('video_frame'),
                 'end_frame':rows[last]['frame_identity'].get('video_frame'),'native_tasks':sorted({r['native_task_id'] for r in (rows[i] for i in active)})})
        for i,r in enumerate(rows):
            contact=False
            if 0<i<len(rows)-1 and pts[i] and pts[i-1] and pts[i+1]:
                dt=rows[i+1]['sim_time']-rows[i-1]['sim_time']
                vz=(pts[i+1][2]-pts[i-1][2])/dt if dt>0 else 999
                contact=abs(pts[i][2])<=.025 and abs(vz)<=.15 and r['planar_speed_mps']>.25
            if contact:active.append(i)
            else:finish();active=[]
        finish()
    intervals.sort(key=lambda v:v['max_drift_m'],reverse=True)
    ordered=sorted(x['max_drift_m'] for x in intervals)
    report={'actor_id':actor,'samples':len(rows),'contact_method':'initial idle-calibrated heel/forefoot shoe proxies; |height|<=.025m, |vertical speed|<=.15m/s, >=3 samples/.06s. Horizontal foot speed is NOT a contact predicate. Root speed>.25 selects locomotion.',
       'limitations':'contact estimate; toe-off/heel-strike sensitivity remains; proxy threshold requires image review, no exact no-slip claim',
       'calibration':calibration,'contact_intervals':len(intervals),'drift_median_m':statistics.median(ordered) if ordered else None,
       'drift_p95_m':ordered[min(len(ordered)-1,int(len(ordered)*.95))] if ordered else None,'worst_intervals':intervals[:20],
       'root_changed_without_sim_time_samples':sum(r.get('root_changed_without_sim_time',False) for r in rows),
       'native_task_count':len({r['native_task_id'] for r in rows if r['action'].startswith('Move')})}
    (directory/'gait_quality.json').write_text(json.dumps(report,indent=2));return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--actor');a=p.parse_args()
    r=audit(a.directory,a.actor);print(json.dumps({k:v for k,v in r.items() if k not in {'calibration','worst_intervals'}},indent=2))
