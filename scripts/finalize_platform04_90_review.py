"""Local first-round handoff. Never claims 90s or a human review pass."""
import hashlib,html,json,shutil,subprocess,zipfile
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.utils import simpleSplit
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'productions/platform04_directors_review'
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def read(p):return json.loads(p.read_text())
def copy_run(rid):
    src=ROOT/'runs'/rid;dst=OUT/'provenance'/rid;dst.mkdir(parents=True,exist_ok=True)
    for p in src.iterdir():
        if p.is_file() and (p.suffix in ['.json','.jsonl','.txt','.py','.npz'] or p.name.startswith('mask_compare') or p.name.startswith('no_glass')):shutil.copy2(p,dst/p.name)
    if (src/'source_snapshot').exists():shutil.copytree(src/'source_snapshot',dst/'source_snapshot',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
def make_html():
    films=[('01_Opening_9s.mp4','9 秒开场','三人、绿门、回头等待与听声。'),('02_Run_Layers_8s.mp4','正式人物跑姿逐层对照','同人物、同相位；先侧面，再前侧 45°。SDK Sprint 已明确归一化步相，只比较姿态。'),('03_Characters_12s.mp4','12 秒性格群像','啃包带、听声张望、扶环失衡、三对错拍慢行。'),('04_Door_Uncut_10s.mp4','10 秒连续门口追逐','故事第 53–63 秒，单拍次连续 300 个源帧，无切镜。')]
    cards=''.join(f'<section><h2>{title}</h2><p>{desc}</p><video controls preload="metadata" src="{name}"></video><p><a href="{name}" download>下载原文件</a></p></section>' for name,title,desc in films)
    (OUT/'START_HERE.html').write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>四号站台 · 第一轮正式试片</title><style>body{background:#101719;color:#e9eded;max-width:1100px;margin:40px auto;font:18px/1.7 system-ui;padding:0 20px}video,img{width:100%;background:#000}a{color:#e8b86b}section{margin:40px 0;padding-top:16px;border-top:1px solid #354146}.badge{color:#edbf71}</style><h1>四号站台 · 第一轮正式试片</h1><p class="badge">1080p30 · 正式人物 · 本地 Isaac Sim 6.2</p><p>本轮交付四项试片；90 秒、24 人完整电影尚未制作。真人盲看目前 0 人。请先静音看开场、性格、追逐，再看动作对照。</p><p><a href="Blind_Review.html">无答案提示的盲看页</a> · <a href="第一轮实施报告.pdf">四页实施报告</a> · <a href="04_Door_WithFoley_10s.mp4">追逐立体声拟音版</a> · <a href="Native_Jog_RealTime_7s.mp4">未重定时的原生 Jog 参考</a></p>'''+cards+'''<p>黑白静音：<a href="01_Opening_9s_Gray.mp4">开场</a> · <a href="03_Characters_12s_Gray.mp4">群像</a>。完整 1080p 单层试镜位于 run_layers/。实际源帧、角色可见性、骨长、未判区间及几何记录位于 evidence/ 和 provenance/。</p><img src="Contact_Sheet.jpg"><p>电影角色由独占骨骼缓存编舞，不作为多人自主丧尸追逐或 Agent/MCP 端到端成功的证明。已通过的旧普通 Jog 一对一证据单独保留。</p></html>''')
    (OUT/'Blind_Review.html').write_text('''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>看片记录</title><style>body{font:18px/1.7 system-ui;max-width:1000px;margin:40px auto;background:#141a1d;color:#eee;padding:20px}video{width:100%}textarea,input{box-sizing:border-box;width:100%;padding:12px;margin:10px 0}button{padding:12px 25px}</style><h1>先看片，再回答</h1><p>请由没读过剧情的人独立观看；第一次先静音，不给提示。此页不会自动上传任何内容。</p><label>看片编号（例如 V1）<input id="viewer"></label><video controls src="01_Opening_9s_Gray.mp4"></video><label>黄衣原本要跟谁去哪里？<textarea id="q1"></textarea></label><video controls src="03_Characters_12s_Gray.mp4"></video><label>哪一个在啃东西，哪一个在找人，哪一个快倒了？<textarea id="q2"></textarea></label><video controls src="04_Door_Uncut_10s.mp4"></video><label>红衣从哪里扑出来，黄衣怎么躲开的？<textarea id="q3"></textarea></label><button onclick="download()">下载本次回答 JSON</button><p>目标：5 位独立观众，至少 4 位能用画面说清。未收齐实际回答前，记录仍为 0 人通过。</p><script>function download(){const result={viewer:document.getElementById('viewer').value,answers:[1,2,3].map(n=>document.getElementById('q'+n).value),time:new Date().toISOString(),self_report_only:true};let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(result,null,2)],{type:'application/json'}));a.download='viewer_answers.json';a.click();}</script></html>''')
def report():
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'));c=canvas.Canvas(str(OUT/'第一轮实施报告.pdf'),pagesize=(595,842));c.setTitle('四号站台：90秒导演版 · 第一轮正式试片实施报告');y=780
    def text(s,size=11):
        nonlocal y
        c.setFont('STSong-Light',size)
        # simpleSplit wraps whitespace, which leaves Chinese prose overflowing.
        lines=[];line='';width=0.
        for char in s:
            advance=pdfmetrics.stringWidth(char,'STSong-Light',size)
            if line and width+advance>495:lines.append(line);line='';width=0.
            line+=char;width+=advance
        if line:lines.append(line)
        for line in lines:c.drawString(50,y,line);y-=size*1.6
        y-=7
    def title(s):text(s,20)
    def image(p,w=495,h=278):
        nonlocal y
        c.drawImage(str(p),50,y-h,width=w,height=h,preserveAspectRatio=True,anchor='c');y-=h+15
    def page(n):
        nonlocal y
        c.setFont('STSong-Light',9);c.drawString(50,25,f'本地交付 · 2026-11-03 · {n}/4 · 真人盲看 0 人');c.showPage();y=780
    title('四号站台：第一轮正式试片')
    text('交付的是四项正式人物试片：9 秒无声开场、8 秒跑姿分层对照、12 秒性格群像、10 秒连续门口追逐。90 秒、24 人完整版本尚未渲染。')
    image(OUT/'Contact_Sheet.jpg',495,250)
    text('开场：沿用制作包三镜的实际机位与人物走位，以黄包、青衣回头等待、绿门站务员招手建立目的地；第三镜先眼动、再侧耳，第二声后收紧肩带。另交黑白静音版。')
    text('群像：深色旧包与带子的拉紧/拖动/释放，听声找人的前后两次张望，手留在固定吊环旁的失衡和补抓，以及六名慢行者的不同手势。正式镜头分别使用 3、9、9 名角色；跨试片共有 18 个角色 ID，使用 11 种基础人物。24 人表仅为后续编舞计划。')
    text('观看入口 START_HERE.html；先静音看，再看拟音版。所有片段均为真实 Isaac RGB 离线采集，固定 1/30 秒动作步长，没有 AI 补帧、慢放扩时或墙钟录屏转帧率。')
    page(1);title('骨长问题已在正式人物上定位')
    text('旧片的世界关节位置插值确实缩短长骨。本轮恢复旧主拍及长椅补拍，共 540 帧、11 人，读取实际 USD FK；与旧日志最大差 0.000000346 米。')
    baseline=read(ROOT/'runs/platform04-90-baseline-02/baseline_findings.json')
    for aid,bone,label in [('hero','R_Thigh/R_Calf','旧黄衣右大腿'),('intercept','R_Forearm/R_Hand','旧红衣右前臂')]:
        b=baseline['long_bone_ranges'][aid][bone];text(f'{label}：最短 {b["min_m"]*100:.2f} cm / 最长 {b["max_m"]*100:.2f} cm。位置中点混合不能保持人体比例。')
    text('新管线：同半球四元数 SLERP，在关节局部空间混合旋转；保留目标人物骨段平移，只允许根与骨盆平移，再做 FK 与按正式演员尺寸求解的 IK。新片骨长范围证据来自实际 USD 读回。没有全局缩放人物来掩盖变形。')
    calibration=read(ROOT/'runs/platform04-90-audition-04/motion_fit.json')['jog_calibration'];text(f'健康底座采用本机原生 Jog 的稳定区间 {calibration["start_source_tick"]}–{calibration["end_source_tick_exclusive"]-1}，完整左右交替周期 33 帧。边界关节差最大 1.72 mm；后续半周期平均腿部位置差 8.75 mm，作为整数采样相位漂移记录，不改写为零。')
    text('六窗依次展示 Native Jog、SDK Sprint、旧腿部处理、旧钉臂感染层、SDK 加凝视、最终健康层。先侧视 4 秒，再前侧 45° 4 秒，单层原规格文件另附。为同相位看形，SDK 源做了明确的步相归一化；这不是原生冲刺速度验收。另附真实 Native Jog 7 秒未重定时参考。')
    image(ROOT/'runs/platform04-90-audition-04/side_final_030.png',495,220)
    page(2);title('连续追逐与空间检查')
    geometry=read(ROOT/'runs/platform04-90-geometry-06/geometry_qa.json');door=read(ROOT/'runs/platform04-90-door-09/completed.json')
    text('红衣在窗内从落后 3.3 米跑至领先约 2.8 米，在 D03 内收步转向，再穿过真实门洞扑出。女主沿浅弧刹切；红衣扑空后继续过冲。白衣另走较外侧路线，避免三个身体重叠。相机和角色只由同一仿真帧控制。')
    image(ROOT/'runs/platform04-90-door-09/frame_1775.png',495,240)
    text(f'10 秒单拍次共 300 个连续源帧，53–63 秒，无切镜。实际手部至黄衣网格/道具顶点最近距离：30 Hz 采集 {door["near_miss"]["hand_to_hero_deformed_vertex_distance_m"]*100:.2f} cm；加密诊断 {geometry["near_miss"]["hand_hero_vertex_distance_m"]*100:.2f} cm。它是顶点距离，不是精确表面最短距离或接触力。')
    text(f'关键区间 57.7–60.5 秒按 120 Hz 加密：三位前景人物变形表面相交记录 {len(geometry["triangle_intersections"])} 项；门框内深于 2 mm 的顶点记录 {len(geometry["door_frame_vertices_deeper_than_2mm"])} 项；线性顶点扫掠接触 {len(geometry["linear_sweep_contacts"])} 项，未解共面候选 {geometry["linear_sweep_unresolved_coplanar_pairs"]} 项。线性扫掠仅近似采样间运动，不宣称连续非线性人体碰撞认证。')
    text('三位前景人物实际鞋底最低高度均约 +3 mm；低速阶段保留完整步态幅度，按距离减慢步相，并做有上限的鞋底高度校正。此项是动画接地，不是轮廓/足端接触力认证。')
    text('新增 B3 窄椅位于 (25.35, 6.70) 米；凹入式通道墙保留开场视线。真实烘焙 NavMesh 的车内→站台、D03→绿门、椅侧→绿门三条查询连通；没有拿查询冒充实际穿行。')
    page(3);title('验收范围与下一轮入口')
    text('项目测试 116 项通过。视频逐解码帧检查分辨率、帧数、时长、首帧与逐帧 PTS。编码和帧率正确不等于每个角色没有停顿。')
    for name in ['01_Opening_9s','03_Characters_12s','04_Door_Uncut_10s']:
        a=read(OUT/'evidence'/name/'freeze_review.json');text(f'{name}：冻结/单区域候选 {len(a["suspect_segments"])} 段，同相候选 {len(a["synchronized_segments"])} 段；全片从未取得足够可见标记的 ID：{", ".join(a["expected_present_but_never_judged"]) or "无"}。逐镜未判和短可见区间完整保留，不把镜外人物写成通过。')
    text('逐角色数据使用实际叶级实例 ID 与同机位、同变形几何的孤立轮廓作为可见率分母；不是用投影矩形冒充遮挡率。衣物表面标记按镜头固定顶点 ID。透明玻璃、毛发贴图与短时遮挡仍会降低覆盖，候选必须结合 RGB 复看。')
    text('本轮返工记录：旧 XYZ 混合；过早截取的 Jog 过渡窗；第二声后无反应；手遮住咬带；车窗挡住扶环脚部；慢群 Idle 权重压住腿导致滑动；红衣超前不足与抓手过近。失败/淘汰拍次均保留，未覆盖旧母版。')
    text('未完成：90 秒完整剪辑、24 人全站编舞、真人动捕、完整低伏撑椅起身、门口撞网和片尾青衣咬肩带；未证明全身自碰撞、真实抓握/布料/接触力；未做感染冲刺或多人自主猎群原生验收。嘴点是头骨偏移设计点，不作为牙齿接触测量。')
    text('声音为原创程序合成的剪辑拟音；脚步时机来自真实脚踝高度极小值代理，声像来自实际人物与摄影机，窗内闷声出门后变清。不称为真实录音或声学求解。')
    text('真人盲看：0 人。Blind_Review.html 可离线播放和下载独立回答；目标 5 人中至少 4 人看懂三项关系。用户给定制作包要求先过这关再做完整 90 秒；本轮没有替观众作答，也没有自动宣布惊悚/自然度通过。')
    page(4);c.save()
def main():
    ids=['platform04-90-opening-03','platform04-90-opening-listen-04','platform04-90-character-04','platform04-90-character-slow-08','platform04-90-door-09','platform04-90-audition-04','platform04-90-baseline-02','platform04-90-jog-02','platform04-90-geometry-06','platform04-90-nav-02']
    for rid in ids:copy_run(rid)
    for rid in ['platform04-90-opening-03','platform04-90-opening-listen-04','platform04-90-character-04','platform04-90-character-slow-08','platform04-90-door-09']:
        shutil.copy2(ROOT/'runs'/rid/'raw_video.mp4',OUT/'provenance'/rid/'raw_video.mp4')
    shutil.copy2(ROOT/'runs/platform04-90-door-09/raw_video.mp4',OUT/'Door_Raw_Capture_10s.mp4')
    # Dependency caches only; NVIDIA character meshes stay in the user's asset cache.
    for rid,files in [('platform04-motion-01',['rig.json','native_bones.npz','frames.jsonl']),('deadweight-zombie-probe-05',['cache_rig.json','native_bones.npz','zombie_frames.jsonl'])]:
        dst=OUT/'dependencies'/rid;dst.mkdir(parents=True,exist_ok=True)
        for file in files:shutil.copy2(ROOT/'runs'/rid/file,dst/file)
    scripts=OUT/'source_current/scripts';scripts.mkdir(parents=True,exist_ok=True)
    for p in list((ROOT/'scripts').glob('platform04_90_*.py'))+[ROOT/'scripts/build_platform04_90_review.py',ROOT/'scripts/finalize_platform04_90_review.py',ROOT/'scripts/check_master.py']:shutil.copy2(p,scripts/p.name)
    shutil.copytree(ROOT/'src/simpeople',OUT/'source_current/src/simpeople',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copytree(ROOT/'tests',OUT/'source_current/tests',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ['pyproject.toml','AGENTS.md']:
        if (ROOT/name).exists():shutil.copy2(ROOT/name,OUT/'source_current'/name)
    shutil.copytree(ROOT/'.runtime/platform04_90/kit',OUT/'director_kit',dirs_exist_ok=True)
    base=OUT/'base_station_and_foley';base.mkdir(exist_ok=True)
    shutil.copytree(ROOT/'.runtime/platform04/kit/station',base/'station',dirs_exist_ok=True)
    shutil.copytree(ROOT/'.runtime/platform04/kit/audio',base/'audio',dirs_exist_ok=True)
    shutil.copytree(ROOT/'configs',OUT/'source_current/configs',dirs_exist_ok=True)
    dst=OUT/'ordinary_native_reference';dst.mkdir(exist_ok=True)
    for f in ['Native_Fork_North_vs_South.mp4','native_pursuit_qa.json','native_fork_trajectories.csv']:shutil.copy2(ROOT/'productions/platform04_review'/f,dst/f)
    save(OUT/'gate.json',{'four_review_deliverables':True,'full_90s_rendered':False,'full_24_actor_cast_rendered':False,'human_reviewers':0,'blind_review_passed':False,'next_gate':'5 independent viewers, >=4 understand the three questions; actual responses required','infection_native_pursuit_claim':False})
    save(OUT/'rejected_takes.json',{'preserved_under_local_runs':True,'entries':[
        {'run':'platform04-90-jog-01','reason':'original target outside initial test-floor navigation area; failed, not reference'},
        {'run':'platform04-90-audition-02','reason':'anatomy fixed, but cycle window still transitional; not selected'},
        {'run':'platform04-90-audition-03','reason':'overstrict integer-phase overlap guard stopped before capture; retained failed'},
        {'run':'platform04-90-opening-03','range':'210..269','reason':'listen reaction held too long; replaced all three actors from listen-04'},
        {'run':'platform04-90-character-slow-06','reason':'Idle mixing suppressed fitted slow-walk legs; replaced all nine actors'},
        {'run':'platform04-90-character-slow-07','reason':'legs fixed, but shared phase still made group stepping too similar; staggered in slow-08'},
        {'run':'platform04-90-door-08','reason':'120Hz actual-skin audit detected hero/red intersections after missed grab; not delivered'},
        {'run':'platform04-90-geometry-04','reason':'24 sampled intersection records; one deck penetration; quality failed'},
        {'run':'platform04-90-geometry-05','reason':'shortened recovery clears the principal actors, but deck penetration remains; quality failed'},
        {'run':'platform04-90-geometry-02/03','reason':'own incomplete diagnostics stopped; no verdict; accelerated CPU cubic-event implementation used subsequently'}]})
    (OUT/'REPRODUCTION.txt').write_text('Runtime: /data/omniverse/isaac-sim-6.2.0/python.sh, 6.2.0-rc.14; Behavior/Nav 110.4.0.\nFrom repository root, preserve unique run IDs. Assets remain local and are referenced, not redistributed.\nSource snapshots under provenance/<run>/source_snapshot are authoritative for each original take; source_current is the latest follow-up source.\nRequired source cache runs: platform04-motion-01, platform04-90-jog-02, deadweight-zombie-probe-05; data copied under dependencies/ and provenance/.\nThe extracted production kit must be at .runtime/platform04_90/kit.\nShoot: python.sh scripts/platform04_90_shoot.py --run-id NEW_UNIQUE_ID --mode opening|character|door --gpu 2\nAudition: python.sh scripts/platform04_90_audition.py --run-id NEW_UNIQUE_ID --gpu 2\nGeometry: python.sh scripts/platform04_90_geometry.py --run-id NEW_UNIQUE_ID --gpu 3\nNavigation: python.sh scripts/platform04_90_nav.py --run-id NEW_UNIQUE_ID --gpu 3\nAssembly is explicitly mapped in evidence/<piece>/assembly.json and master_frame_map.jsonl. Current assembler defaults point to the delivered take IDs.\nTests: PYTHONPATH=src python3 -m pytest -q tests\nNo upload/publish performed. No full 90s film or five-person review has been claimed.\n')
    with (OUT/'REPRODUCTION.txt').open('a') as f:
        f.write('\nRestore director_kit/ as .runtime/platform04_90/kit and base_station_and_foley/ as .runtime/platform04/kit. Restore each dependency cache under runs/<run-id>; use its take snapshot for exact replay. Requires gcc and g++. Selected original camera captures are in provenance/<run>/raw_video.mp4; only mapped frame ranges are selected, so an original take may contain rejected footage. Door_Raw_Capture_10s.mp4 is an untouched copy of door-09/raw_video.mp4.\n')
    report();make_html()
    save(OUT/'DELIVERY.json',{'title':'四号站台 · 90秒导演版第一轮试片','date':'2026-11-03','runs':ids,'input_kit_sha256':'61293c1070195a97c390faef056d84c3a583f810ba0384f991829a4472c44552','entry':'START_HERE.html','full_90s':False,'human_reviewers':0,'tests_passed':116})
if __name__=='__main__':main()
