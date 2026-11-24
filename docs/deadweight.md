# 《死重》/ Deadweight

《换班时刻》的成片、生产入口、原生动作验收和公开版本保持独立。本片的资产和录像只保存在本地，不自动发布。

电影：海崖双车、游客变异、感染者登车成为配重、海鸥演员与摄影师隔窗举手、隔间外侧门逃生。88 秒，1920×1080、30 个真实渲染源帧/电影秒。36 个有独立身份的角色：23 名感染游客、12 名幸存者、1 名演员。角色引用现有授权人物，不分发模型。

## 控制方式与证据边界

- `deadweight_probe.py`：Isaac Sim 6.2、Behavior 110.4，正式人物的正常移动切换到原生导入的丧尸**原地**循环；逐帧采样全部 101 个关节。通过记录是 `runs/deadweight-zombie-probe-05`。
- `deadweight_native_boarding.py`：实际高 61.63 米的平台、真实门洞，六个独立角色顺序执行原生普通步行登车。`runs/deadweight-native-board-03` 的六项任务全部成功且停稳，录到 1,331 帧。它不证明原生丧尸步态导航、移动舱乘坐或 23 人原生自主登车。
- 电影采用从上述正式骨架实采的全身骨骼缓存，加入目标人物比例适配、脚尖接地代理、支撑足匹配位移、上身等候表演和导演手势。电影控制器独占根与骨骼。车厢移动通过单一父节点传递；不同时运行导航与随车根写入。
- 人物站稳、脚高和实际 USD 根位置决定独占站位与演出载荷；两处客门、隔间门闭合和独立司机放行共同决定启程。途中失去门接点会中止拍次。载荷参数、双车互补轨程和缓动曲线属于电影调度，不是铁路动力学认证。
- 海面、雨、倒灌水迹是程序化布景，没有宣称流体求解。足端是关节代理，不宣称足底接触力或全蒙皮无穿模。

## 本机重放

```bash
python3 scripts/prepare_deadweight_assets.py
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/deadweight_probe.py --run-id NEW_PROBE_ID --gpu 3
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/deadweight_native_boarding.py --run-id NEW_BOARD_ID --gpu 3
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/deadweight_film.py --run-id NEW_MOVIE_ID --shot full --gpu 3
python3 scripts/finish_deadweight.py --run-id NEW_MOVIE_ID --out productions/deadweight_new
```

电影默认读取已经关闭的 `runs/deadweight-zombie-probe-05` 骨骼缓存。新录制缓存用于制作前，需要在独立制作入口选择对应目录。每次运行必须使用新 ID，禁止覆盖失败拍次。

运行保留脚本快照、缓存输入散列、逐帧摄影机矩阵、人物身份/根/脚尖、门接点、载荷、仿真时间、故事帧和墙钟耗时。采集只有一个 Replicator 推进循环，等待渲染，RGB 使用已验证的 CPU 读回。

后期保留 0–2,579 连续源帧，最后 60 帧有意定格真实会车源帧；这段定格明确记入 `DELIVERY.json`。没有补帧或用重复帧冒充实时性能。音效与音乐由 `finish_deadweight.py` 原创合成，中文字幕、干净版、30 秒预告及原片证据分别保留。

## 本地资产

用户提供两个原始 ZIP。Quaternius 动作与 Poly Haven Coastal Cliff 02 的来源/许可文件随用户包保存；海鸥头罩来自用户提供的原创模型。人物和风暴 HDRI 引用本机 NVIDIA 资产安装。源码与资产、成片保持分离。
