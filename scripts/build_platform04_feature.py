"""Assemble 2700 source frames at their authored clock; never stretch takes."""
import argparse,hashlib,importlib.util,json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'productions/platform04_feature90_review'
TAKES={'odd':'01','reaction':'01','burst':'01','pursuit':'02','approach':'01','door':'03','after':'02','gate':'02','twist':'01'}
BOUNDS={'odd':(9,21),'reaction':(25,28),'burst':(28,33),'pursuit':(33,46),'approach':(46,53),'door':(53,63),'after':(63,77),'gate':(77,84),'twist':(84,90)}
def rows(path):return [json.loads(x) for x in path.read_text().splitlines()]
def save(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def run(args):subprocess.run(list(map(str,args)),check=True)
def sources():
    clips=[{'start':0,'end':9,'file':ROOT/'productions/platform04_directors_review/01_Opening_9s.mp4','first':0,'rows':ROOT/'productions/platform04_directors_review/evidence/01_Opening_9s/frames.jsonl','actors':ROOT/'productions/platform04_directors_review/evidence/01_Opening_9s/actor_frames.jsonl','runs':['platform04-90-opening-03','platform04-90-opening-listen-04'],'note':'preserved selected opening, first210 + corrected60 source frames'},
      {'start':21,'end':25,'file':ROOT/'runs/platform04-r2-bottle-06/raw_video.mp4','first':0,'rows':ROOT/'runs/platform04-r2-bottle-06/frames.jsonl','actors':ROOT/'runs/platform04-r2-bottle-06/actor_frames.jsonl','runs':['platform04-r2-bottle-06'],'note':'first120 original frames; one bottle release'}]
    for part,version in TAKES.items():
        rid=f'platform04-feature-{part}-final-{version}';folder=ROOT/'runs'/rid;c=json.loads((folder/'completed.json').read_text());assert not c['preview'];lo,hi=BOUNDS[part];assert c['frames']==round((hi-lo)*30),(rid,c)
        clips.append({'start':12 if part=='odd' else lo,'end':hi,'file':folder/'raw_video.mp4','first':90 if part=='odd' else 0,'rows':folder/'frames.jsonl','actors':folder/'actor_frames.jsonl','runs':[rid],'note':'new feature capture; positive 1/30 simulation steps, zero-time camera warmup excluded'})
    chew=ROOT/'runs/platform04-feature-chew-final-01';assert json.loads((chew/'completed.json').read_text())['frames']==90
    clips.append({'start':9,'end':12,'file':chew/'raw_video.mp4','first':0,'rows':chew/'frames.jsonl','actors':chew/'actor_frames.jsonl','runs':['platform04-feature-chew-final-01'],'note':'lower eyeline insert reveals mouth, hand, taut strap and old bag'})
    return sorted(clips,key=lambda x:x['start'])
def assemble():
    clips=sources();assert [c['start'] for c in clips]==[0,9,12,21,25,28,33,46,53,63,77,84]
    OUT.mkdir(exist_ok=False);(OUT/'cuts').mkdir();(OUT/'evidence').mkdir();(OUT/'media').mkdir();mapping=[];allrows=[];allactors=[];files=[]
    for c in clips:
        lo=round(c['start']*30);hi=round(c['end']*30);target=OUT/'cuts'/f'{lo:04d}_{hi:04d}.mp4';count=hi-lo
        run(['ffmpeg','-y','-v','error','-i',c['file'],'-vf',f'trim=start_frame={c["first"]}:end_frame={c["first"]+count},setpts=N/(30*TB)','-an','-c:v','libx264','-threads','4','-crf','17','-pix_fmt','yuv420p','-fps_mode','passthrough','-bsf:v','setts=pts=PTS:dts=DTS:duration=1/(30*TB)','-video_track_timescale','30000','-movflags','+faststart',target]);files.append(target)
        rr=rows(c['rows']);assert len(rr)>=count
        for i,r in enumerate(rr[c['first']:c['first']+count]):
            r['feature_frame']=lo+i;r['feature_time_s']=(lo+i)/30;r['feature_source_runs']=c['runs'];allrows.append(r)
        for r in rows(c['actors']):
            if c['first']<=r['f']<c['first']+count:r['f']=lo+r['f']-c['first'];allactors.append(r)
        mapping.append({'feature_frames_half_open':[lo,hi],'source_movie':str(c['file'].relative_to(ROOT)),'source_frames_half_open':[c['first'],c['first']+count],'runs':c['runs'],'retiming':'none; each decoded source frame gets its authored i/30 presentation time','note':c['note'],'source_sha256':hashlib.sha256(c['file'].read_bytes()).hexdigest()})
    assert [r['feature_frame'] for r in allrows]==list(range(2700))
    with (OUT/'evidence/actual_frames.jsonl').open('w') as f:
        for row in allrows:f.write(json.dumps(row)+'\n')
    with (OUT/'evidence/actor_frames.jsonl').open('w') as f:
        for row in allactors:f.write(json.dumps(row)+'\n')
    save(OUT/'source_frame_map.json',mapping);(OUT/'cuts/concat.txt').write_text(''.join("file '"+p.name+"'\n" for p in files));run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',OUT/'cuts/concat.txt','-map','0:v','-c','copy','-movflags','+faststart',OUT/'media/Platform04_90s_Silent_Source.mp4'])
    # Keep the self-contained, uninterrupted ten-second source alongside film.
    shutil.copy2(OUT/'cuts/1590_1890.mp4',OUT/'media/D03_10s_Uncut.mp4')
    save(OUT/'evidence/source_coverage.json',{'decoded_source_frames':len(allrows),'feature_clock':'0..2699 inclusive at30Hz','unique_story_actor_ids':sorted(set().union(*(set(r['actors']) for r in allrows))),'reuse_seconds':13,'new_capture_seconds':77,'human_reviewers':0,'scope':'authored cinematic performances, not native autonomous pursuit'})
    print('Source movie and actual timeline assembled',flush=True)
if __name__=='__main__':assemble()
