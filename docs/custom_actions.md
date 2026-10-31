# 原生自定义动作

使用 `simpeople run/serve --custom-actions` 显式加载 `configs/custom_actions.json`。`animation://` 从 `SIMPEOPLE_ANIMATION_DIR`（默认 `assets/animations`）定位本地 Reallusion 素材目录，包含 AnimationRig_DS 与 DanceCard_DS。原始动画与人物资源不分发、不写回。

Kit 主线程通过 NVIDIA `ImportCustomActionCommand` 重定向至 Human Motion Library；播放使用 `BehaviorAgent.custom_action`。摄影机、HTTP worker 和后期都不写人物根或骨骼。导入产物只存本次 run 的 custom_actions/，每次启动独立；原生导入器的零起点采样边界被对齐，较低姿态有明确的离线竖直校准，翻身和蹲姿使用原地版本，避免外部位移随循环跳回。

`people_list_actions(actor_id=...)` 返回 custom_action.clips 中的名字与逐外观状态。只对源动画、导入配置/代码、人物 USD 和运行时版本均匹配的本地验收记录标记 verified。其他组合仍是 discovered；正常模式拒绝执行。`--allow-unverified` 仅用于原生动作试拍，不提升验收状态。

```json
{"actor_id":"dancer","steps":[{"action":"custom_action","target":"breakdance","duration_s":6},{"action":"move_to","target":"exit_a"}]}
```

可由 `people_run_activity`、`people_perform_action` 或 people_crowd 批量提交。target 必须是注册名，不接受文件路径、坐标或可执行代码。现有控制权、幂等请求、取消和任务终态仍适用。工业预约后端检查场地障碍和其他人物，并在播放前预约活动区；空间不足会明确失败，不能把受理当播放成功。专用 activity_bay 在动作间歇保持预约，移走/移除人物时释放。

本轮通过的八类为街舞翻身、伦巴、蹲姿活动、交替跪姿、地面拉伸、武术踢腿、俯身动作、站姿律动，每类验收一个指定外观。原生录像保存在 `runs/shift-actions-audition-06/`，25 秒动作后恢复行走，全部八项活动成功。`audit_custom_actions.py` 核对实际动作帧、终态、恢复位移、脚关节地面高度和已记录关节包络；这是有边界的功能与几何代理验收，不是全身三角形碰撞、力学平衡、完整跑酷导航或任意骨架兼容证明。跪姿也会抬脚，所以“双脚离地”统计本身不表示跳跃。

原旋转踢素材因持续悬空未采用，旧重定向的低姿脚部穿地和回位失败均保留在早期试拍；没有重标旧失败为通过。跳跃翻身来自已验收的街舞片段，不另声称翻越障碍、独立滚翻和整套跑酷均已支持。

原生接口依据本机 Behavior 110.4 实现与 [NVIDIA Behavior API](https://docs.omniverse.nvidia.com/kit/docs/behavior-simulation/110.1.1/behavior-simulation/api.html) 核对；实际能力以本机录像和轨迹为准。
