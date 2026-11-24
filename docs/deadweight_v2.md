# 《死重》V2 修复评审

本轮暂停 88 秒全片制作，交付 24 秒原速试片和针对性证据。入口为
`productions/deadweight_v2_review/START_HERE.html`，四页报告为同目录
`修复实施报告.pdf`。V1 成片、旧报告和《换班时刻》均保持独立。

## 实现

- `core/funicular.py`：SI 单位的一维理想张紧索配重动力学。质量账本按人物 ID 去重；空车、水箱和两侧乘客均计入惯量与重力差。门与独立放行控制驻车锁，运动中断门触发有限制动。定力积分在速度零点和限速点拆步；不使用导演位置曲线，也不通过钳制轨程伪造停车。
- `deadweight_v2_actor.py`：保留原制服蒙皮，按正式演员变形后的手顶点拟合短翼，使用手骨局部标定挂点；接地读取 `UsdSkel` 变形后的鞋底点。每次动画更改后清理并重建查询，避免误读缓存中的静止姿态。
- `deadweight_v2_set.py`：连续海岸、桥墩基础、分开的公共站台与隔间检修台；倾斜走行架与水平地板之间有可见支撑。轮角由单一动力学轨程驱动；独立检查读实际轮面/轨面顶点，不把指令角度填回观测。
- `deadweight_v2_director.py`：按输出帧驱动人物和摄影机。36 个身份使用 11 个基础人物。前三排分别贴窗、转头、擦窗，其余骨骼相位错开。人物是电影缓存编排，未替换为 Native 导航/乘车能力。
- `deadweight_v2_film.py`：每帧一次正时间步与一次零时间同步屏障；录制前用可见移动检测球测试 RGB/位姿归属，随后移除。逐帧保存全部关节、相机、轮角、源 RGB 散列及双时钟。拒绝近乎全黑的画面。

## 已关闭的证据

| 内容 | 运行 |
| --- | --- |
| 冻结 V1 归因、逐网格隐藏与恢复 | `deadweight-v2-attribution-02` |
| 1981 / 2570 同身体姿态修复 | `deadweight-v2-repair-1981-01` / `deadweight-v2-repair-2570-01` |
| 11 种制服与四动作九秒视频 | `deadweight-v2-wardrobe-03` |
| 海岸三个干燥/风雨锁机位 | `deadweight-v2-scene-03` |
| 质量、门、放行、制动反事实及轨面读回 | `deadweight-v2-rail-02` |
| 固定机位轮轨录像 | `deadweight-v2-rail-01` |
| 24 秒主体、轮轨与脱险复拍 | `deadweight-v2-trial-01` / `deadweight-v2-wheel-retake-03` / `deadweight-v2-escape-retake-01` |

`wheel-retake-01` 虽正常退出，但黑画面被人工复核拒绝；失败说明保留。
`wheel-retake-02` 画面可用但缺少清楚的双面轮标和对向车镜头，没有进入交付片。
最终四秒补拍保留同 tick 数值轨程，源帧映射见 `master_frame_map.jsonl`。
脱险段另修复了 Idle/Walk 瞬间切换：健康步行循环从 Native 稳定段实测为
42 帧，起步/停步混合姿态，3.3 米行程在检修台上停稳。原试拍保留。
会车与到站之间的旅行用硬切省略；没有加速、运动插帧或回拉到旧合影帧。
电影剪辑跳过的轮转整周不能靠局部解包的轮角重建；完整累积滚动检查使用
`deadweight-v2-rail-02/production_wheel_readbacks.jsonl` 的连续 120 Hz 记录。

## 复现

使用新 `run_id`，禁止覆盖旧拍次；每次入口冻结源码和相关输入。

```bash
PYTHONPATH=src python3 -m pytest -q tests
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/deadweight_v2_diagnose.py \
  --run-id NEW_ATTRIBUTION --pose-offset-frames -1 --gpu 3
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/deadweight_v2_review.py \
  --run-id NEW_SCENE --mode scene --gpu 3
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/deadweight_v2_rail.py \
  --run-id NEW_RAIL --gpu 3
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/deadweight_v2_film.py \
  --run-id NEW_BLOCKING --preview --gpu 3
```

电影入口明确引用已关闭的 `deadweight-zombie-probe-05` 骨骼缓存和
`deadweight-v2-rail-01` 数值轨迹。要替换输入，需要修改制作入口并重新冻结。
归因修复入口引用已关闭的 attribution-02 重放副本；这些文件不是独立分发的模型包。
`finish_deadweight_v2.py` 用于本次明确选择的两个拍次，保持帧数、PTS 和原速。

## 验收边界

本轮是“一维配重动力学、Isaac 渲染”，不是 PhysX 轮轨接触。质量是配置值；
鞋底残差是接地重构后的选定顶点一致性指标；不存在独立接触力证据。
没有升级原生丧尸导航、Native ride 或 Agent 端到端功能验收状态。
岩壁贴图重复与局部坡面基础轮廓仍需精修；严格受控的双玻璃/雨效性能消融未做。
真人静音盲看未做，状态保持 `not_measured`。先评审短片，再决定整片重渲。
