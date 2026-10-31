# 《换班时刻》制作入口

本轮按用户消息中的 90 秒导演方案制作。消息所附 ChatGPT Library ZIP 链接只返回登录页，本机未找到该 ZIP；没有声称读取过原包的 START_HERE.txt。这里的配置、脚本和帧检查器是依据消息内容实现的本地版本。

控制端使用编辑式安装 `python3 -m pip install -e '.[mcp,assets,video]'`，并需要 PATH 中的 ffmpeg/ffprobe、DejaVu 与 Noto CJK 字体。Kit 端沿用既有 Isaac Python 的 USD、Pillow 与原生扩展，不把控制端依赖混装进 Kit。

```bash
python3 scripts/capture_shift_change.py --phase technical --run-id unique-tech --gpu 0
python3 scripts/capture_shift_change.py --phase director --run-id unique-director --gpu 0
python3 scripts/analyze_shift_change.py runs/unique-director
python3 scripts/capture_shift_change.py --phase master --run-id unique-master --gpu 0
python3 scripts/analyze_shift_change.py runs/unique-master
python3 scripts/finish_shift_change.py --run-id unique-master
```

使用现有 Isaac 6.2、Behavior 110.4 原生后端、校准椅子和同步 RGB 录制。美术层保留原道路和三处队列，增加独立叙事服务点以及 B1/B2 设备，重新烘焙 NavMesh 并检查人物起点和故事目标。24 人分属七类角色。人物根和骨骼不由摄影机或后期脚本修改。

摄影机以源视频帧 `i / 30` 驱动；已有 follow 控制器在电影模式下不会执行。切镜预热暂停时间轴并核对原生根位置没有变化。背景活动由 Runtime 持续执行；只有两名主角的核心改派来自真实 Codex CLI + MCP。等候者任务及其余 22 人的控制版本在提交瞬间独立核对。

为了不把模型响应延迟伪装成实时，在实际指令准备点暂停仿真时间轴，等待真实工具提交后恢复。该墙钟等待保留在 `cinematic_agent_applied.json` 和宿主会话；暂停时不输出重复的保持帧。成片是仿真时间回放，不能用来声称实时渲染或即时模型响应。

核心段必须来自同一 run，仿真 tick 与视频源帧连续，摄影机固定；任务是否完成以原生状态和轨迹为准。字幕“已到达”只能在两人真实成功后出现。帧表记录 run、源帧、真实仿真 tick、墙钟时间与机位。`check_master.py` 解码检查每帧展示时间，包含“平均帧率正确但中间 PTS 偏移”的测试。

技术试拍、失败启动、重排走位与未采用素材均保留在 runs/。单位测试不代替原生镜头复看。交付包含主片、无字幕干净版、SRT/ASS、30 秒预告和 24 秒核心连续素材；原始会话与资产留本地。音乐和轨迹驱动的前景脚步 Foley 由本项目生成，脚步并非物理声学接触测量。没有新增长篇验收报告。
