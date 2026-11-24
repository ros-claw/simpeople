"""Local film masters, evidence-led handoff, without invented audience scores."""
import hashlib,importlib.util,json,shutil,subprocess,sys
from pathlib import Path
from PIL import Image,ImageDraw
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'productions/platform04_feature90_review'
def load(path):return json.loads(path.read_text())
def rows(path):return [json.loads(x) for x in path.read_text().splitlines()]
def save(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def cmd(args):subprocess.run(list(map(str,args)),check=True)
def module(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def masters():
 source=OUT/'media/Platform04_90s_Silent_Source.mp4';audio=OUT/'Original_Stereo_Soundtrack.wav';clean=OUT/'media/Platform04_90s_Clean_1080p30.mp4';main=OUT/'media/Platform04_90s_1080p30.mp4'
 grade='eq=contrast=1.035:brightness=0.005:saturation=0.90,fade=t=out:st=89.75:d=0.25'
 cmd(['ffmpeg','-y','-v','error','-i',source,'-i',audio,'-map','0:v','-map','1:a','-vf',grade,'-c:v','libx264','-threads','5','-crf','17','-pix_fmt','yuv420p','-c:a','aac','-b:a','256k','-t','90','-fps_mode','passthrough','-bsf:v','setts=pts=PTS:dts=DTS:duration=1/(30*TB)','-video_track_timescale','30000','-movflags','+faststart',clean])
 (OUT/'Platform04_zh.srt').write_text('1\n00:01:27,100 --> 00:01:29,650\n[站内广播] 请带好随身物品。\n',encoding='utf-8')
 subs='subtitles='+str(OUT/'Platform04_zh.srt')+":force_style='FontName=Noto Sans CJK SC,FontSize=24,Outline=1,Shadow=0,MarginV=32'"
 cmd(['ffmpeg','-y','-v','error','-i',clean,'-vf',subs,'-c:v','libx264','-threads','5','-crf','17','-pix_fmt','yuv420p','-c:a','copy','-fps_mode','passthrough','-bsf:v','setts=pts=PTS:dts=DTS:duration=1/(30*TB)','-video_track_timescale','30000','-movflags','+faststart',main])
def evidence():
 timeline=rows(OUT/'evidence/actual_frames.jsonl');mapping=load(OUT/'source_frame_map.json');roster={};runs=sorted(set(r for m in mapping for r in m['runs']));unfixed=[]
 for row in timeline:
  for aid,a in row['actors'].items():
   x=roster.setdefault(aid,{'first_story_s':row['feature_time_s'],'last_story_s':row['feature_time_s'],'max_instance_pixels':0,'behaviors':set()});x['last_story_s']=row['feature_time_s'];x['max_instance_pixels']=max(x['max_instance_pixels'],a.get('instance_pixels',0));x['behaviors'].add(a['behavior'])
 for aid,x in roster.items():x['behaviors']=sorted(x['behaviors']);x['coverage_scope']='actual instantiated actor; maximum visible leaf ID pixels where available, not recognizability'
 save(OUT/'evidence/actual_cast_24.json',roster)
 for rid in runs:
  src=ROOT/'runs'/rid;dst=OUT/'provenance'/rid;dst.mkdir(parents=True,exist_ok=True)
  for p in src.iterdir():
   if p.is_file() and p.suffix in ['.json','.jsonl','.txt','.py','.mp4']:shutil.copy2(p,dst/p.name)
  if (src/'source_snapshot').exists():shutil.copytree(src/'source_snapshot',dst/'source_snapshot',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
  qa=src/'static_probe_candidates.json'
  if qa.exists():unfixed.extend({'run':rid,**x} for x in load(qa)['candidates'])

 for rid in ['platform04-feature-after-geometry-02','platform04-feature-door-geometry-01','platform04-feature-gate-geometry-01']:
  src=ROOT/'runs'/rid;dst=OUT/'evidence'/rid;shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('*.so','__pycache__'))
 save(OUT/'evidence/static_probe_summary.json',{'candidates':unfixed,'limits':'selected keyframe actual vertices >8mm inside static boxes; not all-frame collision, triangle surface, self-collision, nonlinear CCD or PhysX'})
 audit=module(ROOT/'.runtime/platform04_90/kit/cast/audit_cast_motion.py','freeze');save(OUT/'evidence/cast_motion_review.json',audit.audit(rows(OUT/'evidence/actor_frames.jsonl'),30,expected=sorted(roster)))
 check=module(ROOT/'scripts/check_master.py','master');checks=[]
 for p in (OUT/'media').glob('*.mp4'):checks.append(check.check(p,frames=300 if 'D03_' in p.name else 2700))
 assert all(c['passed'] for c in checks),checks;save(OUT/'evidence/video_checks.json',checks)
 save(OUT/'DELIVERY.json',{'title':'四号站台 · 盲侧','date':'2026-11-03','seconds':90,'frames':2700,'resolution':[1920,1080],'fps':30,'actors_instantiated_across_film':len(roster),'runs':runs,'human_blind_reviewers':0,'audience_recognition_passed':None,'scariness_passed':None,'autonomous_infected_pursuit_claim':False,'source_reuse_s':13,'new_capture_s':77,'all_frame_timestamp_checks_passed':True,'static_probe_candidate_count':len(unfixed)})
 source=OUT/'source_current';shutil.copytree(ROOT/'src/simpeople',source/'src/simpeople',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'));(source/'scripts').mkdir(parents=True,exist_ok=True)
 for p in [*ROOT.glob('scripts/*platform04_feature*.py'),ROOT/'scripts/check_master.py']:shutil.copy2(p,source/'scripts'/p.name)
 shutil.copytree(ROOT/'tests',source/'tests',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
def pictures():
 media=OUT/'media/Platform04_90s_1080p30.mp4';folder=OUT/'gallery';folder.mkdir(exist_ok=True);sheet=Image.new('RGB',(1600,6*245),'#10191c');d=ImageDraw.Draw(sheet)
 for i,time in enumerate([1,5.5,8,10,13.5,16.5,19.5,22.3,26.5,29.7,34.5,38.7,43.5,49.5,53.5,56.5,58.7,60.0,65.8,70.5,77.5,81.5,87.8,89.2]):
  target=folder/f'{time:05.1f}s.jpg';cmd(['ffmpeg','-y','-v','error','-ss',str(time),'-i',media,'-frames:v','1','-q:v','2',target]);sheet.paste(Image.open(target).resize((400,225)),((i%4)*400,(i//4)*245));d.text(((i%4)*400+5,(i//4)*245+227),f'{time:04.1f}s',fill='white')
 sheet.save(OUT/'Contact_Sheet.jpg');shutil.copy2(folder/'058.7s.jpg',OUT/'Poster.jpg')
def report():
 pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'));c=canvas.Canvas(str(OUT/'90秒成片制作记录.pdf'),pagesize=(595,842));y=785
 def text(s,size=11):
  nonlocal y
  c.setFont('STSong-Light',size);line=''
  for ch in s:
   if line and pdfmetrics.stringWidth(line+ch,'STSong-Light',size)>495:c.drawString(50,y,line);y-=size*1.55;line=''
   line+=ch
  if line:c.drawString(50,y,line);y-=size*1.55
  y-=8
 def page(n):
  nonlocal y
  c.setFont('STSong-Light',9);c.drawString(50,25,f'四号站台 · 2026-11-03 · {n}/3 · 真人盲看0人');c.showPage();y=785
 d=load(OUT/'DELIVERY.json');text('《四号站台：盲侧》90秒成片',21);text('按用户本轮指示，继续完成90秒全片，不再把真人盲看作为开拍前置条件。影片为1920×1080、30帧/秒、2700个输出帧，分镜覆盖开场关系、异常群像、水瓶刺激、两波追逐、D03扑空、长椅威胁、跨门关网及肩带反转。')
 c.drawImage(str(OUT/'Poster.jpg'),50,y-265,width=495,height=265,preserveAspectRatio=True);y-=285
 text('逃者通过收步和重新选路保护自己；截击者在承诺后不再追着新位置改手，抓空后必须完成过冲和恢复。完整门口戏仍是同拍次的10秒连续源帧，没有在近失处切镜。')
 text('为接上后续长椅威胁，重新排了黄衣的门口后半程；她尚未提前进入绿门。青衣在前段先逃，后段折返示意；三人实际跨过门槛后，隔离网才关闭。末段用同伴自己的包带呼应开头的旧深色包。')
 text('主片有原创立体声拟音、克制的脉冲底乐和本地合成站内广播；只在广播处加一句中文字幕。另交无字幕版、未经调色的静音源合片与独立十秒长镜。')
 page(1);text('这次拍了什么，保留了什么',20)
 text('24名角色在不同镜头参演：3名生者、5名前景感染者、6名慢行者、6名猎手和4名环境角色。不是24套独立基础骨架，也不是每一帧同时出现24人。实际角色表与叶级实例像素覆盖另附。')
 text('保留9秒已选开场与4秒已选水瓶片段，共13秒；其余77秒在现有Isaac Sim 6.2.0-rc.14重新采集。所有段落按真实仿真状态1/30秒采集、停时预热相机，剪辑未倍速、插帧或重复短片填时长。source_frame_map.json逐段列出原片、源帧和哈希。')
 text('既有固定骨长、关节局部旋转和单一根驱动保持。普通行进仍沿路程推进Native Jog/Walk或慢尸源片相位；刹步、扑击、恢复及物件互动是手工编排，不把它写成新动捕或原生感染冲刺能力。')
 text('已处理：空机位拍不到第二拨猎手；黄衣绕行穿过旧长椅；低伏者后脚与新椅腿重叠；晚段追者横穿B3；逃者提前进通道；门口记录器在出画时省略支撑网格读回；青衣折返与两位同伴的身体擦穿。失败拍次和未选素材留存，新拍次没有覆盖旧片。')
 text('每个新拍次都有实际USD根、101骨关节、长骨长度、相机、RGB哈希和逐角色可见性。主片逐帧PTS/帧数/尺寸/时长检查通过；这些工程结果不等于动作自然或惊悚通过。静态几何只在所列关键帧测变形顶点与箱体代理，另对门口、接应和入门三个窗口，以10Hz读取实际变形表面复查幸存者相关的人物对；已选拍次未检出相交。完整几何范围及未解候选见evidence/。')
 text('声音基于实际踝点极小值或事先标注的鞋底支撑时刻；它们是拟音时序代理，不是麦克风、声学仿真或接触力。车内脚步低通过滤，冲出车门后变清；只落一只瓶、关一次网。')
 page(2);text('成片已交，主观验收仍诚实留空',20)
 text('真人盲看0人，未生成观众答案，未声称达到4/5身份识别、自然度或惊悚评分。上一轮匿名单人身份审片包仍保留，可独立用于定位“快尸像不像感染者”，不以全片配乐替它打分。')
 text('本片为电影编排。既有普通Jog追逐的原生验收结果保持独立；本轮未新增多人自主猎群、原生感染冲刺或本剧情Agent/MCP端到端验收。没有用导演预设路线证明自主追猎。')
 text('仍有制作限制：部分衣装会遮住肩肘细节，表情及口型绑定有限；普通步态、转弯和拥挤背景的所有支撑窗未逐一足锁；没有全身自碰撞、全时段连续碰撞或真实扶椅/撞网受力求解。未把拍到画面当作这些能力通过。')
 text('逐角色工具保留17段候选，未检出同相片段；多发生在延后起跑、喘息、啃带和扶网的保持段，不能自动改判通过。其中A04两段很慢的根移动仍缺少足够身体运动，作为未修的背景小问题留档。逐段说明见cast_candidate_dispositions.json，真人复核仍待进行。')
 text('复拍：使用每次run的source_snapshot与现有角色缓存，运行scripts/platform04_feature_shoot.py --run-id 新名称 --part chew/odd/reaction/burst/pursuit/approach/door/after/gate/twist --gpu 2。完整分段及实际源帧见source_frame_map.json；使用Isaac 6.2安装的python.sh，不用别的版本替代验收。')
 text('交付只保存在本地，未上传、发布或推送远端。旧R1/R2母版和归档保持不变。')
 text('合成广播采用本机eSpeak NG cmn，原创短句，不模仿真人或运营商录音。接口依据：',10);text('https://github.com/espeak-ng/espeak-ng/blob/master/src/include/espeak-ng/speak_lib.h',8)
 page(3);c.save()
def entry():
 (OUT/'START_HERE.html').write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>四号站台 · 盲侧</title><style>body{background:#0d1518;color:#e7eae5;max-width:1152px;margin:36px auto;padding:0 20px;font:18px/1.7 system-ui}a{color:#d9ba7a}video,img{width:100%}small{color:#a7bab7}details{margin-top:32px;padding:20px;background:#172326}</style><p><small>ROSClaw SimPeople · 原创仿真短片 · 90秒</small></p><h1>四号站台：盲侧</h1><p>末班车之后，最危险的声音来自身边。</p><video controls preload="metadata" poster="Poster.jpg" src="media/Platform04_90s_1080p30.mp4"></video><p><a download href="media/Platform04_90s_1080p30.mp4">下载主片</a> · <a href="media/Platform04_90s_Clean_1080p30.mp4">无字幕版</a> · <a href="media/Platform04_90s_Silent_Source.mp4">静音源合片</a> · <a href="media/D03_10s_Uncut.mp4">门口十秒连续镜头</a></p><details><summary>制作记录与原始证据</summary><p><a href="90秒成片制作记录.pdf">三页制作记录</a> · <a href="source_frame_map.json">逐段源帧</a> · <a href="DELIVERY.json">交付清单</a></p><p>24名角色分镜参演；13秒沿用已选素材，77秒新拍。角色动作与追逃为电影编排。真人盲看目前0人；没有把视频完成写成自主追猎或惊悚验收通过。</p></details><p><img loading="lazy" src="Contact_Sheet.jpg" alt="全片镜头采样联系表"></p></html>''',encoding='utf-8')
def main():masters();evidence();pictures();report();entry();print('90-second feature masters and local handoff complete')
if __name__=='__main__':main()
