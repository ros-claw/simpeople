"""Build an offline entry page from actual gate reports and recorded artifacts."""
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
gates=json.loads((ROOT/'reports/phase_gates.json').read_text())
def esc(value):return html.escape(str(value),quote=True)
def link(path,title):
    return f'<a href="../{esc(path)}">{esc(title)}</a>' if (ROOT/path).exists() else f'<span class="pending">{esc(title)}（待生成）</span>'

rows=[]
for phase in ['P4','P5','P6']:
    gate=gates.get(phase,{})
    run=gate.get('run_id')
    summary_path=ROOT/'runs'/run/'acceptance_summary.json' if run else None
    if not gate.get('passed') or not summary_path or not summary_path.exists():
        rows.append(f'<tr><td>{phase}</td><td colspan="8">尚无完整通过的运行；查看阶段和失败记录。</td></tr>');continue
    s=json.loads(summary_path.read_text());r=s['richness'];p=s['performance']
    evidence=link(f'runs/{run}/acceptance_summary.json',run)+' · '+link(f'reports/viewers/{run}.html','轨迹')+' · '+link(f'runs/{run}/raw_video_wallclock.mp4','完整墙钟录像')
    rows.append(f'<tr><td>{phase}</td><td>{r["instances"]}</td><td>{r["base_identities"]}/{r["appearances"]}/{r["role_types"]}</td><td>{p["sim_elapsed_s"]:.1f}</td><td>{s["minimum_role_cycles"]}</td><td>{p["rtf"]:.3f}</td><td>{p["measured_updates_per_wall_second"]:.2f}</td><td>{esc(s["task_status_counts"])}</td><td>{evidence}</td></tr>')

seed_rows=[]
for path in sorted((ROOT/'runs').glob('seed*/seed_validation.json')):
    data=json.loads(path.read_text());run=path.parent.name
    state='通过' if data['passed'] else '测量窗通过；周期未全覆盖' if data.get('measurement_passed') else '未完整通过'
    seed_rows.append(f'<tr><td>{link(f"runs/{run}/seed_validation.json",run)}</td><td>{data["seed"]}</td><td>{data["sim_elapsed_s"]:.1f}</td><td>{state}</td><td>{esc(data["task_status_counts"])}</td></tr>')

pressure_section=''
pressure_run=gates.get('P6_pressure',{}).get('run_id')
if pressure_run:
    path=ROOT/'runs'/pressure_run/'acceptance_summary.json'
    if path.exists():
        data=json.loads(path.read_text())
        links=' · '.join(link(f'runs/{pressure_run}/{name}',title) for name,title in [
            ('acceptance_summary.json','完整结果'),('quality_audit.json','几何检查'),('raw_video_wallclock.mp4','连续墙钟录像')])
        pressure_section=f'<h2>100 人容量探索</h2><p>{esc(pressure_run)}：{data["performance"]["sim_elapsed_s"]:.1f} 仿真秒，实际移动 {data["richness"]["moving_participants"]}/100，RTF {data["performance"]["rtf"]:.3f}，任务结果 {esc(data["task_status_counts"])}。这是容量探索，未列为完整百人日常活动支持。</p><p>{links}</p>'

controls=[]
for path,title in [('runs/final-control-01/single_continuous_demo.mp4','单人连续演示：完整生活流程、事件、改令与取消'),
                   ('runs/demo-population-30-02/demo.mp4','多人演示：全景、步态、座位、队列与 Agent 改令'),
                   ('runs/demo-population-30-02/demo_visual_audit.json','慢跑、坐姿、取消与实际源帧审计'),
                   ('runs/demo-population-30-02/demo_timing_audit.json','最终剪辑的完整解码时间戳核验'),
                   ('runs/appearance-24-03/asset_contact_sheet.jpg','12 个基础人物 / 24 个已验证外观'),
                   ('runs/final-control-01/event_control_acceptance.json','外部事件与连续改令验收'),
                   ('runs/final-control-01/agent_mcp_acceptance.json','真实 stdio MCP 会话：18 个工具'),
                   ('runs/final-control-01/command_latency_audit.json','接收、主线程应用、原生调用与实际运动延迟'),
                   ('runs/final-control-01/late_obstacle_acceptance.json','已预约路线被箱体切入后的刹停重规划'),
                   ('runs/reserved-boundary-01/interaction_acceptance.json','窄门、FIFO 队列、单人跟随与暂停取消'),
                   ('reports/extension_lifecycle.json','Kit 扩展加载、移动、场景保护与卸载'),
                   ('runs/repro-final-01/reproduction_acceptance.json','独立源码目录的单人干净启动复现'),
                   ('runs/seed50-17-03/reproduction_source_audit.json','新版独立源码：冻结文件、启动路径与缓存重定位核对'),
                   ('runs/seed50-17-03/reproduction_acceptance.json','新版独立源码的完整 50 人复现结果')]:
    controls.append('<li>'+link(path,title)+'</li>')

page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ROSClaw SimPeople 验收证据</title><style>
body{margin:auto;max-width:1500px;padding:32px;font:16px/1.65 system-ui,sans-serif;color:#e5eaf4;background:#101624}h1,h2{line-height:1.3}a{color:#8ac8ff}p{max-width:1000px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #38445b;padding:10px;text-align:left;vertical-align:top}th{background:#25324a}.table{overflow:auto}.pending{color:#a5aab4}li{margin:9px 0}.note{background:#1d2940;padding:18px;border-left:4px solid #73b9ff}
</style><h1>ROSClaw SimPeople · 真实运行证据</h1>
<p>Isaac Sim 6.2.0-rc.14 / Behavior 110.4.0。CLI、stdio MCP 与 Skill 共用真实人物控制桥。此页面只链接实际生成的文件；人数、外观、角色和性能分别统计。</p>
<p class="note">raw_video.mp4 使用仿真帧时间轴；raw_video_wallclock.mp4 按每帧测得的墙钟时间播放，保留停顿。演示的剪切位置另有 manifest，编码 30 FPS 不代表实时运行 30 FPS。根胶囊和箱体距离是几何代理，不是精确 mesh 或人体受力证书。</p>
<p>'''+ ' · '.join(link(p,t) for p,t in [('README.md','启动和接入'),('reports/IMPLEMENTATION_REPORT.md','实施报告'),('reports/phase_gates.json','阶段状态'),('reports/ACCEPTANCE_MATRIX.md','用例矩阵'),('reports/FAILURE_LEDGER.md','失败与撤回记录'),('dist/delivery_manifest.json','交付包 SHA256'),('dist/archive_verification.json','压缩包内部校验'),('dist/rosclaw-simpeople-evidence.tar.gz','完整证据包')])+'''</p>
<h2>完整人数档位</h2><div class="table"><table><tr><th>阶段</th><th>实例</th><th>基础/外观/角色</th><th>仿真秒</th><th>最少角色周期</th><th>RTF</th><th>实际更新/墙钟秒</th><th>任务结果</th><th>证据</th></tr>'''+''.join(rows)+'''</table></div>
<h2>动作与 Agent 控制</h2><ul>'''+''.join(controls)+'''</ul>
<h2>补充种子验证</h2><p>30 人补充窗口为 450 仿真秒；修正巡视停靠点后的 50 人附加种子要求完整 600 秒。要求时长和逐项结果见各自 seed_validation.json。提前停止和未完整通过的运行也保留。</p><div class="table"><table><tr><th>运行</th><th>Seed</th><th>仿真秒</th><th>结果</th><th>任务结果</th></tr>'''+''.join(seed_rows)+'''</table></div>
'''+pressure_section+'''
<h2>阅读边界</h2><p>人物 RGB、实际根与七个关键关节已记录。机器人深度/LiDAR、接触力和任意骨架自动兼容未验收。原生慢跑已验证，MotionBricks/CrowdBricks 外部 worker 未启用。多人移动目标跟随仍标为 blocked。共享机器的资源总量包含其他 Isaac 进程。</p></html>'''
(ROOT/'reports/evidence_index.html').write_text(page)
print(ROOT/'reports/evidence_index.html')
