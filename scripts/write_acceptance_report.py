"""Summarize completed evidence without promoting in-progress runs to passed."""
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
gates=json.loads((ROOT/'reports/phase_gates.json').read_text())
accepted=[]
for phase in ['P4','P5','P6']:
    gate=gates.get(phase,{})
    if not gate.get('passed') or not gate.get('run_id'):continue
    path=ROOT/'runs'/gate['run_id']/'acceptance_summary.json'
    if path.exists():
        data=json.loads(path.read_text())
        if data['functional_population_gate_passed']:accepted.append((phase,data))
highest=max((d['richness']['instances'] for _,d in accepted),default=0)
test_match=re.search(r'(\d+) passed',(ROOT/'reports/unit_tests.txt').read_text())
test_count=test_match.group(1) if test_match else '未记录'
rows=[];spatial=[];timing_rows=[]
for phase,d in accepted:
    r=d['richness'];p=d['performance']
    rows.append(f"| {phase} / `{d['run_id']}` | {r['instances']} | {r['base_identities']} / {r['appearances']} / {r['role_types']} | {p['sim_elapsed_s']:.1f} | {d['minimum_role_cycles']} | {p['rtf']:.4f} | {p['measured_updates_per_wall_second']:.2f} | {d['task_status_counts'].get('succeeded',0)} / {d['task_status_counts'].get('failed',0)} / {d['shutdown_cancellations']} |")
    separation=d['trajectory_proxies'].get('minimum_same_floor_root_separation',{}).get('distance_m')
    if separation is not None:spatial.append(f"| {r['instances']} | {separation:.3f} | {d.get('native_route_retry_events',0)} |")
    metrics=json.loads((ROOT/'runs'/d['run_id']/'metrics.json').read_text())
    times=metrics.get('stage_time_medians_s',{})
    if times:
        values=' | '.join(f"{times[key]*1000:.2f}" for key in ['kit_and_render_s','supervisor_s','journal_s','rgb_and_encode_s'])
        timing_rows.append(f"| {r['instances']} | {values} | {d['resources']['max_process_rss_gib']:.2f} |")

seeds=[]
for path in sorted((ROOT/'runs').glob('seed*/seed_validation.json')):
    d=json.loads(path.read_text())
    state='通过' if d['passed'] else '测量窗通过；周期未全覆盖' if d.get('measurement_passed') else '未完整通过'
    seeds.append(f"| `{d['run_id']}` | {d['seed']} | {d['sim_elapsed_s']:.1f} | {state} | `{d['task_status_counts']}` |")

pressure_run=gates.get('P6_pressure',{}).get('run_id','p6-pressure-100-01')
pressure_path=ROOT/'runs'/pressure_run/'acceptance_summary.json'
if pressure_path.exists():
    d=json.loads(pressure_path.read_text());p=d['performance']
    pressure=f"100 人压力探索已保存：`{d['run_id']}`，{p['sim_elapsed_s']:.1f} sim s，RTF {p['rtf']:.4f}，实际参与移动 {d['richness']['moving_participants']}/100，最少角色周期 {d['minimum_role_cycles']}，任务分布 `{d['task_status_counts']}`。它不作为完整功能档位，见对应 summary、quality_audit 和 completion。"
else:pressure='100 人探索尚无已关闭的完整结果，不列为已通过能力。'

population_repro=''
repro_path=ROOT/'runs/seed50-17-03/reproduction_acceptance.json'
if repro_path.exists():
    d=json.loads(repro_path.read_text())
    population_repro=(f"新版独立目录复现结果：`seed50-17-03/reproduction_acceptance.json`，通过={d['passed']}，"
                      f"{d['sim_elapsed_s']:.1f} sim s，实际移动 {d['moving_participants']}/50，每人至少 {d['minimum_role_cycles']} 个周期，"
                      f"任务分布 `{d['task_status_counts']}`。它与早期单人复现分别保存，不覆盖排队失败。")

latency_path=ROOT/'runs/final-control-01/command_latency_audit.json'
latency='命令接收、主线程应用、原生调用与实际姿态运动分别保存在事件和轨迹中。'
if latency_path.exists():
    l=json.loads(latency_path.read_text());bridge=l['all_bridge_receive_to_apply'];dispatch=l['agent_task_receive_to_native_dispatch'];motion=l['stationary_actor_receive_to_observed_motion'];cancel=l['cancel_request_to_settled_terminal']
    latency=(f"`final-control-01/command_latency_audit.json` 分开统计：{bridge['samples']} 个桥请求的主线程应用延迟中位数 {bridge['median_s']*1000:.1f} ms、p95 {bridge['p95_s']*1000:.1f} ms、峰值 {bridge['max_s']:.3f} s；"
             f"{dispatch['samples']} 个移动任务从收到请求到真实原生调用的 p95 为 {dispatch['p95_s']:.3f} s；"
             f"{motion['samples']} 个已有静止观测的样本，首次捕获实际根速度 >0.15 m/s 的延迟中位数 {motion['median_s']:.3f} s、p95 {motion['p95_s']:.3f} s；"
             f"{cancel['samples']} 次取消到停稳终态的 p95 为 {cancel['p95_s']:.3f} s。样本量和全部长尾保留，已在移动的改令不冒充静止起步样本；姿态采样限制动作开始时间的精度。桥请求统计包括本次完整会话中的初始化和读取，不是独占机器的固定延迟承诺。")

report=f'''# ROSClaw SimPeople 实施与验收报告

本报告从已关闭运行的真实证据生成。阶段状态见 [phase_gates.json](phase_gates.json)，原始证据总入口见 [离线索引](evidence_index.html)。受理回执、进程退出码和视频编码帧率均不等同动作验收。

## 五个直接结论

1. **单人物闭环已实现并实测。** 同一人物走、慢跑、停留、面向目标、坐下 15 s、离座、改令、取消、暂停恢复与重置均有实际运行证据。完整生活流程经过三次独立启动；最终源码独立目录再次完成七步流程。
2. **当前最高完整功能档位为 {highest} 人。** 只有达到规定持续时间、每人完成至少一个角色周期、丰富度达标、无人停用且根几何检查通过的运行，才列入下表。更高人数或短种子观察不替代正式档位。
3. **人物池为 12 个基础人物、24 个已核对外观组合、7 类活动角色。** 12 个基础人物分别完成走、慢跑、坐下、离座与返回，24 个外观有同步人像联系表。外观材质变体没有被计作新的基础人物；规模表另列本次实际使用数量。
4. **Agent 能通过真实工具中途控制人物。** CLI 和 stdio MCP 共用本地桥；MCP 实测 18 个工具，含创建、活动、状态、事件、取消和镜头控制。Skill 调这些工具，Kit 主线程执行人物 API。事件和旧任务不能夺回手动改令后的控制权。
5. **性能与物理验证仍有明确限制。** 10 人标准广角测试 RTF 约 0.289，未达到 0.9 初始目标；30 人目标为 RTF 0.8 且实际 24 更新/墙钟秒，实际结果按下表报告。50 人只报告可达到的性能，没有另设虚构阈值。多人移动目标跟随仍为 blocked；机器人深度/LiDAR、接触力、人体受力平衡、精确全身 mesh 穿透和任意骨架自动兼容未验收。

## 完整人数结果

| 阶段 / 运行 | 实例 | 基础人物 / 外观 / 角色 | sim s | 每人最少周期 | RTF | 实际更新/墙钟秒 | 成功 / 失败 / 结束清理取消 |
| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
{chr(10).join(rows)}

结束清理取消是达到测量截止时仍在执行的活动，另列保留。失败、重试和恢复不会改写为成功。每个 summary 内含逐人距离、最高速度、周期、资源和失败原因；完整日志及录像保存在同名 `runs/` 目录。统计中的根胶囊重叠和跳变为几何代理，不是精确 mesh 或接触力证明。

实际移动参与要求人物在同一回合内离首个 ready 根位置超过 1 m，另存逐人最大位移；累计原地摆动和回合重置造成的位置变化不能用于凑参与人数。早期按累计路程统计的派生 summary 另存为 `acceptance_summary_cumulative_distance_v1.json`，原始轨迹始终保留。正式档位还要求全部人物完成角色周期。

| 实例 | 同层最小根间距 m | 原生路线有限重试次数 |
| ---: | ---: | ---: |
{chr(10).join(spatial)}

逐人的 `moving_sim_s`、`stationary_sim_s` 和 `native_action_time_sim_s` 按实际轨迹积分；两类时长之和等于采样覆盖时长。静止包含有意等待、坐姿、交通和过渡，不能直接当成拥堵。`max_contiguous_stationary_sim_s` 与实际事件一同定位长期停顿。预约分段会增加减速停顿，长巡视路线尤其明显；当前优先保留几何保护和可取消任务，未宣称达到自然人群的最终流畅度或实时性能。

{pressure}

## 补充种子观察

补充种子使用相同场景、人物池、活动类型、单台 1920×1080 RGB 和 30 Hz 仿真步长。30 人补充窗口为 450 sim s，短于正式 900 s；修正巡视停靠点后的 50 人附加种子要求完整 600 sim s。提前停止的旧观察也保留，不能代替完整窗口。每份 `seed_validation.json` 写明要求时长、全部检查和程序 SHA256，用于核对种子间的实际调度差异。

| 运行 | Seed | sim s | 检查结果 | 任务分布 |
| --- | ---: | ---: | --- | --- |
{chr(10).join(seeds)}

## 动作、工具和空间交互

- P0 使用本机 `6.2.0-rc.14+release.52805.02189a84.gl`，Behavior/Navigation 110.4.0；未换用 5.x 或 6.0 运行时。GPU 为 4×RTX A6000 48 GB，主存约 125 GiB。环境与绑定签名保存在 `environment_report.json`、`p0-native2/` 和各运行快照。
- 原生移动使用实际绑定的 `set_speed + move_to/move_along`。run 对应 MoveJog，目标速度 2.8 m/s；短路线包含加减速，实测并非始终为 2.8。P1 短程慢跑速度中位数 1.811 m/s、峰值 3.373 m/s，步态与关键关节另见 `gait_audit.json` 和连续近景。没有伪造 `agent.run()` 或 `stand_up()`。
- 座位通过租约、Hips、朝向、脚高、稳定时长联合判定；离座完成原生起身、走到让出位并停稳后才释放。队列 FIFO 前移，服务后让出；窄门和普通交汇使用实际空间预约。动态箱体最小根到表面距离分别为 0.504 m 和 0.714 m，后者覆盖箱体进入已预约路段后的刹停重规划。
- 原生避让单独运行出现过持续重叠，因此工业场景加入基于 NavMesh、实际人物占用与前方通行空间的预约。没有通过传送、写骨骼、隐藏或冻结人物排除拥堵。长工业移动显式设置 240 s 有限截止，普通手动移动默认 120 s；非预期 6 s 无进展保护仍在。
- 外部事件支持 robot_nearby、passage_blocked、call_person、region_closed，含优先级、去抖、安全边界和恢复。事件源由 Agent/外部系统提供，未虚构机器人检测器。
- Kit 扩展在当前 stage 的自有会话层和唯一命名空间内工作。加载、真实移动、原根图层保护、原对象保留和卸载清理已实测；已有场景仍需有效 NavMesh、语义标记与兼容资产。

逐项 T01–T16 入口见 [用例矩阵](ACCEPTANCE_MATRIX.md)。T14 外部 worker 故障不适用：本轮没有启用 MotionBricks/CrowdBricks。当前采集瓶颈主要在 Kit/渲染与 RGB 管线，没有证据说明引入批量动作生成 worker 就能达到实时目标。

## 性能和录像口径

标准工业档为 `industrial-wide-v2` 固定全景：26 mm 焦距、36×20.25 mm 画幅、(38,-48,62) m 机位，单台 1920×1080 RGB，30 Hz 仿真步长。投影检查覆盖完整 44 m 场地和人物头部，实际 RGB 另作复核。早期裁切画幅的功能结果不与该标准混合比较。

每档前 30 s wall 单列预热，之后至少 120 s wall 测量。机器上有其他 Isaac 进程，本项目的种子、演示和复现运行也可能并发；资源日志保留共享 GPU 总量。RSS/CPU 为当前 Kit 进程，外部 FFmpeg 编码器不包括在该进程 RSS 中。数据不代表独占机器的最高性能。

| 实例 | Kit/渲染中位 ms | 监督与几何中位 ms | 日志中位 ms | RGB/编码提交中位 ms | Kit 峰值 RSS GiB |
| ---: | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(timing_rows)}

上述区间来自主循环的实际墙钟计时；各区间中位数不能相加充当总时延分位数。Kit/渲染区间包含原生更新与同步渲染，尚未进一步拆出蒙皮、GPU 渲染和等待；RGB/编码提交不包含外部编码进程的全部 CPU 时间。下一步性能优化应先细分最大区间并验证采集时间对应关系，再比较优化前后同配置结果。队列 120 s 总预算和离座过渡失败仍需分别改进，不通过扩大截止时间掩盖长期堵塞。

{latency}

默认同步 CPU RGB 回读。非零 GPU 的 Warp 直回读曾失败，原日志保留；没有为了帧率启用未通过的异步帧归属。`raw_video.mp4` 使用仿真帧时间轴，`video_timestamps.jsonl` 保留每帧实际 sim/wall 时间；`raw_video_wallclock.mp4` 无损重封装为墙钟时间轴，逐包时间戳核验误差小于 22 微秒，不插帧。

演示导出按源帧编号选取，并独立核对全部解码后的时间戳。早期 VFR 快速 seek 剪辑定位有误，失败导出留在 `final-control-01/demo_export_attempt01/`，最终版不使用该方法。单人演示是一个连续区间，无内部剪切；多人演示逐段标注来源 run、人物与切镜。原始连续录像单独保留。

## 复现与交付

单人控制核心从 Git `ff98c71` 归档解出独立目录，重新定位 Behavior 缓存后实际运行 `single_life_cycle`：56.433 sim s，七步完成、0 失败，26 处缓存路径均指向新目录，Kit 原日志和原始录像完整。见 `runs/repro-final-01/reproduction_acceptance.json`。随后 `b57b123` 与 `8c2baca` 分别修正大组巡视和响应停靠点，保持默认 10/30 人原路径；修正后的 50 人完整运行与附加种子分别保存新版源码快照，不用旧种子的通过结论代替新版验证。种子 17 的新版启动还直接使用 `8c2baca` Git 归档解出的独立源码目录和独立控制端环境，最终通过与否见该运行的实际终态及复现审计。

{population_repro}

源码、CLI、MCP、Kit 扩展、Skill、配置、schema、测试和报告均在项目中。{test_count} 个协议、状态机、停靠点和参与统计回归测试通过；场景验收另外依赖上述原生轨迹与录像。退出清理信号转发也已真实验证，未终止用户其他 Isaac 进程。

源码包与证据包由 `scripts/package_delivery.py` 从已提交源码和已关闭运行生成，逐文件与压缩包均有 SHA256。模型/材质缓存和原有人物资产留在用户安装中，按 README 准备，不混入源码包。实际包名、大小和校验值见 `dist/delivery_manifest.json`。失败历史见 [失败与撤回记录](FAILURE_LEDGER.md)，不将失败重跑成同名证据。
'''
(ROOT/'reports/IMPLEMENTATION_REPORT.md').write_text(report)
print(ROOT/'reports/IMPLEMENTATION_REPORT.md')
