"""Compact local repair report from closed runs; never upgrades movie claims."""
import json,html,hashlib,shutil
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'productions/deadweight_v2_review'
d=json.loads((OUT/'DELIVERY.json').read_text());p=json.loads((OUT/'physics_regression.json').read_text());bugs=json.loads((OUT/'actual_bug_causes.json').read_text());shoe=json.loads((OUT/'deformed_shoe_qa.json').read_text());alignment=json.loads((OUT/'rgb_pose_alignment.json').read_text());clear=json.loads((OUT/'mitt_window_clearance.json').read_text());fit=json.loads((ROOT/'runs/deadweight-v2-wardrobe-03/fitted_mitts/fit_measurements.json').read_text())
def esc(x):return html.escape(str(x))
def image(name,caption):return f'<figure><a href="{name}"><img src="{name}"></a><figcaption>{esc(caption)}</figcaption></figure>'
def table(head,rows):return '<table><tr>'+''.join('<th>'+esc(x)+'</th>' for x in head)+'</tr>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</table>'
cases=p['cases'];regrows=[[name,f"{r['mass_A_kg']:.0f}/{r['mass_B_kg']:.0f}",f"{r['initial_acceleration_mps2']:.6f}",f"{r['travel_m']:.6f}",r['wheel_audit']['passed'] if r['wheel_audit']['passed'] is not None else '静止，不作滚动通过'] for name,r in cases.items()]
body='<h1>《死重》V2 修复试片</h1><p>2026-11-02 · 本地复核包 · 保留 V1，未重渲 88 秒全片</p><p>本轮交付为 24 秒原速剪辑：同一游客变异、最后登车与门锁、标记轮组启动、对向车上升、隔窗举手、女主跨门槛进入独立检修台。人物使用完整骨骼缓存；车辆使用一维配重动力学。它是修复评审版本。</p>'
body+='<video controls preload="metadata" src="'+d['movie']+'"></video><p><a href="'+d['movie']+'">打开 24 秒干净版</a> · <a href="修复实施报告.pdf">四页 PDF</a> · <a href="Heroine_FourActions_9s.mp4">女主四动作 9 秒</a> · <a href="DELIVERY.json">交付数据</a></p>'
body+='<h2>人物：像素归因后再修</h2><p>两个躯干硬壳分别是 survivor_01/RainCape 与 heroine/RainCape；前伸和垂手白卵分别是 heroine/LWing、RWing。原制服蒙皮没有整体缩放或重导入。7 个实际可见对象/帧组合均通过隐藏后消失、恢复后重现；第 2570 帧摄影师不在画面内，未记作失败或通过。完整路径、源层与叶级 ID 见 <a href="actual_bug_causes.json">归因 JSON</a>。</p>'
for f in [1981,2570]:body+=image(f'frame_{f}_before_after.png',f'左：冻结 V1 重放；右：只修附加外壳与翼套；原始帧 {f}，身体 TRS 与根不变。')
body+=f'<p>正式女主演员左手实测腕到指端 {fit["L"]["hand_length_m"]*100:.2f} cm，短翼外长 {fit["L"]["external_extent_m"][1]*100:.2f} cm；不是直接沿用样例 21.8 cm。四动作片的翼套/窗平面最小几何净空 {clear["min_gap_m"]*1000:.2f} mm。头罩、相机、原模型附属器材保留。</p>'
body+='<div class="grid">'+''.join(image(n+'.png',caption) for n,caption in [('hands_down','垂手'),('hand_raised','举手'),('wrist_turn','转腕'),('window_gesture','贴窗示意')])+'</div>'+image('eleven_costumes.png','11 个实际基础人物的原制服组合，无 RainCape 硬壳。')
body+='<h2>质量驱动车，不再指定缓动轨迹</h2><p>长度 112 m、坡度 30°。空车各 2500 kg；A 水箱 0 kg、B 水箱 120 kg；23×74 kg 感染者、女主 76 kg，B 侧 12×75 kg，最终 A/B 总质量 4278/3520 kg。附加旋转等效惯量 160 kg，滚阻 400 N，制动上限 11.2 kN，限速 2 m/s；均为明确配置的电影模型参数。</p>'+table(['反事实','总质量 kg','初始加速度 m/s²','轨程变化 m','轮轨读回'],regrows)
body+=f'<p>完整数值旅程 {p["production"]["travel_time_s"]:.3f} 秒，中点 {p["production"]["meeting_time_s"]:.3f} 秒，终点实际积分到 {p["production"]["arrival_q_m"]:.6f} m 后停稳。没有把两车拽回旧帧 1981。门接点在运动中断开时速度保持连续，再通过有限刹车停稳。完整反事实与最差帧/轮编号见 <a href="physics_regression.json">动力学回归 JSON</a>。</p>'
body+='<p>轮距、轮轨法向净空、角度及累计滚动约束来自 Isaac 中变换后的真实钢轨顶面与轮面顶点；不是用预期公式填写观测值。车轮仍是理想无滑滚动运动学，质量来自配置：本轮没有测 PhysX 接触冲量。</p><p>'+''.join(f'<a href="{f}.mp4">{label}</a>　' for f,label in [('Equal_4s','等载固定机位'),('Loaded_6s','增载固定机位'),('Brake_11kN_6s','11.2 kN 刹车'),('Brake_8kN_8s','8.4 kN 刹车')])+'</p>'
body+='<h2>海岸空间：相同锁机位，干燥 / 风雨</h2><p>连续岸坡、海面与海堤、贴坡基础和中段跨谷桥墩、两站售票合影设施、上站补水管阀门、独立检修台；采用纯天空 HDRI，移除了旧的亮绿地平线。岩石扫描保留原尺寸，分段铺设。当前岸坡的贴图重复与坡面基础轮廓仍需美术精修。</p><div class="grid">'
for view,label in [('lower_to_upper','下站看上站'),('foundation','轨道基础'),('refuge','隔间门与检修台')]:
 for weather in ['dry','storm']:body+=image(f'{weather}_{view}.png',label+' / '+weather)
body+='</div><h2>连续采集与已知边界</h2>'
body+=f'<p>每帧一个 1/30 秒正步进，再做零时间同步渲染屏障。用实际移动的洋红球与相机投影测图像归属，4 个位置的最大像素误差 {max(r["error_pixels"] for r in alignment["samples"]):.2f} px，检测物在正式录制前已移除。逐帧保留所有人物关节、相机、轮角、仿真与墙钟时间、源 RGB 散列。720 个输出帧均来自真实动作帧，无运动补帧；相邻源整帧重复 {d["source_rgb_adjacent_full_duplicates"]} 对。分辨率、帧数和每帧 PTS 检查通过。</p>'
body+=f'<p>11 个目标人物各检查两个完整丧尸循环，选定支撑鞋底顶点的最大每帧水平残差 {max(r["selected_deformed_shoe_patch_max_step_slip_m"] for r in shoe["rigs"])*1000:.3f} mm。这是按鞋底重构位移后的电影接地一致性指标，不能等价于独立接触力、整段步行完全无滑移或全身无穿模。</p>'
body+='<p>低机位首条补拍位于站台结构内，黑画面已拒绝，失败记录保留。最终轮轨段换到另一侧，并将四秒分为轮组近景与下站对向车视角；二者的动力学时间连续，但不是“透过底盘同时看清两车”的单镜头。素材接替的每个同 tick 轨程完全相同。</p><p>会车和到站前允许省略中间旅程，没有加速原始动作。三种玻璃条件另有同姿态截图；尚未做严格受控的雨效/双玻璃性能消融。104 项项目测试通过。</p>'
body+='<p>脱险段另做 4.5 秒复拍：从 Native 稳定段实测健康循环为 42 帧，起步和停步混合姿态，走 3.3 米后在检修台内停稳。根相对关节最大帧间位移由 0.269 米降至 0.098 米；这是姿态连续性指标，不能代替接触力验收。</p>'
body+='<p><b>未测：</b>真人静音盲看、全身/道具自碰撞、PhysX 轮轨接触、Native 丧尸导航/乘车、这次剧情的 Agent 端到端调用。人类盲看要回答：什么让车开起来？两人交会时想做什么？女主最后去了哪里？本包不将这些未测项标为通过。</p>'
body+='<p><a href="master_frame_map.jsonl">完整输出到源帧映射</a> · <a href="rgb_pose_alignment.json">RGB 对齐试验</a> · <a href="deformed_shoe_qa.json">11 角色鞋底数据</a> · <a href="mitt_window_clearance.json">翼套净空</a></p>'
css='body{font:16px/1.7 "Noto Sans CJK SC",sans-serif;max-width:1120px;margin:36px auto;color:#203842;padding:0 24px;background:#f7faf9}h1,h2{color:#173e4a}h2{margin-top:36px}video{width:100%;background:#0b171f}img{width:100%;display:block}figure{margin:18px 0}figcaption{font-size:13px;color:#586a74}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}table{width:100%;border-collapse:collapse;font-size:13px}th,td{border:1px solid #c5d3d8;padding:8px;text-align:left}th{background:#174653;color:white}a{color:#176c80}p{overflow-wrap:anywhere}'
(OUT/'START_HERE.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>死重 V2 修复评审</title><style>'+css+'</style>'+body+'</html>')
# Four-page PDF, using a standard CJK CID font; all images are real captures.
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'));c=canvas.Canvas(str(OUT/'修复实施报告.pdf'),pagesize=(595.28,841.89));W=515;x=40;y=0;c.setTitle('Deadweight V2 Repair Review');c.setAuthor('ROSClaw SimPeople')
def start(title,n):
 global y
 c.setFillColorRGB(.08,.24,.29);c.setFont('STSong-Light',21);c.drawString(x,792,title);c.setFont('STSong-Light',9);c.drawString(x,768,'ROSClaw SimPeople / 2026-11-02 / V2 修复试片 / '+str(n)+'/4');y=742
def para(text,size=10):
 global y
 c.setFont('STSong-Light',size);line=''
 for char in text:
  if pdfmetrics.stringWidth(line+char,'STSong-Light',size)>W:
   c.drawString(x,y,line);y-=size*1.5;line=char
  else:line+=char
 if line:c.drawString(x,y,line);y-=size*1.5
 y-=8
def fig(name,caption,width=515):
 global y
 from PIL import Image
 im=Image.open(OUT/name);h=width*im.height/im.width;c.drawImage(str(OUT/name),x,y-h,width,h);y-=h+13;c.setFont('STSong-Light',8);c.drawString(x,y,caption);y-=21
start('01 / 人物：确认网格，再修外形',1)
para('两张原始帧恢复后，通过叶级实例 ID 和逐个隐藏/恢复定位到 RainCape 与旧 LWing/RWing。移除附加硬壳，保留原蒙皮制服、海鸥头和相机；原身体骨骼 TRS、根变换不变。')
fig('frame_1981_before_after.png','1981：左为 V1 冻结重放，右为修复；完整分辨率对照另附。')
fig('frame_2570_before_after.png','2570：白色大卵与躯干硬壳已单独修复。')
para(f'正式演员左手长度 {fit["L"]["hand_length_m"]*100:.2f} cm；拟合翼套外长 {fit["L"]["external_extent_m"][1]*100:.2f} cm。四动作 9 秒原片与 11 种实际制服组合另附。')
para('完整路径、源层、像素投票、隐藏后像素清零与恢复重现数据保存在 actual_bug_causes.json。未全局缩放人物或重导入动作。')
c.showPage();start('02 / 配重动力学与轮轨读回',2)
para('明确口径：一维理想张紧索配重动力学 + Isaac 6.2 渲染。车辆根没有导演缓动曲线。轮轨几何在 Kit 中读实际网格世界变换，轮角从轮面径向顶点测量；不宣称 PhysX 接触。')
for name,r in cases.items():para(f'{name}  |  {r["mass_A_kg"]:.0f}/{r["mass_B_kg"]:.0f} kg  |  初始 a={r["initial_acceleration_mps2"]:.4f} m/s²  |  轨程变化 {r["travel_m"]:.4f} m',9)
para(f'电影总质量 A/B=4278/3520 kg；112 m、30°、限速 2 m/s。完整积分旅程 {p["production"]["travel_time_s"]:.3f} 秒，中点 {p["production"]["meeting_time_s"]:.3f} 秒。60/120 Hz 制动停距收敛，门断开不瞬间清零速度。')
fig('frame_0330.png','最终近轮拍次：轮面两侧设有真实几何色标；车厢由支架连接倾斜走行架。',420)
c.showPage();start('03 / 海岸空间与锁机位',3)
para('相同相机分别拍干燥版与风雨版。补齐岸坡、海水、海堤、桥墩与基础、上/下站设施和独立检修台。扫描岩石保持原尺寸分段铺设；纯天空替换旧亮绿背景。')
from PIL import Image
for view,label in [('lower_to_upper','下站看上站'),('foundation','轮组高度看基础'),('refuge','隔间门到检修台')]:
 h=140
 for j,weather in enumerate(['dry','storm']):c.drawImage(str(OUT/f'{weather}_{view}.png'),40+j*263,y-h,252,h)
 y-=h+14;c.setFont('STSong-Light',9);c.drawString(40,y,label+' / 左：干燥；右：风雨');y-=24
para('仍需精修：大面积岩壁的贴图重复与局部坡面基础轮廓。干燥空间评审未用雾遮挡；本片尚不是最终美术质量。')
c.showPage();start('04 / 24 秒试片、验证与限制',4)
para('干净版：1920×1080，30 fps，24.000 秒，720 个真实动作帧。变异 → 登车与门锁 → 轮组转动/对向车上升 → 新动力学中点隔窗举手 → 跨门槛进入检修台。中间旅程用切镜省略；没有加速或补帧。')
fig('Meeting_Physics_Midpoint.png','新数值轨程中点取帧；未强拉到 V1 的第 1981 帧。',455)
para(f'图像归属用移动洋红球验证，4 处投影最大误差 {max(r["error_pixels"] for r in alignment["samples"]):.2f} px。11 个目标人物各 71 帧鞋底顶点检查通过；选定支撑鞋底每帧水平残差最大 {max(r["selected_deformed_shoe_patch_max_step_slip_m"] for r in shoe["rigs"])*1000:.3f} mm。这是重构后的电影一致性指标，非独立物理接触证据。')
para('104 项项目测试通过。完整关节、相机、轮角、源帧与时钟保存在 master_frame_map.jsonl。黑画面补拍已拒绝，失败记录保留；最终低轮和对向车镜头使用连续动力学时间的两个机位，不宣称单镜头同时看清两车。')
para('未测：真人静音盲看；完整全身碰撞；PhysX 接触与轮轨冲量；Native 丧尸导航/乘车；本次剧情的 Agent 端到端任务。玻璃有零/单/双层同姿态截图，严格受控的玻璃/雨效性能消融尚未做。')
para('建议先静音看干净版，问三件事：什么让车开起来？两人交会时想做什么？女主最后去了哪里？本包不把未进行的人类评审写成通过。')
c.save();print(OUT/'START_HERE.html');print(OUT/'修复实施报告.pdf')
