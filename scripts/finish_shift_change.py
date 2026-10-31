"""Local 90-second deliverables from a validated native take; no frame synthesis."""
import argparse,csv,hashlib,json,math,shutil,subprocess,wave
from fractions import Fraction
from pathlib import Path
import numpy as np
from analyze_shift_change import analyze
from check_master import check

ROOT=Path(__file__).resolve().parents[1]


def timestamp(t,ass=False):
    h=int(t//3600);m=int(t//60)%60;s=t%60
    return f'{h}:{m:02d}:{s:05.2f}' if ass else f'{h:02d}:{m:02d}:{int(s):02d},{round((s-int(s))*1000):03d}'


def audio(d,frames,out):
    rate=48000;n=90*rate;t=np.arange(n,dtype=np.float32)/rate;rng=np.random.default_rng(1031)
    factory=.003*np.sin(2*np.pi*60*t)+.0015*np.sin(2*np.pi*120*t)+rng.normal(0,.0007,n).astype(np.float32)
    music=np.zeros(n,dtype=np.float32)
    chords=[(146.832,174.614,220),(116.541,146.832,174.614),(130.813,174.614,220),(130.813,164.814,195.998)]
    for k in range(12):
        start=k*8;stop=min(90,start+9)
        if start>=90:break
        a=int(start*rate);b=int(stop*rate);q=t[a:b]-start
        envelope=np.minimum(1,q/.9)*np.minimum(1,(stop-start-q)/1.5)
        for f in chords[k%4]:music[a:b]+=.0065*envelope*(np.sin(2*np.pi*f*q)+.18*np.sin(2*np.pi*f*2*q))
    # Duck the original ambient score while the actual user instruction is shown.
    music[(t>=43.5)&(t<53)]*=.45
    samples=factory+music;last={};recent={};foot_events=[]
    by_sample={r['journal_sample']:r for r in frames}
    for line in (d/'trajectories.jsonl').open():
        row=json.loads(line);identity=row.get('frame_identity',{});frame=identity.get('video_frame')
        if frame is None or identity.get('sample') not in by_sample or row.get('planar_speed_mps',0)<.3:continue
        current=by_sample[identity['sample']];aid=row['actor_id']
        for foot in ['LeftFoot','RightFoot']:
            point=row.get('joints_m',{}).get(foot)
            if not point:continue
            key=(aid,foot);history=recent.setdefault(key,[]);history.append((frame,point))
            if len(history)>3:history.pop(0)
            if len(history)<3:continue
            a0,mid,a2=history
            if mid[1][2]>min(a0[1][2],a2[1][2]) or mid[1][2]>.13 or frame-last.get(key,-100)<7:continue
            dist=math.dist(current['eye_m'],mid[1]);gain=.085/(1+.16*dist*dist)
            if gain<.001:continue
            last[key]=frame;at=mid[0]/30;offset=int(at*rate);length=min(int(.075*rate),n-offset)
            if length<=0:continue
            q=np.arange(length)/rate;noise=rng.normal(0,1,length)
            noise=np.convolve(noise,np.ones(7)/7,mode='same')
            thump=np.sin(2*np.pi*(95+rng.uniform(-12,12))*q)*np.exp(-q*65)
            samples[offset:offset+length]+=gain*(noise*.7*np.exp(-q*70)+thump)
            foot_events.append({'actor_id':aid,'foot':foot,'film_time_s':at,'gain':gain})
    samples*=np.minimum(1,t/1.5)*np.minimum(1,(90-t)/2)
    gain=min(.07/max(float(np.sqrt(np.mean(samples*samples))),1e-8),.8/max(float(np.max(np.abs(samples))),1e-8))
    samples*=gain
    samples=np.clip(samples,-.92,.92)
    with wave.open(str(out),'wb') as f:
        f.setnchannels(2);f.setsampwidth(2);f.setframerate(rate)
        mono=(samples*32767).astype('<i2');stereo=np.column_stack([mono,mono]).tobytes();f.writeframes(stereo)
    return {'method':'original procedural ambient score; trajectory-estimated foreground footstep Foley; not simulated acoustic contacts',
            'sample_rate':rate,'mix_gain':gain,'rms_dbfs':20*math.log10(float(np.sqrt(np.mean(samples*samples)))),
            'peak':float(np.max(np.abs(samples))),'estimated_footsteps':foot_events}


def run(cmd):
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-n',*cmd],check=True)


def repair_final_packet_duration(path, fps):
    """CFR concat may omit the last packet duration. Preserve every AVC packet."""
    import sys
    sys.path.insert(0,str(ROOT/'.runtime/video_deps'))
    import av
    temp=path.with_name(path.stem+'_duration_fixed.mp4')
    assert not temp.exists()
    originals=[];timebase=Fraction(1,30000)
    with av.open(str(path)) as source,av.open(str(temp),'w',options={'movflags':'+faststart'}) as target:
        streams={s.index:target.add_stream_from_template(s) for s in source.streams}
        for s in source.streams:
            if s.type=='video':streams[s.index].time_base=timebase
        for packet in source.demux():
            if packet.pts is None:continue
            stream=packet.stream
            if stream.type=='video':
                originals.append(hashlib.sha256(bytes(packet)).hexdigest())
                packet.pts=round(packet.pts*packet.time_base/timebase)
                packet.dts=round(packet.dts*packet.time_base/timebase)
                packet.duration=round(Fraction(1,fps)/timebase);packet.time_base=timebase
            packet.stream=streams[stream.index];target.mux(packet)
    with av.open(str(temp)) as verify:
        actual=[hashlib.sha256(bytes(p)).hexdigest() for p in verify.demux(video=0) if p.pts is not None]
    assert actual==originals,'stream-copy repair changed encoded video packets'
    assert check(temp,frames=900)['passed']
    backup=ROOT/'.runtime/shift_change'/path.name.replace('.mp4','_missing_final_duration.mp4')
    assert not backup.exists();path.rename(backup);temp.rename(path)
    return {'encoded_video_packets_unchanged':True,'frames':len(actual),'method':'stream-copy remux; assign missing CFR packet duration, no added or removed frames'}


def finish(run_id,resume=False):
    d=ROOT/'runs'/run_id;validation=analyze(d)
    assert validation['passed'] and validation['mode']=='master',validation
    out=ROOT/'productions/shift_change';out.mkdir(parents=True,exist_ok=True)
    raw=d/'raw_video.mp4';frames=[json.loads(x) for x in (d/'cinematic_frames.jsonl').open()]
    stem='SimPeople_ShiftChange';master=out/(stem+'_90s_1080p30.mp4');clean=out/(stem+'_90s_Clean_1080p30.mp4')
    assert resume or (not master.exists() and not clean.exists()),'preserve existing delivered masters; use --resume only for this same take'
    protected={}
    if resume:
        assert (out/'source_frame_map.csv').read_bytes()==(d/'source_frame_map.csv').read_bytes(),'resume source take changed'
        for name in [stem+'_Original_Soundtrack.wav',stem+'_zh-CN.srt',stem+'_zh-CN.ass']:
            path=out/name
            if path.exists():protected[path]=hashlib.sha256(path.read_bytes()).hexdigest()
    wav=out/(stem+'_Original_Soundtrack.wav');sound=audio(d,frames,wav)
    arrival=max(validation['native_arrival_film_s'].values())
    captions=[(0,4,'换班时刻'),(4,8,'早班开始，工作、巡视与休息同时进行。'),(10,15,'巡视员沿通道前行。'),
              (22,31,'走近，转身，落座。'),(34,38,'慢跑经过，走位继续。'),
              (44,51,'把橙衣巡视员派到东侧 B1 复检位，把蓝衣巡视员派到 B2。\n长椅旁那位继续等，其他人照常。'),
              (51,59,'两人改派。长椅旁的等候者保持原任务。'),(max(68,arrival+.1),79,'B1、B2：已到达并停稳。'),
              (80,85,'大厅仍在运转。')]
    srt=out/(stem+'_zh-CN.srt');srt.write_text('\n\n'.join(f'{i}\n{timestamp(a)} --> {timestamp(b)}\n{text}' for i,(a,b,text) in enumerate(captions,1))+'\n')
    ass=out/(stem+'_zh-CN.ass')
    head='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Noto Sans CJK SC,34,&H00F7F5EF,&H000000FF,&H00201812,&H90000000,0,0,0,0,100,100,0,0,1,2,1,8,70,70,45,1
Style: Credit,Noto Sans CJK SC,58,&H00F7F5EF,&H000000FF,&H00201812,&H90000000,1,0,0,0,100,100,0,0,1,2,1,5,70,70,10,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    lines=[]
    for a,b,text in captions:
        text=text.replace('\n',r'\N')
        if a==44:text=r'{\fs26\c&H8CC8F2&}真实 Codex 指令{\r}\N'+text
        lines.append(f'Dialogue: 0,{timestamp(a,True)},{timestamp(b,True)},Caption,,0,0,0,,{text}')
    # Identity labels use actual camera/root records. They add no animation or
    # invented success state; the uncaptioned clean version remains available.
    for row in frames[44*30:68*30]:
        eye=np.array(row['eye_m']);forward=np.array(row['look_at_m'])-eye;forward/=np.linalg.norm(forward)
        right=np.cross(forward,[0,0,1]);right/=np.linalg.norm(right);up=np.cross(right,forward)
        labels=[('bench_waiter','等候者 · 原任务保持','EBEBEB')]
        if row['frame']<54*30:labels += [('patrol_orange','橙衣 → B1','46A7FF'),('patrol_blue','蓝衣 → B2','F7AE70')]
        for aid,label,color in labels:
            point=np.array(row['actors'][aid]['position_m'])+np.array([0,0,1.95])-eye;depth=point@forward
            if depth<=0:continue
            x=(1+2*row['focal_mm']*(point@right)/(36*depth))*960
            y=(1-2*row['focal_mm']*(point@up)/(20.25*depth))*540
            if not 70<x<1850 or not 180<y<1020:continue
            a=row['frame']/30;b=(row['frame']+1)/30
            text=r'{\an2\pos('+str(round(x))+','+str(round(y))+r')\fs23\c&H'+color+'&}'+label
            lines.append(f'Dialogue: 2,{timestamp(a,True)},{timestamp(b,True)},Caption,,0,0,0,,{text}')
    lines.append(r'Dialogue: 1,0:01:26.00,0:01:30.00,Credit,,0,0,0,,{\fs68}ROSClaw SimPeople\N{\fs32}Agent-controlled people and activities for Isaac Sim.\N{\fs34}github.com/ros-claw/simpeople\N{\fs22}原生仿真逐帧采集 · 仿真时间回放')
    ass.write_text(head+'\n'.join(lines)+'\n')
    assert all(hashlib.sha256(p.read_bytes()).hexdigest()==digest for p,digest in protected.items()),'assembly inputs changed; preserve prior outputs'
    if not clean.exists():run(['-i',str(raw),'-i',str(wav),'-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',str(clean)])
    if not master.exists():run(['-i',str(raw),'-i',str(wav),'-vf','ass='+str(ass),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','slow','-crf','18',
         '-threads','4','-pix_fmt','yuv420p','-fps_mode','passthrough','-c:a','aac','-b:a','192k','-movflags','+faststart',str(master)])
    core=out/(stem+'_Continuous_Agent_Take_24s.mp4')
    if not core.exists():run(['-ss','44','-i',str(raw),'-frames:v','720','-an','-c:v','libx264','-crf','18','-preset','fast','-threads','4','-fps_mode','passthrough','-movflags','+faststart',str(core)])
    trailer=out/(stem+'_Trailer_30s_1080p30.mp4');ranges=[(0,4),(10,14),(24,28),(34,38),(44,50),(68,72),(86,90)]
    filters=[];inputs=[]
    for i,(a,b) in enumerate(ranges):
        filters.extend([f'[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]',f'[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.06,afade=t=out:st={b-a-.06}:d=0.06[a{i}]'])
        inputs.extend([f'[v{i}]',f'[a{i}]'])
    filters.append(''.join(inputs)+f'concat=n={len(ranges)}:v=1:a=1[v][a]')
    if not trailer.exists():run(['-i',str(master),'-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-c:v','libx264','-crf','19','-preset','fast','-threads','4','-fps_mode','passthrough','-c:a','aac','-movflags','+faststart',str(trailer)])
    trailer_check=check(trailer,frames=900);duration_repair=None
    if trailer_check['errors']==['incorrect duration']:duration_repair=repair_final_packet_duration(trailer,30)
    shutil.copy2(d/'source_frame_map.csv',out/'source_frame_map.csv')
    shutil.copy2(d/'cinematic_validation.json',out/'native_validation.json')
    checks=[check(master),check(clean),check(core,frames=720),check(trailer,frames=900)]
    assert all(c['passed'] for c in checks),checks
    decoded=subprocess.run(['ffmpeg','-v','error','-i',str(raw),'-map','0:v:0','-fps_mode','passthrough','-f','framemd5','-'],capture_output=True,text=True,check=True)
    hashes=[line.rsplit(',',1)[1].strip() for line in decoded.stdout.splitlines() if line and not line.startswith('#')]
    duplicate_count=sum(a==b for a,b in zip(hashes,hashes[1:]));assert len(hashes)==2700 and duplicate_count==0,'inspect duplicate decoded source frames'
    files=[master,clean,core,trailer,srt,ass,wav,out/'source_frame_map.csv',out/'native_validation.json']
    manifest={'run_id':run_id,'capture':'actual native simulation frames at 1/30 s; no interpolation or repeated output frames',
              'real_agent_wall_wait_s':validation['applied']['wall_wait_s'],'clock_disclosure':'simulation is paused during real Codex thinking; wall latency is preserved in native logs, not presented as real-time model response',
              'source_video_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'adjacent_duplicate_decoded_source_frames':duplicate_count,'checks':checks,'sound':sound,'trailer_packet_duration_repair':duration_repair,
              'assembly_source_sha256':{name:hashlib.sha256((ROOT/'scripts'/name).read_bytes()).hexdigest() for name in ['finish_shift_change.py','analyze_shift_change.py','check_master.py']},
              'trailer_source_ranges_s':ranges,'files':[{'path':str(f.relative_to(ROOT)),'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in files]}
    (out/'delivery_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps({'out':str(out),'validated_videos':len(checks),'frames':[c['decoded_frames'] for c in checks]},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--resume',action='store_true');a=p.parse_args();finish(a.run_id,a.resume)
