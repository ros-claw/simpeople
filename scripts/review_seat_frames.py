"""Extract actual held side views using recorded camera-change wall timestamps."""
import argparse,bisect,json,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args();d=Path(a.directory)
stamps=[json.loads(x) for x in (d/'video_timestamps.jsonl').read_text().splitlines()];times=[s['wall_time'] for s in stamps]
changes=[x for x in (json.loads(y) for y in (d/'seat_calls.jsonl').read_text().splitlines()) if x['method']=='record' and x['params'].get('view')=='seat_side']
out=d/'review_frames';out.mkdir(exist_ok=True);seen={};index=[]
for i,change in enumerate(changes):
 aid=change['params']['actor_id'];seen[aid]=seen.get(aid,0)+1
 if seen[aid]!=(2 if aid.endswith('_00') else 1):continue
 next_wall=changes[i+1]['wall_time'] if i+1<len(changes) else change['wall_time']+1
 wall=(change['wall_time']+next_wall)/2;ix=min(len(stamps)-1,bisect.bisect_left(times,wall));frame=stamps[ix]['frame']
 name=aid+'.png';subprocess.run(['ffmpeg','-v','error','-y','-ss',str(frame/30),'-i',str(d/'raw_video.mp4'),'-frames:v','1',str(out/name)],check=True)
 index.append({'actor_id':aid,'frame':frame,'sim_time':stamps[ix]['sim_time'],'image':name,'camera_window_wall':[change['wall_time'],next_wall]})
(out/'index.json').write_text(json.dumps(index,indent=2));print('extracted',len(index),'actual side views')
