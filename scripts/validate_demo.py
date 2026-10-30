"""Check demo shot labels against real trajectories; extract exact source frames."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess

p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args();d=Path(a.directory).resolve()
sections=json.loads((d/'demo_bookmarks.json').read_text())['sections']
selected={s['label']:[] for s in sections if s['actor_id']}
for line in (d/'trajectories.jsonl').open():
    row=json.loads(line)
    for s in sections:
        if row['actor_id']==s['actor_id'] and s['start_sim_time']<=row['sim_time']<=s['end_sim_time']:
            selected[s['label']].append(row)
results={};checks={};samples=[]
for label,rows in selected.items():
    if not rows:raise ValueError('No measured rows for '+label)
    speeds=[r['planar_speed_mps'] for r in rows]
    flight=[r for r in rows if min(r['joints_m']['LeftFoot'][2],r['joints_m']['RightFoot'][2])>.12]
    fast=[r for r in rows if r['speed_mps']>2.2]
    results[label]={'actor_id':rows[0]['actor_id'],'samples':len(rows),'median_planar_speed_mps':statistics.median(speeds),
                   'max_planar_speed_mps':max(speeds),'samples_speed_above_2_2':len(fast),'both_feet_above_0_12_samples':len(flight)}
    if label.startswith('WALK'):
        checks['walking_actual_speed']=statistics.median(speeds)>.5
        samples.append(('walk',rows[len(rows)//2]))
    if label.startswith('SIT'):
        checks['seated_native_pose_and_stillness']=all(r['action']=='Sit' and r['planar_speed_mps']<.15 and
                       all(-.02<r['joints_m'][tag][2]<.25 for tag in ['LeftFoot','RightFoot']) for r in rows)
        samples.append(('sit',rows[len(rows)//2]))
    if label.startswith('NATIVE JOG'):
        checks['jog_has_sustained_fast_samples_and_flight']=len(fast)>=15 and len(flight)>=3
        samples.append(('jog',max(flight or rows,key=lambda r:r['speed_mps'])))
    if label.startswith('AGENT / cancelled'):
        checks['cancelled_actor_stays_stopped']=max(speeds)<.15

stamps=[json.loads(line) for line in (d/'video_timestamps.jsonl').open()]
out=d/'review_frames';out.mkdir(exist_ok=True);frame_refs=[]
for label,row in samples:
    stamp=min(stamps,key=lambda r:abs(r['sim_time']-row['sim_time']))
    output=out/(label+'.png')
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(d/'raw_video.mp4'),
                    '-vf',f"select=eq(n\\,{stamp['frame']})",'-frames:v','1',str(output)],check=True)
    frame_refs.append({'label':label,'file':str(output.relative_to(d)),'source_frame':stamp['frame'],
                       'sim_time':row['sim_time'],'wall_time':stamp['wall_time'],'actual_speed_mps':row['speed_mps'],
                       'actor_id':row['actor_id'],'asset_id':row['asset_id'],'joints_m':row['joints_m']})
control=json.loads((d/'demo_acceptance.json').read_text())
checks['actual_control_acceptance']=control.get('redirect_and_cancel_with_actual_settlement') is True
checks['geometry_flags_zero']=json.loads((d/'quality_audit.json').read_text())['critical_count']==0
result={'passed':all(checks.values()),'checks':checks,'shots':results,'review_frames':frame_refs,
        'scope':'Trajectory proxies and exact source frame references; human RGB review is complementary, not a force/mesh certificate.'}
(d/'demo_visual_audit.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='review_frames'},indent=2),flush=True)
if not result['passed']:raise SystemExit(1)
