"""Make labeled demonstrations from real retained renders; never synthesize poses."""
import argparse,hashlib,json,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'reports'
p=argparse.ArgumentParser();p.add_argument('--start-sim',type=float,default=3);p.add_argument('--duration',type=float,default=20);a=p.parse_args()
sources=[];filters=[];command=['ffmpeg','-v','error','-y']
for i,(run,label) in enumerate([('opt1031-motion-B-segmented-01','B - segmented reservations'),('opt1031-motion-CD-lazy-03','C - continuous reserved corridor')]):
 d=ROOT/'runs'/run;stamps=[json.loads(l) for l in (d/'video_timestamps.jsonl').open()]
 first=next(r['frame'] for r in stamps if r['sim_time']>=a.start_sim)
 last=next(r['frame'] for r in stamps if r['sim_time']>=a.start_sim+a.duration)
 path=d/'raw_video.mp4';command+=['-i',str(path)]
 filters.append(f"[{i}:v]trim=start_frame={first}:end_frame={last},setpts=PTS-STARTPTS,scale=960:540,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='{label}':fontsize=22:fontcolor=white:box=1:boxcolor=black@0.7:x=15:y=15,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:text='Simulation-time playback - actual throughput in report':fontsize=16:fontcolor=white:box=1:boxcolor=black@0.7:x=15:y=h-30[v{i}]")
 sources.append({'run_id':run,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'start_frame':first,'end_frame_exclusive':last,'start_sim_time':stamps[first]['sim_time'],'each_panel_continuous':True})
filters.append('[v0][v1]hstack=inputs=2[v]');comparison=out/'optimization_1031_motion_comparison.mp4'
command+=['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map','[v]','-an','-c:v','libx264','-preset','fast','-crf','20','-threads','4','-pix_fmt','yuv420p',str(comparison)]
subprocess.run(command,check=True)
seat=ROOT/'runs/opt1031-seat-calibrated-v3-12-02/raw_video.mp4';target=out/'optimization_1031_seat_lifecycle.mp4';shutil.copy2(seat,target)
files=[comparison,target,out/'optimization_1031_gait_demo.mp4',out/'optimization_1031_seat_comparison.mp4']
manifest={'motion_panels':sources,'seat_lifecycle':{'source':'runs/opt1031-seat-calibrated-v3-12-02/raw_video.mp4','unmodified_copy':hashlib.sha256(seat.read_bytes()).digest()==hashlib.sha256(target.read_bytes()).digest()},
 'limits':'simulation-time playback; static seat comparison uses stills; encoding FPS does not establish native runtime FPS',
 'files':[{'path':str(f.relative_to(ROOT)),'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in files]}
(out/'optimization_1031_assets/media_manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps(manifest,indent=2))
