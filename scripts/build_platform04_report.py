"""Local screening entry and concise evidence report from actual closed runs."""
import hashlib
import html
import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'productions/platform04_review'


def main():
    d=json.loads((OUT/'DELIVERY.json').read_text());g=json.loads((OUT/'geometry_qa.json').read_text());n=json.loads((OUT/'native_pursuit_qa.json').read_text())
    # Exact camera comparison: kit cached proxies and separate formal stage.
    meta=[]
    for mode,run in [('kit','platform04-kit-open-01'),('formal','platform04-formal-reference-01')]:
        r=ROOT/'runs'/run;meta.append(json.loads((r/'completed.json').read_text()))
        for t in [8.5,11.5]:shutil.copy2(r/f'reference_{t:.1f}.png',OUT/f'{mode}_same_camera_{t:.1f}.png')
    errors=[]
    for a,b in zip(meta[0]['stills'],meta[1]['stills']):
        error=float(abs(np.array(a['camera_matrix'])-np.array(b['camera_matrix'])).max());assert error==0
        errors.append({'time_s':a['story_time_s'],'camera_matrix_max_error':error,'focal_mm_error':abs(a['focal_mm']-b['focal_mm'])})
    (OUT/'kit_camera_comparison.json').write_text(json.dumps({'samples':errors,'scope':'exact supplied ShotCamera in both still sets; formal standing columns at x10.5/18 moved to y7.1 for eyeline, stage/lighting/costumes intentionally differ'},indent=2))
    # Small image exports are decoded actual movie frames, never artwork.
    gallery=OUT/'gallery';gallery.mkdir(exist_ok=True)
    for f in [0,48,90,180,240,270,330,345,360,375,420,450,480,510,539]:
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(OUT/d['movie']),'-vf',f'select=eq(n\\,{f}),scale=960:540','-frames:v','1',str(gallery/f'frame_{f:04d}.jpg')],check=True)
    sheet=Image.new('RGB',(1440,3*290),(8,15,18));pen=ImageDraw.Draw(sheet)
    for i,f in enumerate([0,90,180,270,330,360,375,420,510]):
        im=Image.open(gallery/f'frame_{f:04d}.jpg');im.thumbnail((480,270));x=i%3*480;y=i//3*290;sheet.paste(im,(x,y));pen.text((x+8,y+273),f'{f/30:.2f}s / tick {f}',fill=(204,222,217))
    sheet.save(OUT/'Contact_Sheet.jpg',quality=93)
    e=lambda s:html.escape(str(s))
    def figure(file,caption):return f'<figure><a href="{e(file)}"><img loading="lazy" src="{e(file)}"></a><figcaption>{e(caption)}</figcaption></figure>'
    def table(rows):return '<table>'+''.join('<tr>'+''.join('<td>'+e(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</table>'
    body='<div class="kicker">ROSCLAW SIMPEOPLE / LOCAL SCREENING / 2026.11.02</div><h1>四号站台：盲侧</h1><p class="lead">她在看身后的追者。窗内那件红衣，已经跑到她前面。</p>'
    body+=f'<video id="movie" controls preload="metadata" poster="gallery/frame_0270.jpg" src="{e(d["movie"])}"></video>'
    body+='<nav>'+''.join(f'<a href="{file}">{label}</a>' for file,label in [(d['movie'],'18 秒有声试片'),(d['silent'],'静音版'),('地铁追逐实施报告.pdf','四页实施报告'),('Native_Fork_North_vs_South.mp4','原生追逐对照'),('Blind_Review.html','独立盲看入口')])+'</nav>'
    body+='<p>正式人物、正式灯光、真实 Isaac 6.2 RGB；1920×1080 / 30 fps / 18.000 s。场内 11 个独立人物：3 名生者、8 名感染者。本轮交付是正式追逐试片，60 秒正片尚未拍摄，真人盲看尚未进行。</p>'
    body+='<h2>这次让危险追上人</h2><p>开头从刷手机者的手与肩颈异常开始，再让白衣从静止爆冲。黄衣只顾回头，红衣在车内超越她，抢前方真实门洞扑出。女主收步改向，红衣抓空后继续冲出、补步恢复。后段保留长椅侧撑起的低伏者和伸手执拗追人的感染者。四种表演使用不同起动时刻，没有用一组跑步循环整齐铺满站台。</p>'
    body+=figure('Contact_Sheet.jpg','实际成片解码九帧；同一黄衣、白衣与红衣贯穿追逐。')
    body+='<p>门口 10.20–13.17 s 的 89 帧保持同一相机矩阵、同一拍次、连续源 tick。<a href="Door_NearMiss_Uncut_30fps.mp4">独立查看无声、未调色的连续门口原片</a>。原片保留空中跨步，没有逐帧把鞋压到地面；没有视频补帧或变速。</p>'
    body+='<h2>动作、脸和声音</h2><p>将提供的 53 关节冲刺按骨名与 retarget 标记送入本机 Behavior SDK，再读取正式演员实际输出的 101 关节。普通冲刺与感染冲刺各得到 17 帧稳定循环；收短腿部步幅、保留步频与腾空，重新拟合真实鞋底。头、颈、眼球朝向单独处理，红衣持续朝女主转头；头部朝向误差只是代理测量，不能等同真人理解了眼神。</p>'
    body+='<div class="grid">'+figure('glass_none_0270.png','9.0 s：无玻璃，原始 RGB')+figure('glass_single_0270.png','9.0 s：单层玻璃，同姿态、相机和曝光')+'</div>'
    body+='<p>声轨使用工程包的原创合成 Foley 函数，按新片实际支撑相位重配 116 个脚步事件。车内红衣的脚步低通、距离与左右声像随实际位置变化，走出门洞时逐渐变清楚。擦地、喘息和关网错开；开头没有恐怖配乐，整段没有持续嘶吼。它是电影声音设计，不是声学求解或现场录音。</p>'
    body+=table([['检查','本轮结果与范围'],['输出时钟','540 帧；所有展示 PTS 精确均匀；相邻解码整帧重复 0 对'],['门口最近手部距离',f'{g["near_miss"]["min_hand_hero_vertex_distance_m"]*100:.2f} cm，tick 362 / 12.067 s；实际变形手部到女主顶点'],['门口三组前景人物',f'{g["foreground_triangle_surface_checks"]["samples"]} 个 30 Hz 三角形表面配对样本，检测相交 0；不含连续扫掠/自碰撞/全背景'],['门洞框体','已测红衣顶点穿入实际车体框体超过 2 mm 的记录为 0'],['直线跑支撑漂移',f'4.4–9.33 s，21 个多帧支撑段，选定鞋底点最大漂移 {g["max_multi_frame_patch_drift_m"]*1000:.2f} mm；急转、刹停与全片接地未授予同等通过']])
    body+='<h2>会追人的原生证据另交</h2><p>电影用独占骨骼缓存和编排路径拍精准近失。另在同一站台上让 Native Behavior 独占人物根与骨骼，追者只追一个感知代理；代理以 3.75 Hz 接收当前可见位置和估计速度，不读取逃者未来轨迹。没有逐帧重发 move_to。</p>'
    body+='<video controls preload="metadata" src="Native_Fork_North_vs_South.mp4"></video><p>左：逃者走柱北；右：逃者走柱南。两个独立原生运行按相同仿真帧并排，取两者共有的 357 帧；完整取消停稳录像另存。</p>'+figure('native_fork_trajectories.png','真实运行坐标，不是电影导演曲线。')
    body+=f'<p>同种子、同实际初态、同代码、相同 GPU 配置，仅改逃者在第 30 tick 的选择。分叉前追者差异为 0；之后轨迹最大分开 {n["post_branch_max_hunter_difference_m"]:.3f} m，两次都从对应柱侧绕行。两次取消后均观察到低于 0.15 m/s 并持续 0.5 s。<a href="native_pursuit_qa.json">原生 QA</a> · <a href="native_fork_trajectories.csv">实际轨迹 CSV</a>。</p>'
    body+='<p>失去视野试验另外让观察者先原生 Idle 2.5 s 隔离遮挡变量，再原生跟随记忆点；实际记录 PURSUE → LAST_SEEN → SEARCH → PURSUE。SEARCH 期间目标点保持最后所见位置，没有偷读遮挡后的实时坐标。重新看到目标发生在逃者再次出发之前，因为观察者自己绕过了柱子。另有正式人物实际走完车厢→门洞→站台→出口三段，均以实际任务成功、距离和停稳判定。</p>'
    body+='<p><a href="native_evidence/north-03/raw_video.mp4">北侧完整原速录像</a> · <a href="native_evidence/south-04/raw_video.mp4">南侧完整原速录像</a> · <a href="native_evidence/occlusion-05/raw_video.mp4">遮挡与重获原速录像</a> · <a href="native_evidence/portals-02/raw_video.mp4">车厢到出口原速录像</a></p>'
    body+='<p>原生试验用普通 Jog 和几何视野/遮挡判定，不是 RGB 识别、原生感染冲刺或多尸群猎；Native Follow 的硬速度/加速度上限尚未验收，本轮没有增加对外 MCP 丧尸能力声明。技术视图仅在烘焙后隐藏顶棚叶网格并加诊断照明，保留全部碰撞体和 NavMesh。旧版遮顶黑画面保留在运行目录，已拒绝用于交付。</p>'
    body+='<h2>排演与正式人物同机位</h2><div class="grid">'+figure('kit_same_camera_8.5.png','本机 Isaac 打开提供的 OPEN_METRO / ShotCamera，8.5 s')+figure('formal_same_camera_8.5.png','正式人物与灯光，严格复制相机位姿及焦距；不是最终成片机位')+'</div>'
    body+='<h2>交付与下一道评审</h2><p>本次代码测试 112 项通过。完整帧映射保留源 run_id、tick、源 RGB 散列、仿真/墙钟时刻、摄影机和全部人物根/关节；长椅撑起补拍只替换 395–539 帧，三位主角同 tick 的根、关节与旋转差均为 0。门口段不在补拍范围内。</p>'
    body+='<p>将静音版单独给没读过方案的人看一次，再询问谁在逃、红衣从哪里来、黄衣怎么躲过。<a href="Blind_Review.html">独立盲看页</a>只在本地下载回答，不会上传。当前真实观众人数 0，不能宣称已经达到“吓人”或“4/5 人看懂”。按照提供任务书，真人盲看通过后再扩成约 60 秒、12–18 名感染者的正片。</p>'
    body+='<p><a href="Platform04_18s_SourceRGB.mp4">18 秒未调色素材剪辑</a> · <a href="master_frame_map.jsonl">逐帧原始数据</a> · <a href="geometry_qa.json">网格 QA</a> · <a href="Platform04_OriginalFoley.events.json">脚步事件</a> · <a href="DELIVERY.json">交付清单</a> · <a href="REPRODUCTION.txt">本机复现与素材路径</a></p>'
    css='body{font:16px/1.75 "Noto Sans CJK SC",sans-serif;max-width:1120px;margin:38px auto;padding:0 24px;background:#0a1317;color:#c5d3d1}h1{font-size:44px;color:#f0c76c;line-height:1.2}h2{margin-top:42px;color:#e6ece8}.kicker{color:#78aaa7;letter-spacing:.14em;font-size:12px}.lead{font-size:21px;color:#e8e5d2}video,img{width:100%;display:block;background:#000}nav{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}nav a{border:1px solid #48615d;padding:8px 13px;border-radius:4px}a{color:#8fc9c3}figure{margin:18px 0}figcaption{color:#91a6a5;font-size:13px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}table{border-collapse:collapse;width:100%;font-size:14px}td{padding:10px;border:1px solid #33484a}tr:first-child{color:#ebd29a}td:first-child{width:21%}p{overflow-wrap:anywhere}@media(max-width:700px){.grid{display:block}h1{font-size:32px}}'
    (OUT/'START_HERE.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>四号站台：盲侧 / 本地试片</title><style>'+css+'</style>'+body+'</html>')
    review='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>内部静音看片</title><style>body{font:18px/1.7 sans-serif;max-width:1000px;margin:40px auto;padding:0 20px;background:#0b151b;color:#eee}video{width:100%}textarea,input{display:block;width:90%;padding:10px;margin:10px 0 22px}button{padding:12px 24px}</style><h1>内部静音看片</h1><p>适合第一次看、没读过方案的观众。先完整静音看一次，再填写自己的理解。回答只下载到本机。</p><video id="v" controls muted src="Platform04_BlindSide_18s_Silent.mp4"></video><form id="f" hidden><label>匿名编号<input name="reviewer" required></label><label>谁在逃？<textarea name="escape" required></textarea></label><label>红衣最初在哪里，从哪里出来？<textarea name="red" required></textarea></label><label>黄衣靠什么躲过？<textarea name="avoid" required></textarea></label><p>写完以上答案后，可打开有声版再看一次。</p><a href="Platform04_BlindSide_18s_1080p30.mp4" target="_blank">有声版</a><label>第一次觉得危险的秒数与原因<input name="danger"></label><label>最紧张的秒数与原因<input name="peak"></label><label>最出戏的地方<textarea name="problem"></textarea></label><button>下载我的回答 JSON</button></form><script>v.onended=()=>f.hidden=false;f.onsubmit=e=>{e.preventDefault();const r=Object.fromEntries(new FormData(f));r.recorded_at=new Date().toISOString();r.scope='human self-report; correctness requires separate review';const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json'}));a.download='platform04_review_'+Date.now()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}</script></html>'''
    (OUT/'Blind_Review.html').write_text(review)
    # Compact four-page PDF. All image panels are captured or decoded actual RGB.
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'));c=canvas.Canvas(str(OUT/'地铁追逐实施报告.pdf'),pagesize=(595.28,841.89));c.setTitle('Platform 04 Blind Side / Local Review');c.setAuthor('ROSClaw SimPeople');y=0
    def page(title,num):
        nonlocal y
        c.setFillColorRGB(.06,.17,.20);c.setFont('STSong-Light',21);c.drawString(40,793,title);c.setFont('STSong-Light',9);c.drawString(40,768,f'ROSClaw SimPeople / 2026-11-02 / 四号站台：盲侧 / {num}/4');y=740
    def para(text,size=10):
        nonlocal y
        c.setFont('STSong-Light',size);line=''
        for char in text:
            if pdfmetrics.stringWidth(line+char,'STSong-Light',size)>515:c.drawString(40,y,line);y-=size*1.55;line=char
            else:line+=char
        if line:c.drawString(40,y,line);y-=size*1.55
        y-=9
    def fig(file,caption,width=515):
        nonlocal y
        im=Image.open(OUT/file);h=width*im.height/im.width;c.drawImage(str(OUT/file),40,y-h,width,h);y-=h+13;c.setFont('STSong-Light',8);c.drawString(40,y,caption);y-=23
    page('01 / 让威胁抢到前方',1)
    para('交付：18.000 秒、1080p30、540 个真实动作帧；11 个独立正式人物，3 名生者与 8 名感染者。列车停站，站台、车厢、门洞和出口空间连通。旧《死重》与《换班时刻》保留。')
    fig('gallery/frame_0270.jpg','9.0 s：黄衣仍回望白衣；红衣已从窗内跑到她前面。')
    para('白衣从刷手机到肩颈异常、爆冲；红衣隔窗盯人、抢门扑出；低伏者定点撑住长椅再起身；执拗者伸手并换向。人物轮廓与起动相位分别设计，未用整群同步加速的拖步代替冲刺。')
    para('门口 10.20–13.17 秒：89 个连续源帧、同一拍次、相机矩阵差为 0。红衣从实际门洞踏出，黄衣收步斜切；抓空后保留过冲与恢复，没有在抓空瞬间剪特写。')
    para('有声版、静音版、未调色素材剪辑及门口连续片段均附。当前是正式追逐试片；60 秒全片未制作，真人“是否吓人”的评价未测。')
    c.showPage();page('02 / 动作重定向、接地与近失',2)
    para('53 关节源冲刺通过骨名与 retarget 标记导入本机 SDK，捕获正式演员实际 101 关节输出。正常/感染冲刺稳定循环各 17 帧。原始步幅过大，因此用两骨 IK 收短腿部轨迹，保留步频、空中跨步和上身表现；不是加速慢丧尸走路。')
    fig('gallery/frame_0360.jpg','12.0 s：正式人物、真实门口与急转同框；主片没有切开近失。')
    para(f'30 Hz 实际变形网格复核：红衣右手到黄衣最近顶点 {g["near_miss"]["min_hand_hero_vertex_distance_m"]*100:.2f} cm，tick 362。门口三组前景人物共 291 个三角形表面配对样本，相交 0；车体框内超过 2 mm 的顶点记录为 0。')
    para(f'4.4–9.33 秒直线跑段共 21 个多帧支撑区间，选定鞋底点最大漂移 {g["max_multi_frame_patch_drift_m"]*1000:.2f} mm。该指标不覆盖全部刹停/转弯，也不是接触力测量。连续扫掠、自碰撞与全体背景配对未测。')
    para('头颈与眼球朝向独立修正；无玻璃/单玻璃同姿态原图另附。声音重配 116 次脚步，车内红衣低通，门外逐渐清楚；短促擦地、喘息与关网让位给追逐。程序 Foley 为电影设计，不是物理声学。')
    c.showPage();page('03 / 原生人物真的会改道追逐',3)
    para('与电影分开验收：同种子、同代码、同 GPU 配置、同实际初态；只改变活人在第 30 tick 绕柱哪侧。人物根与骨骼始终归 Native Behavior，追者仅更新感知代理，不读取活人未来路径。')
    fig('native_fork_trajectories.png','实测轨迹：虚线为逃者，实线为 Native 追者；黑块为实体柱。',475)
    para(f'分叉前追者差异 0，分叉后最大差异 {n["post_branch_max_hunter_difference_m"]:.3f} m；两次取消后均低于 0.15 m/s 并稳定 0.5 秒。感知 3.75 Hz，以视野、距离和固体遮挡判可见。')
    para('遮挡试验先让观察者原生 Idle 2.5 秒，再跟随记忆点；实测追逐→最后所见→搜索→重获。SEARCH 期间代理位置不随隐藏人物更新。另有正式角色原生走完车厢→门洞→站台→出口三段。')
    para('范围：1 对 1、普通 Jog、几何感知原型。未验收原生感染冲刺、多人猎群、硬速度/加速度上限或新 MCP 丧尸接口。技术画面隐藏顶棚叶网格并加照明，保留碰撞体与导航；旧遮顶黑片已拒绝，原始运行保留。',9)
    c.showPage();page('04 / 交付、复核与当前边界',4)
    para('主片：Platform04_BlindSide_18s_1080p30.mp4。静音版：Platform04_BlindSide_18s_Silent.mp4。总入口：START_HERE.html。原生分叉左右对照：Native_Fork_North_vs_South.mp4。')
    fig('Contact_Sheet.jpg','按顺序的实际成片九帧；全片原速，未补运动帧。')
    para('逐帧展示时间戳全部通过，540 帧解码，相邻完整画面重复 0 对。两个正式拍次分别写入 540/145 帧、丢弃 0、空 RGB 0；源帧、源 RGB 散列、相机、全部关节与墙钟均留存。长椅撑起补拍只替换 395–539 帧；三位主角同 tick 根/关节/旋转差均为 0。')
    para('112 项测试通过。交付保留实际源码快照、运动导入记录、网格 QA、原生任务/观测、CSV 与原始录像。18 秒片是独占骨骼缓存电影；原生追逐是另一组运行，不能互相替代证明。')
    para('真人盲看尚未进行（0 人）。独立 Blind_Review.html 可先静音看，再本地下载答案。按提供制作包要求，应由 5 位未读方案的人看片，至少 4 位说清谁在逃、红衣从哪来、黄衣怎么躲；达标后再扩 60 秒群尸正片。没有由模型代填评价。')
    para('继续改善方向：更自然的急刹与全身重心、脸部表情、低伏者近景。未进行完整多角色碰撞、PhysX 接触、雨效性能消融或 Agent 端到端丧尸任务。',9)
    c.save()
    print(OUT/'START_HERE.html');print(OUT/'地铁追逐实施报告.pdf')


if __name__=='__main__':main()
