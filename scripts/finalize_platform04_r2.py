"""Evidence-led local handoff for R2. Human recognition remains pending."""
import hashlib,importlib.util,json,shutil,subprocess,sys
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'productions/platform04_r2_review'
spec=importlib.util.spec_from_file_location('assembly',ROOT/'scripts/build_platform04_r2_review.py');assembly=importlib.util.module_from_spec(spec);spec.loader.exec_module(assembly)
def read(p):return json.loads(p.read_text())
def rows(p):return [json.loads(l) for l in p.read_text().splitlines()]
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def copy_evidence(rid):
 src=ROOT/'runs'/rid;dst=OUT/'provenance'/rid;dst.mkdir(parents=True,exist_ok=True)
 for p in src.iterdir():
  if p.is_file() and p.suffix in ['.json','.jsonl','.txt','.py']:shutil.copy2(p,dst/p.name)
 shutil.copytree(src/'source_snapshot',dst/'source_snapshot',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 if (src/'raw_video.mp4').exists():shutil.copy2(src/'raw_video.mp4',dst/'raw_video.mp4')
def contact_sheet():
 picks=[('platform04-r2-trio-06',[135,145,170,180,195,225]),('platform04-r2-bottle-06',[0,40,65,90,150,195]),('platform04-r2-human-fast-side-06',[0,30,45,60,90,120]),('platform04-r2-infected-fast-side-03',[0,30,45,75,90,120])];sheet=Image.new('RGB',(1800,len(picks)*190),'#10181b');draw=ImageDraw.Draw(sheet)
 for row,(rid,frames) in enumerate(picks):
  for col,f in enumerate(frames):
   p=ROOT/'runs'/rid/f'frame_{f:04d}.png'
   if not p.exists():continue
   im=Image.open(p).resize((300,169));sheet.paste(im,(col*300,row*190));draw.text((col*300+4,row*190+171),rid.replace('platform04-r2-','')+f' +{f/30:.2f}s',fill='white')
 sheet.save(OUT/'Contact_Sheet.jpg')
def pdf_report():
 pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'));c=canvas.Canvas(str(OUT/'第二轮表演优化报告.pdf'),pagesize=(595,842));c.setTitle('四号站台：第二轮表演返修');y=785
 def text(s,size=11):
  nonlocal y
  c.setFont('STSong-Light',size);line='';width=0.
  for char in s:
   w=pdfmetrics.stringWidth(char,'STSong-Light',size)
   if line and width+w>495:c.drawString(50,y,line);y-=size*1.55;line='';width=0.
   line+=char;width+=w
  if line:c.drawString(50,y,line);y-=size*1.55
  y-=7
 def pic(path,w=495,h=250):
  nonlocal y
  c.drawImage(str(path),50,y-h,width=w,height=h,preserveAspectRatio=True,anchor='c');y-=h+14
 def page(n):
  nonlocal y
  c.setFont('STSong-Light',9);c.drawString(50,25,f'2026-11-03 · R2 · {n}/4 · 真人盲审 0 人，识别率待审');c.showPage();y=785
 text('先修两个人演的是谁',21)
 text('本轮交付：同模同灰衣的快/慢四类单人试演（侧视与前侧45°各5秒）、另一套正式身材的两类快态、受伤活人压力对照；D03双人/三人各10秒；一只水瓶的两种反应12秒；真实根轨迹与同向赶路负对照。90秒、24人版本仍未制作。')
 pic(ROOT/'runs/platform04-r2-trio-06/frame_0180.png')
 text('黄衣：看见门内威胁后收步、支撑、斜切，随后放开手臂继续逃。红衣：提前抢门、肩先加载、抓一个已经锁定的旧位置；黄衣切走后不更新手部目标，胸与脚继续过冲，分两次补步找回平衡。白衣延后进入视觉中心，柱旁搜索仍属电影编排。')
 text('先前“修好骨架”没有解决身份。本轮保留局部旋转、正式骨长和单一根控制；改掉三人几乎全用健康Jog、低速完整长步慢放，以及扑击手部追着目标当帧位置走的逻辑。局部骨长稳定、无几何穿透不等于人物能被认出。')
 text('新增退片原因：刹步支撑点仍会偏移、掌心朝上的对称姿势像闲聊、机位被26号柱挡住、逃跑路穿B3、鞋底未考虑凸起盲道。失败和不选拍次完整留在本地。')
 page(1);text('把身体身份与快慢分开测试',21)
 metrics=read(OUT/'evidence/identity_motion.json')
 for label,key in [('健康快态','H_fast_side'),('感染快态','Z_fast_side'),('健康慢态','H_slow_side'),('感染慢态','Z_slow_side')]:
  r=metrics[key];text(f'{label}：实际根平均速度 {r["mean_speed_mps"]:.3f} m/s，5秒连续150帧；支撑窗最大鞋底水平漂移 '+('未作独立支撑标注。' if r['plant_drift_m'] is None else f'{r["plant_drift_m"]*1000:.2f} mm。'))
 text('快态平均速度差为 '+f'{metrics["fast_mean_speed_relative_difference"]*100:.2f}%'+ '。没有将两个身份硬锁同一步相；各自保留启动、停顿、扑击与恢复的时间分配。角色题不带包、动作名、字幕、声音或片名，主测试同一正式演员与同一中性衣装。前侧视角与另一身材单独留档，不用它们重复训练同一个首次观众。')
 text('原速的边界：所有成片按编排的1/30秒状态直接采集，未后期倍速或插帧。稳态腿部仍沿路程推进Native Jog相位，不能称为原始动作库恒1×播放；原生Jog未重定时7秒参考另附。刹步、扑击和恢复改为手工关键姿、短步和独立足底目标，不再把长Jog周期拖慢当制动。')
 text('素材核查：本地UAL2_Standard.glb与给定哈希一致，确有43条动画；Zombie名称仅Idle、Walk、Scratch三条。感染慢态使用既有SDK实测的101骨慢尸缓存；没有把慢尸快放冒充感染冲刺。本轮未采购商业库、未获得新真人动捕，快态攻击短句为原创关键姿。')
 pic(ROOT/'runs/platform04-r2-infected-fast-front-03/frame_0090.png',495,220)
 page(2);text('先把因果和落脚拍出来',21)
 geo=read(ROOT/'runs/platform04-r2-geometry-02/geometry_qa.json');qa=read(ROOT/'runs/platform04-r2-trio-06/performance_qa.json');prop=read(OUT/'evidence/bottle_prop_qa.json')
 text(f'D03：同拍次300个连续源帧、没有切镜。扑击目标的实际日志范围为{qa["committed_target_range_m"]}米，即承诺后不再吸附黄衣的新位置。两人的方向在扑击时分开；新增固定鞋底顶点与事先声明的支撑时间窗，全片标注窗内最大水平漂移 {qa["worst_xy_plant_drift_m"]*1000:.2f} mm；未标注的普通跑步支撑不被写成通过。')
 text(f'三位前景人物：整段30Hz、4.3–7.7秒120Hz，共{geo["samples"]}次实际变形网格读回。人物表面相交记录{len(geo["sampled_triangle_intersections"])}项，静态箱体代理深于3毫米入侵{len(geo["static_box_intrusions_deeper_than_3mm"])}项；线性扫掠接触{len(geo["linear_sweep_contacts"])}项，未解共面候选{geo["unresolved_coplanar_pairs"]}项。独立几何回放与最终三人镜头300帧实际关节坐标最大差0。未测全身自碰撞，也未宣称PhysX接触或连续非线性CCD。')
 visibility=read(OUT/'evidence/critical_visibility.json');text('关键4.5–6.83秒：黄衣孤立轮廓可见率最低 '+f'{visibility["H01"]["minimum_visible_fraction"]*100:.1f}%'+ '，红衣最低 '+f'{visibility["F02"]["minimum_visible_fraction"]*100:.1f}%'+ '。分母来自同相机的实际变形三角网格。白衣这段主要在镜外，列为未判；延后入画是一项调度选择，不能冒充其感染表演已获识别。')
 text(f'水瓶：全片实际事件日志只释放{prop["bottle_release_events"]}次。青衣放弃捡回，转向同伴；啃带者停嘴、松带、离开旧包朝声源走。旧包脱离人物根驱动后，实际USD世界中心漂移 {prop["actual_old_bag_world_drift_after_f100_m"]:.2g} m。瓶子重力/滚动为编排轨迹，不称物理碰撞；本轮没有扩拍扶环者和六人传播链。')
 pic(ROOT/'runs/platform04-r2-bottle-06/frame_0075.png',495,205)
 page(3);text('看片放行与工程检查各留一栏',21)
 text('真人盲审仍为0人，收回回执0份。没有由模型、主创或程序代打“4/5”。已按用户工具生成匿名片名、随机片序、独立本地答卷；作者答案保存在private/，不得随评委文件夹派发。已准备的文件夹数不计作观众数。')
 text('先用role_side的五份核心身份审片；role_front供另外一组或替代视角，不能让同一首次观众反复看同take两机位。H快、Z快、H慢、Z慢分别至少4/5，未答和不确定保留，不把慢尸高分平均掉快尸失败。受伤活人只作压力项。')
 text('cause_main给另一组五人：开场、水瓶、正式三人门口戏，自由回答谁先做什么、什么使另一人改变、最后怎样。双人隔离和根轨迹正/负对照另有可选独立组，避免同一人先看双人版后记住三人版答案。开放题必须按原话人工评分，工具不自动宣布惊悚或自然。')
 text('120项项目测试通过；主片和匿名媒体均核对解码帧数、逐帧PTS、尺寸、时长和无音轨。本人复诊使用逐帧采样、实际坐标与渲染图检查，不作为真人原速盲看的名额。')
 text('仍未完成：90秒主片、24人全站编舞、完整慢群传播、低伏撑椅与撞网、片尾反转、新真人动捕；尚无原生感染冲刺、多人自主猎群或本剧情MCP端到端验收。既有普通Jog一对一验收保持独立；本轮所有新情节如实叫电影编排。')
 text('研究只指导对照设计，不替代观众：Naughty Dog动画师关于受刺激牵引的身体；Gao等追逐知觉中的朝向/追向线索；Atkinson等对动态身体表达的研究。没有据此制定“科学丧尸关节阈值”。',10)
 for url in ['https://www.naughtydog.com/blog/the_last_of_us_part_I_hbo_tv_show_clickers','https://taogao.comm.ucla.edu/project_ThePsychophysicsOfChasing.html','https://doi.org/10.1068/p5096']:text(url,8)
 page(4);c.save()
def html_entry():
 films=[('D03_ThreeActors_10s','先看：10秒三人门口戏','静音；扑击前收步，抓空后补步，白衣延后进入视觉中心。'),('D03_TwoActors_10s','双人隔离','同一份核心动作与根轨迹，去掉白衣，单看逃与扑。'),('Bottle_Reactions_12s','一只水瓶，两种反应','只落一次；同伴转向人，感染者松掉旧包带去追刺激。')]
 cards=''.join(f'<section><h2>{title}</h2><p>{text}</p><video controls preload="metadata" src="media/{name}.mp4"></video><p><a download href="media/{name}.mp4">下载原速静音版</a></p></section>' for name,title,text in films)
 (OUT/'START_HERE.html').write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>四号站台 · 第二轮表演试片</title><style>body{background:#10191c;color:#e8edec;font:18px/1.7 system-ui;max-width:1120px;margin:40px auto;padding:0 20px}a{color:#dfba77}video,img{width:100%;background:#050808}section{margin:40px 0;padding-top:20px;border-top:1px solid #334346}.notice{padding:18px;border-left:3px solid #c9a463;background:#1c292d}</style><h1>四号站台 · 第二轮表演试片</h1><p>这轮检查的是“她在逃，它在猎”。保留地铁站与演员，以动作的选择、抓空和恢复区分角色。</p><div class="notice">主创审片页含角色说明，不能直接给首次盲审观众。真人回执目前 0；没有宣布识别率、惊悚或自然度通过。90秒、24人完整版尚未制作。</div><p><a href="第二轮表演优化报告.pdf">四页实施报告</a> · <a href="BLIND_REVIEW_INSTRUCTIONS.html">如何派发匿名审片</a> · <a href="media/Opening_Preserved_9s.mp4">保留的9秒开场</a></p>'''+cards+'''<section><h2>可选：原声设计版</h2><p><a href="media/D03_WithFoley_10s.mp4">10秒门口戏，附原创立体声拟音</a>。先看静音版再比较；脚步由支撑标注与踝点代理驱动，声音为后期设计，不是录音或接触力仿真。此版不进入匿名测试。</p></section><section><h2>同模、同灰衣、无包的身份试演</h2><p>下列标签只供主创。匿名评委版在 blind_panels/；每位观众只看一个视角。</p>'''+''.join(f'<p><a href="media/roles/{name}.mp4">{name}</a></p>' for name in assembly.ROLE_TAKES)+'''</section><section><h2>因果对照</h2><p><a href="media/Roots_Interception_10s.mp4">真实根轨迹：截击</a> · <a href="media/Roots_Parallel_10s.mp4">真实根轨迹：同向赶路</a> · <a href="media/Parallel_Control_10s.mp4">同向赶路正式人物负对照</a></p><p>二维片由实际USD根读回生成；两个标记同样式，无尾迹、身份颜色或标签。它们用于判断路线关系，不能作为自主追猎证明。</p></section><img src="Contact_Sheet.jpg"><p>原始采集、实际关节/鞋点、几何、未判区间与源码快照在 provenance/ 和 evidence/。所有旧成片保持不变。</p></html>''')
 (OUT/'BLIND_REVIEW_INSTRUCTIONS.html').write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>盲审派发</title><style>body{font:18px/1.8 system-ui;max-width:900px;margin:40px auto;padding:20px}</style><h1>先选独立观众，再派匿名文件夹</h1><p>主测试：把 blind_panels/role_side/ 中五个独立文件夹，分别给五位没读剧本的人。每人打开自己文件夹的 index.html；答完下载回执。只给这个评委目录，不能给整个交付包、主创审片入口、private/ 或本说明。</p><p>role_front 是另一视角的替代/独立新组，不要让同一个首次观众重复看同一take。每个核心快/慢、健康/感染片分别需要至少4/5识别，不能平均。</p><p>另找五位新观众用 cause_main；先自由复述，不提前说身份。cause_isolation 与 cause_roots 为可选独立诊断组，避免先看隔离版教会正式版答案。人数不够就保留待审。</p><p>收到真实 response_*.json 后，在工具 blind.py 中以对应 private/*.key.json 评分；开放题按原话在manual模板里逐题人工编码。待审分数中缺席不是实际失败观众，派了五份也不是看过五人。目前真实回执0。</p></html>''')
def main():
 assert (OUT/'screening_status.json').exists()
 ids=list(assembly.ROLE_TAKES.values())+['platform04-r2-duo-06','platform04-r2-trio-06','platform04-r2-parallel-01','platform04-r2-bottle-06','platform04-r2-camera-only-01','platform04-r2-geometry-02']
 analyser=assembly.load_module(ROOT/'scripts/analyze_platform04_r2.py','analysis');identity={}
 for name,rid in assembly.ROLE_TAKES.items():
  qa=analyser.analyse(ROOT/'runs'/rid);a=next(iter(qa['actual_motion'].values()));identity[name]={'run':rid,'mean_speed_mps':a['mean_speed_over_source_interval_mps'],'plant_drift_m':qa['worst_xy_plant_drift_m']}
 identity['fast_mean_speed_relative_difference']=abs(identity['H_fast_side']['mean_speed_mps']-identity['Z_fast_side']['mean_speed_mps'])/max(identity['H_fast_side']['mean_speed_mps'],identity['Z_fast_side']['mean_speed_mps']);save(OUT/'evidence/identity_motion.json',identity)
 for rid in ['platform04-r2-duo-06','platform04-r2-trio-06','platform04-r2-parallel-01','platform04-r2-bottle-06']:analyser.analyse(ROOT/'runs'/rid)
 for rid in ids:copy_evidence(rid)
 for name in ['P0_diagnosis.json','source_inventory_ual2.json','geometry_render_alignment.json','bottle_prop_qa.json']:shutil.copy2(ROOT/'.runtime/platform04_r2'/name,OUT/'evidence'/name)
 vis=rows(ROOT/'runs/platform04-r2-trio-06/actor_frames.jsonl');summary={}
 for aid in ['H01','F02','F01']:
  r=[x for x in vis if x['id']==aid and 135<=x['f']<=205];summary[aid]={'frames':len(r),'minimum_visible_fraction':min(x['visible_fraction'] for x in r),'minimum_box_height_px':min(x['box_px'] for x in r),'below_35pct_visible_frames':sum(x['visible_fraction']<.35 for x in r),'scope':'actual leaf ID pixels / same-camera isolated actual-deformed-mesh opaque silhouette; not subjective performance'}
 save(OUT/'evidence/critical_visibility.json',summary)
 audit=assembly.load_module(ROOT/'.runtime/platform04_90/kit/cast/audit_cast_motion.py','cast_audit')
 for rid in ['platform04-r2-duo-06','platform04-r2-trio-06','platform04-r2-bottle-06']:
  vv=rows(ROOT/'runs'/rid/'actor_frames.jsonl');result=audit.audit(vv,30,expected=[x['id'] for x in read(ROOT/'runs'/rid/'actual_roster.json')['actors']]);save(OUT/'evidence'/(rid+'_freeze_review.json'),result)
 source=OUT/'source_current';(source/'scripts').mkdir(parents=True,exist_ok=True)
 for p in [*ROOT.glob('scripts/platform04_r2_*.py'),*ROOT.glob('scripts/*platform04_r2*.py'),ROOT/'scripts/check_master.py']:shutil.copy2(p,source/'scripts'/p.name)
 shutil.copytree(ROOT/'src/simpeople',source/'src/simpeople',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copytree(ROOT/'tests',source/'tests',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'));shutil.copytree(ROOT/'configs',source/'configs',dirs_exist_ok=True)
 shutil.copytree(ROOT/'.runtime/platform04_r2/kit',OUT/'input_kit',dirs_exist_ok=True);shutil.copy2(ROOT/'.runtime/platform04_r2/tests.log',OUT/'tests_120.log')
 contact_sheet();pdf_report();html_entry()
 save(OUT/'DELIVERY.json',{'date':'2026-11-03','title':'四号站台 第二轮表演试片','runs':ids,'input_kit_sha256':'ea2782515abd0992ef4be4e1c01970c1e1eedf7634063f02ff365a32c1094ff4','tests_passed':120,'human_reviewers':0,'real_responses':0,'role_recognition_passed':None,'scariness_passed':None,'full_90s_rendered':False,'autonomous_infection_pursuit_claim':False})
 (OUT/'REPRODUCTION.txt').write_text('Use the existing repository, assets and Isaac 6.2.0-rc.14 installation.\nFrozen per-take source_snapshot is authoritative; no NVIDIA character meshes or textures are packaged.\nNew capture: /data/omniverse/isaac-sim-6.2.0/python.sh scripts/platform04_r2_capture.py --run-id UNIQUE --mode identity|duo|trio|parallel|bottle|camera_only --gpu 2\nIdentity options: --case human_fast|infected_fast|human_slow|infected_slow|human_fast_injured --angle side|front45 --body 0|3\nGeometry: python.sh scripts/platform04_r2_geometry.py --run-id UNIQUE --gpu 3\nActual point analysis: python3 scripts/analyze_platform04_r2.py RUN_ID\nTests: PYTHONPATH=src python3 -m pytest -q tests\nRequired preserved input caches: runs/platform04-motion-01, platform04-90-jog-02, deadweight-zombie-probe-05. Existing station kit .runtime/platform04/kit and opening kit .runtime/platform04_90/kit remain unchanged.\nOrdinary travel uses distance-driven Native Jog phase; no post-export retiming or interpolation. Braking/attack/recovery are authored R2 key poses/IK; no new motion capture or native infected sprint claim.\nBlind review tool is in input_kit/Platform04_R2. Send individual anonymous viewer folders only; never private/ or creator page. No real viewer answer is generated.\n')
 print('R2 evidence, 4-page report and local entry complete')
if __name__=='__main__':main()
