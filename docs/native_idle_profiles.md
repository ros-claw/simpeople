# 原生待机启动配置

专用 Kit 运行器支持 `--idle-profile default|basic`。默认 `default` 保留已安装 SDK 的待机菜单；`basic` 仅选择原生 `Idle`，可用于需要减少待机根漂移的受控运行。

```bash
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/kit_main.py \
  --scenario industrial_life --serve --traffic-profile corridor \
  --idle-profile basic --gpu 3 --port 8895 --run-id my-basic-idle-runtime
```

配置在 Behavior 扩展加载后、创建人物和 Play 前生效，影响该专用进程。它不在运行中夺取人物控制权，不写根或骨骼。启动时读取 SDK 的实际菜单，再设置并复读；菜单不可用或生效值不符会停止启动，不能静默回退后声称使用了基础 Idle。

每拍的 `sdk_idle_settings.json` 保存请求模式、原菜单和实际菜单，`environment.json` 同时记录。它是启动配置证据，不是对整个运行期间设置不变的认证。

已完成的独立探针中，基础 Idle 下两名演员在 40 秒等待内根漂移为零，实验性两秒头手保持及返回为 20/20；默认菜单对应结果分别出现漂移超限及六项任务失败。完整证据见[待机对照](../reports/ITERATION_20261114_IDLE_COUNTERFACTUALS.md)和[头手对照](../reports/ITERATION_20261114_GESTURE_STATIC.md)。正式 `kit_main.py` 新启动参数的实际宿主回归另行记录，不能用探针结果代替。

配置名称不承诺所有资产完全静止，也不认证接触、脚底或生成动作质量。它不会自动提高安装目录的头手保持上限；默认上限仍为 0.6 秒。两秒保持、更多资产及多人长期运行仍按各自范围验收。当前仅提供专用进程入口；加载到用户已有 stage 的扩展没有偷偷改变其全局待机设置。

头手能力已加入条件域选择逻辑：除匹配实际资产、动作库和 SDK 修订外，还须同时具有基础模式的启动回执、当前基础 Idle 菜单、固定 30 Hz 响应和零随机响应偏移，以及匹配执行代码 hash 的已验收记录。发现态候选只供显式未验证运行；设置变化、代码变化或缺失证据时保留原来的短时域。该选择逻辑的普通回归已通过，候选的原生发现态与严格态复测已排队，**安装目录尚未发布两秒条件域**。
