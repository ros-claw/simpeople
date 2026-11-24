"""Local-only edit, original synthesized sound, subtitles and source-frame photo."""
import argparse,json,hashlib,subprocess,wave,sys,shutil,time
from pathlib import Path
import numpy as np
from scipy import signal
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from check_master import check
from finish_shift_change import COLOR_FILTER,COLOR_ARGS


def run(args):
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-filter_threads','4','-filter_complex_threads','4','-n',*map(str,args)],check=True)


def normalize_packet_duration(path,frames):
    """Repair concat's zero final packet duration, without changing video data.

    Only accept an already complete, evenly timestamped frame sequence. Keep
    PTS and DTS explicitly: setts's combined TS default would reorder B frames.
    """
    before=check(path,30,frames,(1920,1080))
    if before['passed']:return None
    if before['errors']!=['incorrect duration']:raise ValueError(before)
    def packet_hashes(file):
        p=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_packets','-show_data_hash','sha256','-show_entries','packet=data_hash','-of','json',str(file)],capture_output=True,text=True,check=True)
        return [x['data_hash'] for x in json.loads(p.stdout)['packets']]
    tmp=path.with_name(path.stem+'.clockfix.mp4')
    run(['-i',path,'-map','0','-c','copy','-bsf:v','setts=pts=PTS:dts=DTS:duration=1/(30*TB)','-video_track_timescale','30000','-movflags','+faststart',tmp])
    after=check(tmp,30,frames,(1920,1080))
    unchanged=packet_hashes(path)==packet_hashes(tmp)
    if not after['passed'] or not unchanged:raise ValueError('clock repair changed frames or failed validation')
    backup=ROOT/'.runtime/deadweight'/('packet_duration_backup_'+str(time.time_ns()));backup.mkdir(parents=True)
    shutil.move(str(path),backup/path.name);tmp.rename(path)
    return {'file':path.name,'compressed_video_packets_unchanged':True,'frames':frames,'old_duration_s':before['stream']['duration'],'new_duration_s':after['stream']['duration']}


def soundtrack(path,photo_time):
    rate=48000;n=88*rate;t=np.arange(n)/rate;rng=np.random.default_rng(881103)
    noise=rng.normal(size=n)
    wind=signal.sosfilt(signal.butter(2,[80,1800],btype='bandpass',fs=rate,output='sos'),noise)*.035
    sound=wind*(.7+.3*np.sin(t*.21))
    drone=sum(np.sin(2*np.pi*f*t+.25*np.sin(t*.27)) for f in [55,82.4069,110])/3
    sound+=drone*.038*(.4+.6*np.sin(t*.055)**2)
    # Original D-minor suspense phrase, followed by a warmer F/A/C resolution.
    for beat in np.arange(14,83,.75):
        melody=[146.8324,174.6141,220.,261.6256] if beat<49 else [174.6141,220.,261.6256,293.6648]
        freq=melody[int((beat-14)/.75)%4];start=int(beat*rate);length=int(1.3*rate);u=np.arange(length)/rate
        note=(np.sin(2*np.pi*freq*u)+.2*np.sin(4*np.pi*freq*u))*(1-np.exp(-u*30))*np.exp(-u*3)
        level=.018 if beat<49 else .027;sound[start:start+length]+=note*level
    def impact(at,level=.12,pitch=70,length=.23):
        start=int(at*rate);m=min(int(length*rate),n-start)
        if start<0 or m<=0:return
        u=np.arange(m)/rate
        grain=signal.sosfilt(signal.butter(2,900,fs=rate,output='sos'),rng.normal(size=m))
        sound[start:start+m]+=level*(.7*np.sin(2*np.pi*pitch*u*np.exp(-u*1.8))+.3*grain)*np.exp(-u*22)
    for at in np.arange(14.1,17,.48):impact(at,.07,95)
    for at in np.arange(18.8,27,.5833333):impact(at,.10,64)
    for at in np.arange(30,35,.45):impact(at,.07,110)
    for at in np.arange(49,83,.31):impact(at,.045,46,.16)
    # Wheels, storm, door locks and a shutter. All original generated effects.
    movement=np.maximum(0,np.sin(np.pi*np.clip((t-49)/34,0,1)))
    sound+=signal.sosfilt(signal.butter(2,[35,240],btype='bandpass',fs=rate,output='sos'),noise)*movement*.07
    for at in [48.25,48.9,49.05,83.3]:impact(at,.19,110,.3)
    sound*=1-.65*np.exp(-((t-photo_time)/.6)**2)
    impact(photo_time,.27,900,.09);impact(photo_time+.12,.14,160,.14)
    for at in [3.2,23.8,50.2]:
        start=int(at*rate);m=min(2*rate,n-start);u=np.arange(m)/rate
        thunder=signal.sosfilt(signal.butter(2,150,fs=rate,output='sos'),rng.normal(size=m))
        sound[start:start+m]+=thunder*.3*np.exp(-u*1.8)
    sound*=np.minimum(1,t/1.2)*np.minimum(1,(88-t)/1.4)
    sound=np.tanh(sound*1.9)*.85
    stereo=np.column_stack([sound,np.roll(sound,57)*.96]);pcm=np.clip(stereo*32767,-32768,32767).astype('<i2')
    with wave.open(str(path),'wb') as out:out.setnchannels(2);out.setsampwidth(2);out.setframerate(rate);out.writeframes(pcm.tobytes())


SUBTITLES=[(0,3.2,'海崖铁路，风暴封站。'),(6,9.5,'下站，最后十二个人已经进车。'),(10,13.7,'补水管断了。上面太轻。'),(14,17.5,'刚才，他们还在拍照。'),(27,30,'那扇维护门，本来可以让她离开。'),(31,35,'“各位游客，请跟我上车。”'),(42.5,46.7,'他们没有走散。\n他们成了配重。'),(49.3,53,'一车死人下去。'),(53.5,57.5,'一车活人上来。'),(61,63,'她想竖起拇指。'),(63.2,65.2,'可手套，只有一整片翅膀。'),(75,78,'救援还没有结束。'),(82.7,85.8,'只开乘务格侧门。')]


def stamp(value,ass=False):
    h=int(value//3600);m=int(value//60)%60;s=value%60
    return f'{h}:{m:02d}:{s:05.2f}' if ass else f'{h:02d}:{m:02d}:{int(s):02d},{round((s-int(s))*1000):03d}'


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--out',type=Path,default=ROOT/'productions/deadweight');a=p.parse_args()
    source=ROOT/'runs'/a.run_id;result=json.loads((source/'completed.json').read_text())
    if result['frames']!=2640 or result['infected']!=23 or len(result['boarded_ids'])!=24 or result['departure_s'] is None:raise ValueError('unfinished full production run')
    raw=source/'raw_video.mp4';validation=check(raw,30,2640,(1920,1080))
    if not validation['passed']:raise ValueError(validation)
    out=a.out;out.mkdir(parents=True,exist_ok=True)
    photo_frame=round((result['departure_s']+17)*30);photo_time=photo_frame/30
    photo=out/'DEADWEIGHT_Meeting_SourceFrame.png'
    if not photo.exists():run(['-i',raw,'-vf',f'select=eq(n\\,{photo_frame}),{COLOR_FILTER}','-frames:v',1,photo])
    wav=out/'DEADWEIGHT_Original_Sound.wav'
    if not wav.exists():soundtrack(wav,photo_time)
    srt=out/'DEADWEIGHT_zh-CN.srt'
    srt.write_text('\n\n'.join(f'{i}\n{stamp(start)} --> {stamp(end)}\n{text}' for i,(start,end,text) in enumerate(SUBTITLES,1))+'\n',encoding='utf-8')
    ass=out/'DEADWEIGHT_zh-CN.ass'
    header='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Noto Sans CJK SC,43,&H00F3EFE7,&H000000FF,&H00251D18,&H80000000,0,0,0,0,100,100,1,0,1,2,1,2,120,120,65,1
Style: Title,Noto Sans CJK SC,82,&H00F3EFE7,&H000000FF,&H00251D18,&H80000000,1,0,0,0,100,100,7,0,1,2,1,8,120,120,50,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    lines=[f'Dialogue: 0,{stamp(start,True)},{stamp(end,True)},Default,,0,0,0,,{{\\fad(120,120)}}'+text.replace('\n','\\N') for start,end,text in SUBTITLES]
    lines.append('Dialogue: 1,0:01:26.00,0:01:28.00,Title,,0,0,0,,死重  /  DEADWEIGHT')
    lines.append('Dialogue: 1,0:01:26.00,0:01:28.00,Default,,0,0,0,,ROSClaw SimPeople · Isaac Sim')
    ass.write_text(header+'\n'.join(lines)+'\n',encoding='utf-8')
    # Exactly 2,580 moving source frames + 60 declared source-photo freeze frames.
    edit=f'[0:v]split=2[m][p];[m]trim=end_frame=2580,setpts=PTS-STARTPTS[moving];[p]trim=start_frame={photo_frame}:end_frame={photo_frame+1},loop=loop=59:size=1:start=0,setpts=N/(30*TB)[still];[moving][still]concat=n=2:v=1:a=0,{COLOR_FILTER}[edited]'
    clean=out/'DEADWEIGHT_88s_1080p30_Clean.mp4';master=out/'DEADWEIGHT_88s_1080p30_CN.mp4'
    enc=['-c:v','libx264','-preset','medium','-crf','18','-threads','4','-pix_fmt','yuv420p','-fps_mode','passthrough',*COLOR_ARGS,'-c:a','aac','-b:a','192k','-movflags','+faststart']
    if not clean.exists():run(['-i',raw,'-i',wav,'-filter_complex',edit,'-map','[edited]','-map','1:a:0','-af','loudnorm=I=-18:TP=-1.5:LRA=10','-ar','48000',*enc,clean])
    if not master.exists():run(['-i',clean,'-vf','ass='+str(ass)+':fontsdir=/usr/share/fonts/opentype/noto','-c:v','libx264','-crf','18','-preset','medium','-threads','4','-fps_mode','passthrough',*COLOR_ARGS,'-c:a','copy','-movflags','+faststart',master])
    clips=[('01_ZombieGait_4s.mp4',19,120),('02_HeroineBoarding_4s.mp4',31,120),('03_WindowPassing_4s.mp4',photo_time-2,120),('Infection_Continuous_13s.mp4',14,390),('Meeting_Continuous_15s.mp4',59,450)]
    for name,start,frames in clips:
        target=out/name
        if not target.exists():run(['-ss',str(start),'-i',clean,'-frames:v',str(frames),'-an','-c:v','libx264','-preset','fast','-crf','18','-threads','4','-fps_mode','passthrough',*COLOR_ARGS,target])
    ranges=[(14,22),(31,36),(43,52),(63,69),(86,88)];filters=[];parts=[]
    for i,(start,end) in enumerate(ranges):
        filters.extend([f'[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]',f'[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]']);parts.append(f'[v{i}][a{i}]')
    filters.append(''.join(parts)+'concat=n=5:v=1:a=1[v][a]');trailer=out/'DEADWEIGHT_30s_Teaser.mp4'
    if not trailer.exists():run(['-i',master,'-filter_complex',';'.join(filters),'-map','[v]','-map','[a]',*enc,trailer])
    repairs=[x for path,frames in [(master,2640),(clean,2640),(trailer,900)] if (x:=normalize_packet_duration(path,frames))]
    if repairs:(out/'CLOCK_NORMALIZATION.json').write_text(json.dumps(repairs,indent=2)+'\n')
    validations=[check(master,30,2640,(1920,1080)),check(clean,30,2640,(1920,1080)),check(trailer,30,900,(1920,1080))]
    manifest={'source_run':a.run_id,'scope':result['scope'],'source_photo_frame':photo_frame,'source_photo_story_time_s':photo_time,'edit':{'moving_source_frames':[0,2579],'intentional_photo_freeze_frames':[2580,2639],'freeze_source_frame':photo_frame},'raw_validation':validation,'exports':validations,'production_result':result,'color_conversion':COLOR_FILTER,'audio':'Original procedural score/effects; no third-party music.','files':{x.name:{'bytes':x.stat().st_size,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()} for x in out.iterdir() if x.suffix in ['.mp4','.png','.srt','.ass','.wav']}}
    (out/'DELIVERY.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    if not all(v['passed'] for v in validations):raise ValueError('export validation failed')
    print(json.dumps({'master':str(master),'photo_source_frame':photo_frame,'checks_passed':True},ensure_ascii=False))


if __name__=='__main__':main()
