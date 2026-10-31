# 《换班时刻》制作入口

第一版按用户消息中的 90 秒导演方案完成。用户随后提供本地制作包，本轮已读取原包 START_HERE.txt、shot_plan.json、blocking.svg、字幕和逐帧检查器，并按追加的动作丰富度要求制作独立的增强版。原包和第一版交付均保留。制作包 SHA256 为 `a4ccc1ec860e56780f1318007197638567f7090b121680ff5d340472e368b391`。

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

增强版使用 `--lively`：32 人，保留七类生活角色，增加八个热身/动作角色。走位避开活动区，专用热身区在短暂休息时保留预约，直至角色移动离开或被移除。除明确承担叙事任务的等候者外，访客、响应人员和跑者使用有限停留与循环活动。新增动作分别只在其已试拍的外观和本机运行时上验收，详情见 [原生自定义动作](custom_actions.md)。

核心机位在 44–68 秒固定；真正的指令触发额外检查两人最近两秒和最近半秒的实际西向位移。原 A 区程序先沿人物实际所在通道出发，避免为回到假定通道而先向东绕行。只有两人的走位都满足条件才向真实 Codex 发令；字幕、人物箭头与音乐降音使用实际触发帧。超时不满足就拒收拍次，不用切镜或后期改写轨迹。片中明示等待宿主调用时暂停仿真，墙钟等待时长与连接重试分列在交付记录中。

影片宿主将本地 SimPeople MCP 设为 required、启动超时 60 秒，并使用解析后的绝对可执行文件路径；文件沙箱仍为 read-only，仅给这个本地服务配置工具授权。可选 MCP 的初始工具目录有启动宽限，不能假定进程启动就已经挂载工具，见 [OpenAI MCP 配置说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

```bash
python3 scripts/capture_shift_change.py --phase director --lively --run-id unique-lively-director --gpu 3
python3 scripts/capture_shift_change.py --phase master --lively --run-id unique-lively-master --gpu 3
python3 scripts/finish_shift_change.py --run-id unique-lively-master --output productions/shift_change_v2
```

增强版做实际 SDR Rec.709 色彩矩阵和传递函数转换，同时写入对应标记，保留未转换的原始录像。输入假设为显示编码 sRGB，原录制器经 swscale 默认 BT.601 矩阵写入 YUV。另交付环境、音乐、脚步三条 48 kHz 分轨。公开视频发布须另获用户明确指示。
