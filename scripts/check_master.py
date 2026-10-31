"""Decode presentation timestamps; average FPS cannot hide a shifted middle PTS."""
import argparse,json,subprocess


def validate_times(times, fps, frames):
    errors=[]
    if len(times)!=frames:errors.append(f'frames {len(times)} != {frames}')
    for i,value in enumerate(times):
        if abs(value-i/fps)>2e-6:
            errors.append(f'PTS at frame {i}: {value} != {i/fps}');break
    return errors


def check(path,fps=30,frames=2700,size=(1920,1080)):
    stream=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
        'stream=width,height,avg_frame_rate,start_time,duration','-of','json',str(path)],capture_output=True,text=True,check=True).stdout)['streams'][0]
    probe=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries',
        'frame=best_effort_timestamp_time','-of','json',str(path)],capture_output=True,text=True,check=True)
    times=[float(x['best_effort_timestamp_time']) for x in json.loads(probe.stdout)['frames']]
    errors=validate_times(times,fps,frames)
    if (stream['width'],stream['height'])!=size:errors.append('incorrect dimensions')
    if abs(float(stream['duration'])-frames/fps)>1e-4:errors.append('incorrect duration')
    return {'path':str(path),'passed':not errors,'errors':errors,'decoded_frames':len(times),'stream':stream}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('path');p.add_argument('--fps',type=int,default=30);p.add_argument('--frames',type=int,default=2700)
    p.add_argument('--size',default='1920x1080');a=p.parse_args();r=check(a.path,a.fps,a.frames,tuple(map(int,a.size.split('x'))));print(json.dumps(r,ensure_ascii=False,indent=2));raise SystemExit(0 if r['passed'] else 1)
