"""Review media and isolated blind panels. No generated spectator responses."""
import argparse,hashlib,importlib.util,json,shutil,subprocess,sys
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'productions/platform04_r2_review'
ROLE_TAKES={
 'H_fast_side':'platform04-r2-human-fast-side-06','H_fast_front':'platform04-r2-human-fast-front-06',
 'Z_fast_side':'platform04-r2-infected-fast-side-03','Z_fast_front':'platform04-r2-infected-fast-front-03',
 'H_slow_side':'platform04-r2-human-slow-side-02','H_slow_front':'platform04-r2-human-slow-front-02',
 'Z_slow_side':'platform04-r2-infected-slow-side-02','Z_slow_front':'platform04-r2-infected-slow-front-02',
 'H_body2':'platform04-r2-body2-human-fast-03','Z_body2':'platform04-r2-body2-infected-fast-01',
 'H_injured':'platform04-r2-human-injured-01'}
def load_module(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def rows(p):return [json.loads(l) for l in p.read_text().splitlines()]
def save(p,data):p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def cmd(args):subprocess.run(list(map(str,args)),check=True,stdout=subprocess.DEVNULL)
def clean_copy(source,target):
 cmd(['ffmpeg','-y','-v','error','-i',source,'-map','0:v:0','-c:v','copy','-an','-map_metadata','-1','-metadata','title=','-metadata','comment=','-bsf:v','setts=pts=PTS:dts=DTS:duration=1/(30*TB)','-video_track_timescale','30000','-movflags','+faststart',target])
def original(rid):
 run=ROOT/'runs'/rid;closed=json.loads((run/'completed.json').read_text());assert not closed['preview'];return run/'raw_video.mp4'
def trace_movie(rid,target):
 data=rows(ROOT/'runs'/rid/'frames.jsonl');width,height=1280,720;low=np.array([2.,-3.5]);high=np.array([35.5,10.5]);scale=min((width-80)/(high[0]-low[0]),(height-80)/(high[1]-low[1]));origin=np.array([40,680])
 def pixel(p):return tuple((origin+(np.array(p[:2])-low)*[scale,-scale]).astype(int))
 def rect(draw,lo,hi,fill):
  a=pixel([lo[0],hi[1]]);b=pixel([hi[0],lo[1]]);draw.rectangle([a,b],fill=fill)
 base=Image.new('RGB',(width,height),'#182126');d=ImageDraw.Draw(base);rect(d,[2,0],[35.5,8.65],'#394348');rect(d,[2,-3.14],[35.5,-.25],'#29343a');rect(d,[25,8.65],[31,10.5],'#394348')
 for x in [5,14,23,32]:
  rect(d,[x-1.1,-.35],[x+1.1,.15],'#465158')
 for x,y in [(3.8,4.25),(10.5,7.1),(18,7.1),(26,4.4),(34.8,4.25)]:rect(d,[x-.34,y-.34],[x+.34,y+.34],'#142026')
 encoder=subprocess.Popen(['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','1280x720','-r','30','-i','-','-an','-c:v','libx264','-threads','3','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],stdin=subprocess.PIPE)
 for r in data:
  im=base.copy();draw=ImageDraw.Draw(im)
  for aid in ['H01','F02']:
   a=r['actors'][aid];m=np.array(a['actual_root_matrix']);p=m[3,:3];yaw=np.arctan2(m[0,1],m[0,0]);x,y=pixel(p);radius=9;draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill='#e1e6e6');forward=np.array([np.cos(yaw),np.sin(yaw)]);center=np.array([x,y]);tip=center+forward*[radius,-radius];draw.line([tuple(center),tuple(tip)],fill='#182126',width=3)
  encoder.stdin.write(im.tobytes())
 encoder.stdin.close();assert encoder.wait()==0;save(target.with_suffix('.source.json'),{'run':rid,'frames':len(data),'positions':'actual USD root matrix readback','marks':'identical circles + same-size direction notch, no IDs/colors/trails','movie':'2D diagnostic from actual rendered take telemetry, not Isaac RGB'})
def panels():
 tool=ROOT/'.runtime/platform04_r2/kit/Platform04_R2/blind.py';private=OUT/'private';private.mkdir(exist_ok=True);public=OUT/'blind_panels';public.mkdir(exist_ok=True)
 groups={}
 for angle in ['side','front']:
  groups['role_'+angle]=[{'id':name+'_'+angle,'type':'role','media':'../media/roles/'+name+'_'+angle+'.mp4','truth':'human' if name[0]=='H' else 'infected'} for name in ['H_fast','Z_fast','H_slow','Z_slow']]
  groups['role_'+angle].append({'id':'H_injured','type':'role','media':'../media/roles/H_injured.mp4','truth':'human'})
 opening=['能指出近处角色要跟随等待的同伴','能从画面指出目标是发绿光的站务通道','能描述等待或招手后角色继续靠近的关系']
 bottle=['能指出瓶落地与角色注意改变的先后','能分别描述生者放弃捡瓶照顾同伴、另一人松带朝落点移动','能描述旧包留下或对帮助不回应、抓空/继续搜寻的后果']
 chase=['能指出门内角色主动截击站台逃跑者','能说出逃者先收步改道、追者仍扑先前位置','能描述扑空后两步恢复而逃者继续离开']
 parallel=['能描述两人同向持续移动','未把没有发生的截击/改道说成画面事实','能说明没有相互改变路线、未发生扑空恢复']
 groups['cause_main']=[{'id':'Opening_R1_preserved','type':'cause','media':'../media/Opening_Preserved_9s.mp4','rubric':opening},{'id':'Bottle_R2','type':'cause','media':'../media/Bottle_Reactions_12s.mp4','rubric':bottle},{'id':'D03_R2_trio','type':'cause','media':'../media/D03_ThreeActors_10s.mp4','rubric':chase}]
 groups['cause_isolation']=[{'id':'D03_R2_duo','type':'cause','media':'../media/D03_TwoActors_10s.mp4','rubric':chase},{'id':'Parallel_negative','type':'cause','media':'../media/Parallel_Control_10s.mp4','rubric':parallel}]
 groups['cause_roots']=[{'id':'Root_interception','type':'cause','media':'../media/Roots_Interception_10s.mp4','rubric':chase},{'id':'Root_parallel','type':'cause','media':'../media/Roots_Parallel_10s.mp4','rubric':parallel}]
 for group,trials in groups.items():
  spec=private/(group+'.spec.json');save(spec,{'trials':trials});keys=[]
  for i in range(1,6):
   reviewer=f'{group}_{i:02d}';folder=public/group/reviewer;key=private/(reviewer+'.key.json');cmd([sys.executable,tool,'pack','--spec',spec,'--out',folder,'--reviewer',reviewer,'--seed','R2-20261103-'+group,'--key-out',key]);keys.append(key)
  cmd([sys.executable,tool,'score','--keys',*keys,'--out',private/(group+'.pending_scores.json')])
 save(OUT/'screening_status.json',{'real_reviewers':0,'real_responses':0,'status':'pending, not failed or passed','prepared_groups':list(groups),'packets_per_group':5,'identity_gate':'Each core H_fast / Z_fast / H_slow / Z_slow independently >=4/5 correct; unsure/missing retained. Do not average slow clips over fast failures.','assignment_policy':'role_side is the primary 5-viewer set; role_front is an alternative/new group. Never show both angles of a take to the same first-time viewer. Cause_main needs fresh viewers, cause_isolation / cause_roots are optional independent diagnostic groups. Prepared packets are not actual reviewers.','keys':'private/ must never be sent with reviewer folders'})
def main():
 OUT.mkdir(exist_ok=False);(OUT/'media/roles').mkdir(parents=True);(OUT/'evidence').mkdir();(OUT/'gallery').mkdir()
 mapping={}
 for name,rid in ROLE_TAKES.items():
  target=OUT/'media/roles'/f'{name}.mp4';clean_copy(original(rid),target);mapping[str(target.relative_to(OUT))]={'run':rid,'source_frames':[0,149],'retiming':'none'}
 for name,rid in [('D03_TwoActors_10s','platform04-r2-duo-06'),('D03_ThreeActors_10s','platform04-r2-trio-06'),('Parallel_Control_10s','platform04-r2-parallel-01'),('Bottle_Reactions_12s','platform04-r2-bottle-06'),('R1_CameraOnly_Diagnostic_10s','platform04-r2-camera-only-01')]:
  target=OUT/'media'/f'{name}.mp4';clean_copy(original(rid),target);mapping[str(target.relative_to(OUT))]={'run':rid,'source_frames':[0,359 if 'Bottle' in name else 299],'retiming':'none','note':'camera-only clip is the first composition diagnostic, not the selected R2 camera' if 'CameraOnly' in name else ''}
 clean_copy(ROOT/'productions/platform04_directors_review/01_Opening_9s.mp4',OUT/'media/Opening_Preserved_9s.mp4');clean_copy(ROOT/'productions/platform04_directors_review/Native_Jog_RealTime_7s.mp4',OUT/'media/Native_Jog_Original_7s.mp4')
 trace_movie('platform04-r2-duo-06',OUT/'media/Roots_Interception_10s.mp4');trace_movie('platform04-r2-parallel-01',OUT/'media/Roots_Parallel_10s.mp4');save(OUT/'source_frame_map.json',mapping)
 checker=load_module(ROOT/'scripts/check_master.py','check');checks=[]
 for path in sorted((OUT/'media').rglob('*.mp4')):
  n=150 if path.parent.name=='roles' else 360 if 'Bottle' in path.name else 270 if 'Opening' in path.name else 210 if 'Original_7' in path.name else 300;checks.append(checker.check(path,frames=n,size=(1280,720) if 'Roots_' in path.name else (1920,1080)))
 save(OUT/'video_checks.json',checks);assert all(r['passed'] for r in checks),checks
 panels();print('R2 review media, blind packets and zero-response score files created')
if __name__=='__main__':main()
