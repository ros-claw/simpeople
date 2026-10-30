"""Make traceable, wall-clock 1x demonstration clips from closed raw recordings."""
import argparse
import bisect
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from export_wall_video import export

def duration(path):
    result=subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(path)],text=True)
    return float(json.loads(result)['format']['duration'])

def clip(directory,start,length,label,out):
    stamps=[json.loads(line) for line in (directory/'video_timestamps.jsonl').open()]
    wall=[s['wall_time']-stamps[0]['wall_time'] for s in stamps]
    lo=bisect.bisect_left(wall,start);hi=bisect.bisect_left(wall,start+length)
    if hi-lo<2:raise ValueError('clip contains fewer than two actual frames')
    caption=out.with_suffix('.txt')
    caption.write_text(label+' | wall-clock 1x | '+directory.name)
    # Text is read from a file, never interpreted as filter syntax or shell code.
    # Fast input seeking on this remuxed VFR stream selected the wrong source
    # interval. Decode from the beginning and select measured frame IDs instead.
    video_filter=f"trim=start_frame={lo}:end_frame={hi},setpts=PTS-STARTPTS,drawbox=x=0:y=0:w=iw:h=56:color=black@0.75:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:textfile='{caption}':fontsize=24:fontcolor=white:x=18:y=16"
    # B-frame composition offsets caused drift when VFR shots were joined.
    # Demo derivatives use P frames; original encoded evidence is unchanged.
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(directory/'raw_video_wallclock.mp4'),
                    '-an','-vf',video_filter,'-frames:v',str(hi-lo),'-fps_mode','passthrough','-enc_time_base','1/90000','-c:v','libx264','-threads','2',
                    '-preset','fast','-crf','20','-bf','0','-video_track_timescale','90000','-movflags','+faststart',str(out)],check=True)
    probe=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_frames',
                  '-show_entries','frame=best_effort_timestamp_time','-of','json',str(out)],text=True)
    actual=[float(x['best_effort_timestamp_time']) for x in json.loads(probe)['frames']]
    expected=[x-wall[lo] for x in wall[lo:hi]]
    if len(actual)!=len(expected):raise ValueError('edited clip dropped or duplicated source frames')
    error=max(abs(x-y) for x,y in zip(actual,expected))
    if error>3/90000:raise ValueError(f'edited clip changed wall timing: {error}s')
    return {'duration_s':duration(out),'source_first_frame':lo,'source_end_frame_exclusive':hi,
            'source_first_wall_offset_s':wall[lo],'source_last_wall_offset_s':wall[hi-1],
            'frames':hi-lo,'max_decoded_timestamp_error_s':error}

def prepare(directory):
    if not (directory/'completion.json').exists():raise ValueError('run is still active')
    if not (directory/'raw_video_wallclock.mp4').exists():export(directory)
    return json.loads((directory/'video_timestamps.jsonl').open().readline())['wall_time']

def population(directory):
    first=prepare(directory)
    acceptance=json.loads((directory/'demo_acceptance.json').read_text())
    if acceptance.get('error') or not acceptance.get('redirect_and_cancel_with_actual_settlement'):
        raise ValueError('population demonstration did not complete')
    sections=json.loads((directory/'demo_bookmarks.json').read_text())['sections']
    work=directory/'demo_segments';work.mkdir(exist_ok=True)
    manifest=[]
    for i,section in enumerate(sections):
        start=section['start_wall_time']-first
        length=section['end_wall_time']-section['start_wall_time']
        out=work/f'segment_{i:02d}.mp4'
        actual=clip(directory,start,length,section['label']+((' / '+section['actor_id']) if section['actor_id'] else ''),out)
        manifest.append({**section,'source_start_wall_offset_s':start,'requested_clip_seconds':length,
                         'encoded_clip_seconds':actual['duration_s'],'frame_audit':actual,'file':str(out.relative_to(directory))})
    concat=work/'concat.txt'
    concat.write_text(''.join("file '"+Path(x['file']).name+"'\nduration "+str(x['frame_audit']['duration_s'])+'\n' for x in manifest))
    out=directory/'demo.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','1','-i',str(concat),
                    '-c','copy','-movflags','+faststart',str(out)],check=True)
    actual=duration(out)
    if not 90<=actual<=150:raise ValueError(f'demonstration length {actual} outside 90–150s')
    result={'run_id':directory.name,'output':out.name,'duration_s':actual,'sections':manifest,
            'timing':'Selected measured wall-clock intervals at 1x; no interpolation or speed-up. Cuts are explicit.',
            'full_source':'raw_video_wallclock.mp4','simulation_time_source':'raw_video.mp4'}
    (directory/'demo_manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    return {k:v for k,v in result.items() if k!='sections'}

def single(directory):
    first=prepare(directory)
    checks=json.loads((directory/'event_control_acceptance.json').read_text())
    if not checks or not all(v is True for v in checks.values()):raise ValueError('single-person checks failed')
    calls=[json.loads(line) for line in (directory/'event_control_calls.jsonl').open()]
    start=max(0,calls[0]['wall_time']-first-1)
    end=calls[-1]['wall_time']-first+5
    out=directory/'single_continuous_demo.mp4'
    actual=clip(directory,start,end-start,'CONTINUOUS / walk jog stop sit stand / events redirect cancel',out)
    result={'run_id':directory.name,'output':out.name,'duration_s':actual['duration_s'],'frame_audit':actual,
            'source_start_wall_offset_s':start,'source_end_wall_offset_s':end,
            'timing':'One continuous wall-clock 1x interval; no internal cuts, interpolation or speed-up.',
            'full_source':'raw_video_wallclock.mp4','checks':'event_control_acceptance.json'}
    (directory/'single_demo_manifest.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--population-run');p.add_argument('--single-run');a=p.parse_args()
    if a.single_run:print(json.dumps(single(ROOT/'runs'/a.single_run),indent=2),flush=True)
    if a.population_run:print(json.dumps(population(ROOT/'runs'/a.population_run),indent=2),flush=True)
