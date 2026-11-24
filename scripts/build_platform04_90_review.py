"""Assemble the four review pieces, with frame provenance and candid gates."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,shutil,subprocess,sys
import numpy as np
from PIL import Image,ImageOps,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'productions/platform04_directors_review'
def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def run(argv):subprocess.run(list(map(str,argv)),check=True,stdout=subprocess.DEVNULL)
def rows(path):return [json.loads(l) for l in path.read_text().splitlines()]
def save(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def encode(args,target):
    run(['ffmpeg','-y','-v','error','-threads','4',*args,'-c:v','libx264','-threads','4','-crf','18','-preset','fast','-pix_fmt','yuv420p','-an','-fps_mode','passthrough','-bsf:v','setts=pts=PTS:dts=DTS:duration=1/(30*TB)','-video_track_timescale','30000','-movflags','+faststart',target])
def piece(name,segments):
    inputs=[];filters=[];mapping=[];full=[];actors=[];offset=0
    for i,(rid,lo,hi) in enumerate(segments):
        folder=ROOT/'runs'/rid;complete=json.loads((folder/'completed.json').read_text());assert not complete['preview'];source_first=complete['source_ticks'][0]
        inputs+=['-i',folder/'raw_video.mp4'];filters.append(f'[{i}:v]trim=start_frame={lo-source_first}:end_frame={hi-source_first},setpts=PTS-STARTPTS[v{i}]')
        frame_rows={r['source_tick']:r for r in rows(folder/'frames.jsonl')}
        for f in range(lo,hi):
            row=frame_rows[f].copy();row['output_frame']=offset+f-lo;row['source_run']=rid;full.append(row)
            mapping.append({'output_frame':offset+f-lo,'source_run':rid,'source_tick':f,'source_rgb_sha256':row['rgb_sha256'],'shot':row['shot']})
        for r in rows(folder/'actor_frames.jsonl'):
            source_tick=r['f']+source_first
            if lo<=source_tick<hi:
                r=r.copy();r['f']=offset+source_tick-lo;r['shot']=r['shot'].split(':')[-1];actors.append(r)
        offset+=hi-lo
    filters.append(''.join(f'[v{i}]' for i in range(len(segments)))+f'concat=n={len(segments)}:v=1:a=0[out]')
    target=OUT/f'{name}.mp4';encode([*inputs,'-filter_complex',';'.join(filters),'-map','[out]'],target)
    evidence=OUT/'evidence'/name;evidence.mkdir(parents=True,exist_ok=True)
    for file,data in [('master_frame_map.jsonl',mapping),('frames.jsonl',full),('actor_frames.jsonl',actors)]:
        (evidence/file).write_text(''.join(json.dumps(r)+'\n' for r in data))
    audit=module(ROOT/'.runtime/platform04_90/kit/cast/audit_cast_motion.py','cast_audit');result=audit.audit(actors,30,expected=sorted({r['id'] for r in actors}));save(evidence/'freeze_review.json',result)
    save(evidence/'assembly.json',{'source_segments_half_open':segments,'frames':offset,'retiming':'none; one selected real source frame per output frame','actor_qa':'actual leaf ID visibility / same-camera isolated deformed silhouette; candidate list, not performance acceptance'})
    print(name,'frames',offset,'suspects',result['suspect_segments'],'unjudged',result['expected_present_but_never_judged'],flush=True)
    return full,actors
def gray(name):encode(['-i',OUT/f'{name}.mp4','-vf','hue=s=0'],OUT/f'{name}_Gray.mp4')
def poses(name,frames,actors):
    source_names=json.loads((ROOT/'runs/platform04-motion-01/rig.json').read_text())['joints'];leaf={n.rsplit('/',1)[-1]:i for i,n in enumerate(source_names)}
    short='hips chest neck head lshoulder lelbow lwrist rshoulder relbow rwrist lhip lknee lankle ltoe rhip rknee rankle rtoe'.split();long='Hip Spine02 NeckTwist01 Head L_Upperarm L_Forearm L_Hand R_Upperarm R_Forearm R_Hand L_Thigh L_Calf L_Foot L_ToeBase R_Thigh R_Calf R_Foot R_ToeBase'.split();vis={(r['f'],r['id']):r for r in actors};data=[]
    for row in frames:
        for aid,a in row['actors'].items():
            r=vis[row['output_frame'],aid];p=np.array(a['actual_world_joints_m']);mat=np.array(a['actual_root_matrix']);yaw=np.radians(r['yaw_deg']);eligible=r['box_px']>=48 and r['mask_px']>=120 and r['visible_fraction']>=.35
            data.append({'frame':row['output_frame'],'t_s':row['output_frame']/30,'actor_id':aid,'shot':row['shot'],'phase':a.get('action',a.get('gait','performance')),'visibility':'visible' if eligible else 'not_eligible','root_m':r['root_m'],'yaw_rad':float(yaw),'joints':{s:p[leaf[l]].tolist() for s,l in zip(short,long)}})
    audit=module(ROOT/'.runtime/platform04_90/kit/motion/pose_audit.py','pose_audit');e=OUT/'evidence'/name;save(e/'pose_features.json',audit.analyse({'coordinates':'world_m_Z_up','frames':data}));save(e/'pose_adapter.json',{'joint_map':dict(zip(short,long)),'visibility':'actual silhouette visibility eligibility; per-joint visibility not asserted by this pose summary','stance':'no externally annotated fixed sole vertices; shoe slip not certified here','rest_reference':'none in this feature summary; actual long-bone ranges supplied separately'})
def contacts():
    picks=[('01_Opening_9s',[0,3.8,5.5,7.5]),('03_Characters_12s',[.6,3.8,7.3,10.8]),('04_Door_Uncut_10s',[1.2,4.4,5.5,6.3])];canvas=Image.new('RGB',(1280,3*215),'#121719');draw=ImageDraw.Draw(canvas)
    for row,(name,times) in enumerate(picks):
        for col,t in enumerate(times):
            tmp=OUT/'gallery'/f'{name}_{t}.jpg';run(['ffmpeg','-y','-v','error','-ss',t,'-i',OUT/f'{name}.mp4','-frames:v','1',tmp]);im=Image.open(tmp).resize((320,180));canvas.paste(im,(col*320,row*215));draw.text((col*320+5,row*215+185),f'{name} +{t:.1f}s',fill='white')
    canvas.save(OUT/'Contact_Sheet.jpg')
def audition(rid):
    folder=ROOT/'runs'/rid;completed=json.loads((folder/'completed.json').read_text());assert completed['frames']==1440
    inputs=[];filters=[];names=['Native Jog','SDK Sprint','Old leg IK','Old pinned arm','SDK + gaze','Healthy final']
    for i in range(12):
        path=folder/('raw_video.mp4' if i==0 else f'raw_video_{i:03d}.mp4');inputs+=['-i',path];filters.append(f'[{i}:v]scale=640:360,pad=640:540:0:90:color=0x111619,drawtext=text=\'{names[i%6]}\':fontcolor=white:fontsize=24:x=20:y=30[v{i}]')
    for a in range(2):filters.append(''.join(f'[v{i}]' for i in range(a*6,a*6+6))+f'xstack=inputs=6:layout=0_0|640_0|1280_0|0_540|640_540|1280_540[g{a}]')
    filters.append('[g0][g1]concat=n=2:v=1:a=0[out]');encode([*inputs,'-filter_complex_threads','2','-filter_complex',';'.join(filters),'-map','[out]'],OUT/'02_Run_Layers_8s.mp4')
    dst=OUT/'run_layers';dst.mkdir(exist_ok=True)
    for i in range(12):shutil.copy2(folder/('raw_video.mp4' if i==0 else f'raw_video_{i:03d}.mp4'),dst/f'{"Side" if i<6 else "Front45"}_{i%6+1:02d}.mp4')
    shutil.copy2(ROOT/'runs/platform04-90-jog-02/raw_video.mp4',OUT/'Native_Jog_RealTime_7s.mp4')
    save(dst/'README.json',{'order':names,'comparison':'same actor, camera, root distance, normalized phase; Sprint source explicitly time-normalized to Jog phase for SHAPE comparison, not native speed evidence','native_reference':'Native_Jog_RealTime_7s.mp4 is actual original 30Hz Native task capture, unretimed','final_healthy':'Native Jog-based; no infection overlay; not a new Native sprint capability'})
def main():
    p=argparse.ArgumentParser();p.add_argument('--door-run',required=True);p.add_argument('--audition-run',default='platform04-90-audition-04');p.add_argument('--slow-run',default='platform04-90-character-slow-08');a=p.parse_args();OUT.mkdir(exist_ok=True);(OUT/'evidence').mkdir(exist_ok=True);(OUT/'gallery').mkdir(exist_ok=True)
    items=[('01_Opening_9s',[('platform04-90-opening-03',0,210),('platform04-90-opening-listen-04',210,270)]),('03_Characters_12s',[('platform04-90-character-04',270,540),(a.slow_run,540,630)]),('04_Door_Uncut_10s',[(a.door_run,1590,1890)])]
    for name,segments in items:
        frames,actors=piece(name,segments);poses(name,frames,actors)
        if name!='04_Door_Uncut_10s':gray(name)
    audition(a.audition_run);contacts()
    checker=module(ROOT/'scripts/check_master.py','master_check');checks=[]
    for name,n in [('01_Opening_9s',270),('01_Opening_9s_Gray',270),('02_Run_Layers_8s',240),('03_Characters_12s',360),('03_Characters_12s_Gray',360),('04_Door_Uncut_10s',300),('Native_Jog_RealTime_7s',210)]:checks.append(checker.check(OUT/f'{name}.mp4',frames=n))
    save(OUT/'video_checks.json',checks);assert all(r['passed'] for r in checks),checks
if __name__=='__main__':main()
