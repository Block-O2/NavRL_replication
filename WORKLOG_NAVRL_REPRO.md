# NavRL 复现工作日志

日期：2026-04-17

这份日志记录当前 NavRL 复现推进状态、本地调整、验证脚本、训练结果和文本评估结果。目标是让后续调试可以从这里直接接上，而不是依赖截图或记忆。

## 当前可调整工作计划

状态说明：

- `[done]` 已完成并记录结果。
- `[doing]` 当前正在推进。
- `[next]` 建议下一步。
- `[blocked]` 暂时被环境或依赖阻塞。
- `[optional]` 可选增强项。

当前计划：

- `[done]` 完成 1024 / 350 / 80 GPU 50M 训练，并确认 `NO_CLOSE_EXIT` 与 checkpoint。
- `[done]` 建立 quick-demo 单步、单机器人、多机器人文本 evaluator。
- `[done]` 建立 ROS2-style 离线 evaluator。
- `[done]` 加入更强动态横穿场景 `path-crossing`。
- `[done]` 建立固定复现评估脚本 `quick-demos/run_repro_eval.sh`。
- `[done]` 做 author / own1500 / ownfinal 在 `path-crossing` 场景下的逐帧动作序列对比。
- `[done]` 回到训练代码阅读，重点查动态障碍分布、reward、termination、dynamic obstacle encoding 是否和作者部署一致。
- `[done]` 给干净 noeval0 训练入口增加默认关闭的 JSONL metrics 日志，方便后续继续训练时保留文本证据。
- `[done]` 给干净 noeval0 训练入口增加默认关闭的 checkpoint 加载参数，方便从 `checkpoint_1500.pt` 做短阶段继续训练。
- `[done]` 执行一次从 `checkpoint_1500.pt` 接续的 10M 短阶段训练，并保留 metrics。
- `[done]` 分析为什么 10M 接续训练没有改善 dynamic path-crossing，避免沿错误方向继续加长训练。
- `[done]` 添加默认关闭的 reward ablation 开关：碰撞惩罚、成功奖励/终止、动态障碍近距离停滞惩罚。
- `[done]` 跑一个 5M 定向 ablation：只打开动态障碍近距离停滞惩罚，验证是否能减少 `path-crossing` 中停在障碍路径上的坏行为。
- `[done]` 用固定离线 evaluator 对 ablation checkpoint 做 dynamic path-crossing 和 mixed 场景对比。
- `[done]` 备份当前关键 policy 到 GitHub：作者 checkpoint、自训练 baseline、自训练 `dynstopfinal`。
- `[done]` ROS2 链路做过最小辅助验证，但它不是当前主线。
- `[done]` 收敛到 policy 复现主线：确认候选 policy、固定评估命令、输出可解释结果。
- `[done]` 用固定 evaluator 做干净复跑，并把表格作为当前复现结论。
- `[done]` 对 `dynstopfinal` 做少量失败样本 trace，确认它不是偶然变好。
- `[done]` 新增干净 Isaac eval-only 入口，并完成四档 CPU eval matrix、小规模 GPU eval 诊断。
- `[next]` 评估是否需要继续训练；如果继续，应基于 `dynstopfinal` 或同类 reward 设计，而不是原始 reward 盲目加长。
- `[next]` 继续把 Isaac eval 扩大到更接近作者口径；GPU 路线必须先处理 reset / Direct GPU API 报错。
- `[optional]` ROS2/真机部署只保留为附录和后续工作，不再压过 policy 训练与验证主线。

计划会随着新证据调整；不要把这里当作固定路线图。

## 基本原则

- 不把“训练能跑完”当成“论文已经复现”。
- 优先使用文本日志、代码阅读、确定性探针和可复现脚本判断结果。
- 不重复 Isaac 重装、基础 smoke test 或已经验证过的启动检查。
- 按作者思路理解系统：作者发布的 policy 更像局部导航 / 避障策略，完整部署还包括障碍 gating、目标处理以及可选的 `safe_action`。

## 环境

- 代码仓库：`/home/ubuntu/projects/NavRL`
- 训练目录：`/home/ubuntu/projects/NavRL/isaac-training`
- Conda Python：`/home/ubuntu/miniconda3/envs/NavRL/bin/python`
- 当前可用 Isaac：
  - `ISAACSIM_PATH=$HOME/.local/share/ov/pkg`
  - `CARB_APP_PATH=$ISAACSIM_PATH/kit`
- 推荐运行方式：
  - `source $ISAACSIM_PATH/setup_conda_env.sh`
  - 需要时 unset proxy 环境变量
  - 使用 `/home/ubuntu/miniconda3/envs/NavRL/bin/python` 执行脚本

## 训练入口

优先使用下面两个干净脚本，不再使用历史上被多次 patch 的 `train_noclose.py`：

- `isaac-training/training/scripts/train_clean_noclose.py`
  - 基于原始 `train.py`。
  - checkpoint 输出保存在 repo 内。
  - 用 `NO_CLOSE_EXIT` 替代 `sim_app.close()`。

- `isaac-training/training/scripts/train_clean_noclose_noeval0.py`
  - 在上一个脚本基础上只额外跳过 step-0 eval：
    - 从 `if i % cfg.eval_interval == 0:`
    - 改为 `if i > 0 and i % cfg.eval_interval == 0:`
  - 支持 `+ckpt_dir=...` 指定 checkpoint 目录。

原因：

- 1024 / 350 / 80 的 GPU 训练主路径在跳过 step-0 eval 后可以跑。
- eval/reset 路径存在单独的 GPU Direct API / PhysX 兼容问题，不能和 PPO 训练主循环混为一谈。

## 当前 50M 训练

运行目录：

`/home/ubuntu/projects/NavRL/isaac-training/runs/navrl_1024_50m_20260417_policy_retry1`

最终 checkpoint：

`/home/ubuntu/projects/NavRL/isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_final.pt`

中间 checkpoint：

- `checkpoint_0.pt`
- `checkpoint_500.pt`
- `checkpoint_1000.pt`
- `checkpoint_1500.pt`
- `checkpoint_final.pt`

训练命令：

```bash
export ISAACSIM_PATH=$HOME/.local/share/ov/pkg
export CARB_APP_PATH=$ISAACSIM_PATH/kit
source $ISAACSIM_PATH/setup_conda_env.sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
cd $HOME/projects/NavRL/isaac-training
$HOME/miniconda3/envs/NavRL/bin/python training/scripts/train_clean_noclose_noeval0.py \
  headless=True \
  env.num_envs=1024 \
  env.num_obstacles=350 \
  env_dyn.num_obstacles=80 \
  max_frame_num=50000000 \
  eval_interval=999999 \
  save_interval=500 \
  wandb.mode=disabled \
  +ckpt_dir=$HOME/projects/NavRL/isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts \
  > $HOME/projects/NavRL/isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/logs/train.log 2>&1
```

结果：

- 日志里出现 `NO_CLOSE_EXIT`，说明正常结束。
- 已保存 `checkpoint_final.pt`。
- 最终日志关键词筛查未命中异常：
  - `Traceback`
  - `AttributeError`
  - `Segmentation fault`
  - `set_transforms`
  - `eENABLE_DIRECT_GPU_API`
  - `CUDA error`

大致耗时：

- 本地时间 2026-04-17 03:33:43 到 04:09:27。
- 约 36 分钟。

## 作者 checkpoint

已找到作者发布 checkpoint：

- `quick-demos/ckpts/navrl_checkpoint.pt`
- `ros1/navigation_runner/scripts/ckpts/navrl_checkpoint.pt`
- `ros2/navigation_runner/scripts/ckpts/navrl_checkpoint.pt`

三者 SHA-256 相同：

`51fa3dbdc6ba89626b5dad3a4638deb53d40aa6f0caa9b289657da4a8e0b60c3`

部署注意事项：

- 作者 checkpoint 可用于 demo 或集成验证。
- 但它本身不等于“可以直接安全上真机”。
- ROS2 完整路径还包括 odom、raycast/perception、动态障碍服务、目标逻辑和 `safe_action`。

## 代码级理解

来自 `quick-demos`、`ros2/navigation_runner` 和训练代码的结论：

- PPO 通过 Beta policy 输出 `agents/action_normalized`。
- `agents/action` 由 `action_normalized` 缩放并通过 `vec_to_world` 转到世界系。
- quick-demo 的 `Agent.plan()` 使用 `agents/action`。
- ROS2 部署逻辑：
  - 如果感知范围内没有障碍，直接朝目标速度前进；
  - 如果有障碍，调用 RL policy；
  - 然后可选调用 `safe_action`；
  - 接近目标时由外层控制逻辑减速或停止。

训练 reward / termination 注意点：

- `reach_goal` 目前主要作为统计量记录。
- 没有明确看到它作为 success reward 或 terminal condition 直接进入训练目标。
- 如果作者本意是训练局部避障策略，这可能是合理的。
- 因此 Isaac eval 里的 `reach_goal` 不能作为判断局部策略质量的唯一标准。

Eval 注意点：

- PPO 更新不依赖 eval。
- eval 是自动输出 `reach_goal/collision` 等指标的主要路径。
- GPU eval/reset 可能触发 PhysX / Direct GPU API 问题，这和训练 collector 能否工作是两个问题。

### 训练代码回读：环境、动态障碍和 reward

核心文件：

- `isaac-training/training/scripts/env.py`
- `isaac-training/training/scripts/ppo.py`
- `isaac-training/training/scripts/train_clean_noclose_noeval0.py`
- `isaac-training/third_party/OmniDrones/omni_drones/envs/isaac_env.py`
- `isaac-training/third_party/OmniDrones/omni_drones/utils/torchrl/collector.py`

训练 step 调用链：

```text
SyncDataCollector.rollout()
  -> IsaacEnv._step()
     -> NavigationEnv._pre_sim_step()
        -> drone.apply_action()
     -> sim.step()
     -> NavigationEnv._post_sim_step()
        -> move_dynamic_obstacle()
        -> lidar.update()
     -> _compute_state_and_obs()
     -> _compute_reward_and_done()
  -> PPO.train(data)
```

对应代码位置：

- `IsaacEnv._step()`：`isaac_env.py:263-272`
- `NavigationEnv._post_sim_step()`：`env.py:425-428`
- `NavigationEnv._compute_state_and_obs()`：`env.py:431-608`
- `NavigationEnv._compute_reward_and_done()`：`env.py:610-624`
- `PPO.train()` 读取 reward / terminated：`ppo.py:94-115`

动态障碍生成与移动：

- 训练配置默认 `env_dyn.num_obstacles=80`，速度范围 `[0.5, 1.5]`，局部目标范围 `[5.0, 5.0, 4.5]`。
- 动态障碍被分成 8 个类别：
  - 4 档宽度；
  - 2 档高度，区分 3D 浮空障碍和 2D 长柱障碍。
- 每个 step 后调用 `move_dynamic_obstacle()`。
- 动态障碍每约 2 秒重新采样速度，朝自己的局部随机目标移动。
- 障碍 pose 写回 Isaac 的位置在 `env.py:286-289`：

```text
dynamic_obstacle.write_root_state_to_sim(...)
dynamic_obstacle.write_data_to_sim()
dynamic_obstacle.update(...)
```

这也是 GPU eval / reset 路径里容易碰到 Direct GPU API / PhysX pose 更新问题的位置之一。

动态障碍 observation：

- PPO 只看最近 `dyn_obs_num=5` 个动态障碍。
- 每个动态障碍 10 维：

```text
relative_position_unit_in_goal_frame: 3
distance_2d_in_goal_frame: 1
distance_z_in_goal_frame: 1
velocity_in_goal_frame: 3
width_category: 1
height_category: 1
```

训练侧构造位置：

- `env.py:479-518`

ROS2 部署侧构造位置：

- `ros2/navigation_runner/scripts/navigation.py:313-340`

当前对照结果：

- 训练和 ROS2 的网络结构一致。
- 训练和 ROS2 的动态障碍 10 维字段顺序一致。
- 一个需要记住的差异：
  - 训练侧宽度分桶使用动态障碍自身宽度；
  - ROS2 部署侧先把动态障碍宽度加上 `robot_size * 2`，再做分桶。
- 这不一定是错误，因为作者 checkpoint 也是按这套 ROS2 逻辑部署；但它是解释自训练 policy 与作者 policy 差异时的重要边界。

reward 真正进入 PPO 的项：

```text
reward =
  reward_vel
  + 1
  + reward_safety_static
  + reward_safety_dynamic
  - 0.1 * penalty_smooth
  - 8.0 * penalty_height
```

其中：

- `reward_vel`：沿目标方向的世界速度投影。
- `reward_safety_static`：LiDAR 静态障碍安全距离 shaping。
- `reward_safety_dynamic`：最近动态障碍距离的 log shaping。
- `penalty_smooth`：速度变化惩罚。
- `penalty_height`：偏离起点/终点高度范围的惩罚。

重要问题：

- 碰撞大惩罚存在但被注释：

```text
# self.reward[collision] -= 50. # collision
```

- `reach_goal` 只写进 stats：

```text
self.stats["reach_goal"] = reach_goal.float()
```

- `reach_goal` 不进入 reward，也不进入 terminated。
- 当前 terminated 只包含：

```text
below_bound | above_bound | collision
```

所以，PPO 真正优化的是“朝目标方向移动，同时保持静态/动态安全距离和平滑高度”，不是显式优化“成功到达目标并结束 episode”。

这解释了当前现象：

- 训练能跑完，不等于复现成功。
- eval 的 `reach_goal` 是指标，不是训练目标。
- `ownfinal` 在动态横穿样本里“停在动态障碍路径上”，可能没有被足够强地压制：
  - 停下会损失 `reward_vel`；
  - 但不会立刻触发碰撞大惩罚，直到真正碰撞才终止；
  - 碰撞终止没有额外 `-50`；
  - 如果某些局部状态下停下能换来较高 safety shaping 或较低动作变化，策略可能学到保守但危险的局部行为。

训练期统计限制：

- 当前 50M run 的 `train.log` 只保留了 checkpoint 保存和结束标志。
- wandb offline 目录没有在 run 目录里找到。
- 因此这次训练缺少可回放的 train/reach_goal、train/collision、reward 分项曲线。
- 后续如果继续训练，应该先加最小文本日志或 CSV，把 reward 分项、collision、truncated、speed 记录下来；不要只保存 checkpoint。

## 新增验证脚本

### `quick-demos/policy_probe.py`

用途：

- 不依赖 Isaac 的单步 policy 探针。

## 训练入口最小 metrics 日志

调整文件：

```text
isaac-training/training/scripts/train_clean_noclose_noeval0.py
```

调整目的：

- 50M 训练已经证明可跑，但 `train.log` 没有保留足够的训练期文本指标。
- 下一次继续训练时，需要保留每个 PPO batch 的 return、collision、reach_goal、truncated、done rate 和 loss，避免只剩 checkpoint。
- 这一步只加默认关闭的日志能力和默认关闭的 checkpoint 加载能力，不改变默认训练行为。

具体改动：

- 增加 `import json`。
- 增加可选 Hydra 参数：

```text
+metrics_log=/path/to/metrics.jsonl
```

- 增加可选 Hydra 参数：

```text
+checkpoint=/path/to/checkpoint.pt
```

- 如果不传 `+metrics_log`，行为和之前一致。
- 如果传入，会每个训练 iteration 追加一行 JSON：
  - `step`
  - `env_frames`
  - `rollout_fps`
  - `loss/actor_loss`
  - `loss/critic_loss`
  - `loss/entropy`
  - `batch/stats.return`
  - `batch/stats.episode_len`
  - `batch/stats.reach_goal`
  - `batch/stats.collision`
  - `batch/stats.truncated`
  - `batch/done_rate`
  - `batch/terminated_rate`
  - `batch/truncated_rate`

验证：

```text
python3 -m py_compile isaac-training/training/scripts/train_clean_noclose_noeval0.py
```

结果：

- 语法检查通过。
- 没有启动 Isaac。
- 没有运行新的训练。

下一次短阶段继续训练建议：

- 起点：`checkpoint_1500.pt`，因为它在动态横穿场景比 `checkpoint_final.pt` 更稳。
- 目标：不是追求长训练，而是验证继续训练是否改善 dynamic path-crossing，同时不破坏静态/混合场景表现。
- 必须启用 `+metrics_log`，保留每个 batch 的文本证据。
- checkpoint 单独保存到新 run 目录，不覆盖已有 50M 结果。

命令模板：

```bash
export ISAACSIM_PATH=$HOME/.local/share/ov/pkg
export CARB_APP_PATH=$ISAACSIM_PATH/kit
source $ISAACSIM_PATH/setup_conda_env.sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
cd $HOME/projects/NavRL/isaac-training
$HOME/miniconda3/envs/NavRL/bin/python training/scripts/train_clean_noclose_noeval0.py \
  headless=True \
  env.num_envs=1024 \
  env.num_obstacles=350 \
  env_dyn.num_obstacles=80 \
  max_frame_num=10000000 \
  eval_interval=999999 \
  save_interval=100 \
  wandb.mode=disabled \
  +checkpoint=$HOME/projects/NavRL/isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_1500.pt \
  +ckpt_dir=$HOME/projects/NavRL/isaac-training/runs/<new_run_name>/ckpts \
  +metrics_log=$HOME/projects/NavRL/isaac-training/runs/<new_run_name>/logs/metrics.jsonl \
  > $HOME/projects/NavRL/isaac-training/runs/<new_run_name>/logs/train.log 2>&1
```

预期：

- 日志出现 `[CKPT] loaded checkpoint from ...checkpoint_1500.pt`。
- 日志出现 `[METRICS] writing jsonl metrics to ...metrics.jsonl`。
- 每个训练 batch 在 `metrics.jsonl` 里追加一行 JSON。
- 结束时出现 `NO_CLOSE_EXIT` 和新的 `checkpoint_final.pt`。

失败判断：

- 如果加载失败，优先看 checkpoint 路径和模型结构是否一致。
- 如果训练中出现 PhysX / Direct GPU API 错误，说明问题又进入 eval/reset 或动态障碍 pose 更新路径，需要和 PPO 更新分开看。
- 如果训练正常但 dynamic path-crossing 变差，说明继续训练方向不对，应该回到 reward / 分布设计，而不是加长训练。
- 使用固定的合成静态 / 动态障碍输入。
- 输出速度、forward/lateral 分量，以及动作来源 `DIRECT` 或 `RL`。

示例：

```bash
/home/ubuntu/miniconda3/envs/NavRL/bin/python quick-demos/policy_probe.py \
  --checkpoint quick-demos/ckpts/navrl_checkpoint.pt \
  --label author
```

### `quick-demos/policy_rollout_compare.py`

用途：

- 基于 quick-demo 几何逻辑的单机器人 2D rollout。
- 使用确定性随机种子对比不同 checkpoint。
- 模式：
  - `quickdemo`：始终使用 policy。
  - `ros-gated`：无障碍时直奔目标，有障碍时使用 RL。

示例：

```bash
/home/ubuntu/miniconda3/envs/NavRL/bin/python quick-demos/policy_rollout_compare.py \
  --mode quickdemo \
  --seeds 100 \
  --frames 300 \
  --device cpu \
  --policy author=quick-demos/ckpts/navrl_checkpoint.pt \
  --policy own50m=isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_final.pt
```

### `quick-demos/policy_multi_rollout_compare.py`

用途：

- 基于 `quick-demos/multi-robot-navigation.py` 的多机器人 / 动态障碍 rollout。
- 8 个机器人穿过静态障碍区域。
- 其他机器人会被编码成 dynamic obstacle。
- 统计指标：
  - `reach`
  - `static_col`
  - `robot_col`
  - `nonfinite`
  - `timeout`
  - `dyn_sanitized`

调整：

- 只在该验证脚本里加入 dynamic obstacle 清洗。
- 原因：quick-demo 的 `get_dyn_obs_state()` 在某些多机器人状态下会产生非有限 dynamic-obstacle tensor，并污染 policy 输出。
- 行为：非有限 dynamic obstacle 会计入 `dyn_sanitized`，并在进入 policy 前替换为 0。
- 这样可以避免把“输入编码 NaN”误判成“policy 自身坏了”。

调试参数：

```bash
--debug-nonfinite --show-failures
```

作用：打印第一次非有限 tensor 的细节。

### `quick-demos/policy_ros2_style_compare.py`

用途：

- 离线复刻 `ros2/navigation_runner/scripts/navigation.py` 的核心 `get_action()` 逻辑。
- 不导入或启动 ROS2。
- 使用 ROS2 的 `ppo.py` 和 ROS2 风格动作语义：
  - policy 输出 `action_normalized`；
  - evaluator 用 `vel_limit=1.0` 重新缩放；
  - 无障碍时直奔目标；
  - 有障碍时调用 RL policy；
  - 距离 `<= 1.0` 视为到达 / 停止，对齐 ROS2 近目标停止逻辑。

与真实 ROS2 部署的主要差异：

- 没有调用 `safe_action` 服务。
- raycast 是简化几何版本。
- 动态障碍是确定性合成障碍，不是 perception 输出。
- 默认假设机器人朝向已经和目标方向对齐。

常用参数：

```bash
--static-grid-div 10   # 默认静态障碍网格密度
--static-grid-div 0    # 关闭静态障碍
--dynamic-count 3      # 默认动态障碍数量
--dynamic-count 0      # 关闭动态障碍
--dynamic-layout side-crossing  # 默认动态障碍布局
--dynamic-layout path-crossing  # 动态障碍横穿机器人路径
--dynamic-layout head-on        # 动态障碍迎面接近
--route random                  # 随机起终点
--route corridor                # 固定走廊起终点
--safe-action          # 启用离线 safe_action 近似层
```

关于 `--safe-action`：

- 这是一个 Python 近似实现，用来模拟 ROS2 `safe_action_node` 的 ORCA/线性规划修正层。
- 参考文件：
  - `ros2/navigation_runner/srv/GetSafeAction.srv`
  - `ros2/navigation_runner/include/navigation_runner/safeAction.cpp`
  - `ros2/navigation_runner/include/navigation_runner/solver.h`
- 它不会启动 ROS2 service。
- 它使用 evaluator 内部的静态圆障碍和合成动态障碍近似生成约束。
- 因此它只能作为“safe_action 是否可能改变 RL 输出”的离线证据，不能等价于真实 ROS2 `safe_action_node`。

## Quick-Demo checkpoint 选择

已更新 quick-demo 可视化入口，支持自定义 checkpoint，同时保持原始默认行为：

- `quick-demos/agent.py`
- `quick-demos/simple-navigation.py`
- `quick-demos/random-navigation.py`
- `quick-demos/multi-robot-navigation.py`

默认行为：

```bash
/home/ubuntu/miniconda3/envs/NavRL/bin/python quick-demos/simple-navigation.py
```

仍然加载：

```text
quick-demos/ckpts/navrl_checkpoint.pt
```

显式指定 checkpoint：

```bash
/home/ubuntu/miniconda3/envs/NavRL/bin/python quick-demos/simple-navigation.py \
  --checkpoint /home/ubuntu/projects/NavRL/isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_1500.pt
```

也可以使用环境变量：

```bash
NAVRL_CHECKPOINT=/home/ubuntu/projects/NavRL/isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_final.pt \
  /home/ubuntu/miniconda3/envs/NavRL/bin/python quick-demos/simple-navigation.py
```

已做验证：

```text
python -m py_compile agent.py simple-navigation.py random-navigation.py multi-robot-navigation.py
```

也验证了 `Agent` 可直接加载：

- `checkpoint_1500.pt`
- 通过 `NAVRL_CHECKPOINT` 加载 `checkpoint_final.pt`

当前限制：

- 当前 `NavRL` conda 环境缺少 `matplotlib`。
- 因此 GUI demo 脚本暂时无法在该环境中显示窗口。
- 这不影响 policy 加载，也不影响纯文本 evaluator。

## Checkpoint 权重健康检查

检查过这些 checkpoint 是否包含 NaN/Inf：

- author
- own1000
- own1500
- ownfinal

结果：

```text
author   bad_tensors=0
own1000  bad_tensors=0
own1500  bad_tensors=0
ownfinal bad_tensors=0
```

解释：

- checkpoint 权重本身都是有限值。
- 之前多机器人 rollout 里看到的 `nonfinite` 来自 dynamic-obstacle 输入编码，不是 checkpoint 权重损坏。

## 单步 policy 探针结果

作者 checkpoint：

```text
front_static_close     vel=( 0.637,  1.792)
left_static_close      vel=( 0.016,  1.931)
right_static_close     vel=(-0.223,  1.942)
front_dynamic_cross    vel=(-1.316,  1.974)
static_and_dynamic     vel=( 1.652, -0.000)
```

自训练 50M final：

```text
front_static_close     vel=( 0.154,  1.553)
left_static_close      vel=( 0.856,  1.690)
right_static_close     vel=(-0.606,  1.489)
front_dynamic_cross    vel=(-0.804,  0.859)
static_and_dynamic     vel=(-1.245,  0.334)
```

解释：

- 自训练 50M policy 不是随机策略或死策略。
- 它会根据左 / 右 / 静态 / 动态障碍输入输出不同动作。
- 在部分动态 / 混合场景下看起来更保守。

## 单机器人 rollout 结果

Quickdemo 模式，100 seeds，300 frames：

```text
author             reach= 57/100 collision= 43/100 timeout=  0/100 avg_steps=  62.2 avg_final_dist=  3.740 min_clearance=  0.186 avg_path= 11.680
own50m             reach= 80/100 collision= 15/100 timeout=  5/100 avg_steps= 104.3 avg_final_dist=  1.352 min_clearance=  0.201 avg_path= 17.176
```

ROS-gated 模式，50 seeds，300 frames：

```text
author             reach= 24/50  collision= 26/50  timeout=  0/50  avg_steps=  55.8 avg_final_dist=  5.255 min_clearance=  0.186 avg_path= 10.527
own50m             reach= 35/50  collision= 10/50  timeout=  5/50  avg_steps= 107.4 avg_final_dist=  3.230 min_clearance=  0.201 avg_path= 18.840
```

解释：

- 在这些简化 2D 测试里，自训练 50M 的碰撞更少、到达更多。
- 它也更慢 / 更保守，路径更长，并且有一些 timeout。
- 这不能证明 Isaac 或真实部署成功。

## 多机器人 rollout 结果

加入 dynamic-obstacle 清洗后，5 seeds，300 frames，每个 seed 8 个机器人：

```text
author             reach=  15/40   static_col=  25/40   robot_col=   0/40   nonfinite=   0/40   timeout=   0/40   avg_steps= 117.4 avg_final_dist= 13.645 min_clearance=  0.177 avg_path= 22.645 dyn_sanitized=0
own1000            reach=  17/40   static_col=  10/40   robot_col=   0/40   nonfinite=   0/40   timeout=  13/40   avg_steps= 225.3 avg_final_dist=  6.765 min_clearance=  0.212 avg_path= 33.511 dyn_sanitized=0
own1500            reach=  32/40   static_col=   4/40   robot_col=   0/40   nonfinite=   0/40   timeout=   4/40   avg_steps= 234.7 avg_final_dist=  1.445 min_clearance=  0.217 avg_path= 38.535 dyn_sanitized=4
ownfinal           reach=  30/40   static_col=   2/40   robot_col=   0/40   nonfinite=   0/40   timeout=   8/40   avg_steps= 243.3 avg_final_dist=  1.303 min_clearance=  0.231 avg_path= 39.402 dyn_sanitized=90
```

解释：

- `checkpoint_1500.pt` 是当前更稳妥的主候选：
  - 在该简化多机器人测试中到达率高于作者 checkpoint；
  - 静态碰撞少；
  - dynamic-obstacle 清洗次数远少于 final。
- `checkpoint_final.pt` 也很强，但 `dyn_sanitized=90` 且 timeout 更多，因此不作为第一主候选。
- `checkpoint_1000.pt` 稳定但更保守，timeout 偏多。

当前候选排序：

1. `checkpoint_1500.pt`
2. `checkpoint_final.pt`
3. `checkpoint_1000.pt`

## ROS2-style 离线结果

静态 + 动态混合，20 seeds，300 frames：

```text
author             reach=  2/20  static_col= 17/20  dynamic_col=  1/20  timeout=  0/20  avg_steps=  71.6 avg_final_dist= 12.196 min_static=  0.249 min_dynamic=  0.229 avg_path=  7.025 rl_ratio= 1.00
own1000            reach=  4/20  static_col= 11/20  dynamic_col=  2/20  timeout=  3/20  avg_steps= 158.4 avg_final_dist=  8.639 min_static=  0.249 min_dynamic=  0.256 avg_path= 12.503 rl_ratio= 0.98
own1500            reach= 12/20  static_col=  3/20  dynamic_col=  1/20  timeout=  4/20  avg_steps= 200.7 avg_final_dist=  3.908 min_static=  0.276 min_dynamic=  0.291 avg_path= 18.141 rl_ratio= 0.99
ownfinal           reach= 14/20  static_col=  2/20  dynamic_col=  1/20  timeout=  3/20  avg_steps= 211.2 avg_final_dist=  2.500 min_static=  0.263 min_dynamic=  0.287 avg_path= 19.622 rl_ratio= 0.99
```

Static-only，10 seeds，300 frames：

```text
author             reach=  1/10  static_col=  9/10  dynamic_col=  0/10  timeout=  0/10  avg_steps=  67.9 avg_final_dist= 11.134 min_static=  0.249 min_dynamic=    inf avg_path=  6.718 rl_ratio= 1.00
own1500            reach=  7/10  static_col=  2/10  dynamic_col=  0/10  timeout=  1/10  avg_steps= 166.2 avg_final_dist=  4.949 min_static=  0.252 min_dynamic=    inf avg_path= 15.677 rl_ratio= 0.98
ownfinal           reach=  7/10  static_col=  2/10  dynamic_col=  0/10  timeout=  1/10  avg_steps= 179.6 avg_final_dist=  3.886 min_static=  0.279 min_dynamic=    inf avg_path= 16.842 rl_ratio= 0.98
```

Dynamic-only，10 seeds，300 frames：

```text
author             reach= 10/10  static_col=  0/10  dynamic_col=  0/10  timeout=  0/10  avg_steps= 175.1 avg_final_dist=  0.942 min_static=    inf min_dynamic=  1.173 avg_path= 17.447 rl_ratio= 0.21
own1500            reach= 10/10  static_col=  0/10  dynamic_col=  0/10  timeout=  0/10  avg_steps= 179.0 avg_final_dist=  0.956 min_static=    inf min_dynamic=  0.877 avg_path= 17.456 rl_ratio= 0.23
ownfinal           reach= 10/10  static_col=  0/10  dynamic_col=  0/10  timeout=  0/10  avg_steps= 178.9 avg_final_dist=  0.948 min_static=    inf min_dynamic=  0.621 avg_path= 17.446 rl_ratio= 0.23
```

解释：

- 在 ROS2-style 离线 evaluator 中，主要性能差异来自静态障碍处理。
- 合成 dynamic-only 场景太简单，所有测试 policy 都能 10/10 到达。
- 混合场景的数值结果更偏向 `checkpoint_final.pt`。
- 但综合多机器人 quick-demo 中的 dynamic-input 清洗次数，`checkpoint_1500.pt` 仍是更稳妥的主候选。
- 静态 / 混合测试中的 `rl_ratio` 接近 `1.0`，说明这些场景主要在测试 RL 局部策略，而不是 direct-goal fallback。

## ROS2-style + safe_action 近似结果

同一组 mixed 静态 + 动态场景，10 seeds，300 frames。

不启用 safe_action：

```text
author             reach=  1/10  static_col=  9/10  dynamic_col=  0/10  timeout=  0/10  avg_steps=  71.1 avg_final_dist= 10.886 min_static=  0.249 min_dynamic=  3.118 avg_path=  7.033 rl_ratio= 1.00 safe_ratio= 0.00 safe_delta=  0.000
own1500            reach=  7/10  static_col=  1/10  dynamic_col=  1/10  timeout=  1/10  avg_steps= 181.9 avg_final_dist=  4.745 min_static=  0.283 min_dynamic=  0.291 avg_path= 16.173 rl_ratio= 0.98 safe_ratio= 0.00 safe_delta=  0.000
ownfinal           reach=  8/10  static_col=  1/10  dynamic_col=  0/10  timeout=  1/10  avg_steps= 201.3 avg_final_dist=  2.553 min_static=  0.263 min_dynamic=  0.491 avg_path= 18.508 rl_ratio= 0.98 safe_ratio= 0.00 safe_delta=  0.000
```

启用 `--safe-action`：

```text
author             reach=  1/10  static_col=  9/10  dynamic_col=  0/10  timeout=  0/10  avg_steps=  71.4 avg_final_dist= 10.870 min_static=  0.267 min_dynamic=  3.118 avg_path=  7.053 rl_ratio= 1.00 safe_ratio= 0.04 safe_delta=  0.119
own1500            reach=  8/10  static_col=  0/10  dynamic_col=  1/10  timeout=  1/10  avg_steps= 204.9 avg_final_dist=  2.512 min_static=  0.377 min_dynamic=  0.291 avg_path= 18.607 rl_ratio= 0.98 safe_ratio= 0.07 safe_delta=  0.125
ownfinal           reach=  8/10  static_col=  1/10  dynamic_col=  0/10  timeout=  1/10  avg_steps= 195.4 avg_final_dist=  3.571 min_static=  0.286 min_dynamic=  0.470 avg_path= 17.528 rl_ratio= 0.99 safe_ratio= 0.10 safe_delta=  0.150
```

解释：

- 离线 `safe_action` 近似层对 `own1500` 有正向作用：
  - reach 从 `7/10` 到 `8/10`；
  - static collision 从 `1/10` 到 `0/10`；
  - 平均最终距离从 `4.745` 降到 `2.512`。
- 对 `ownfinal` 的作用较小：
  - reach 仍是 `8/10`；
  - static collision 仍是 `1/10`；
  - path 和 final distance 有变化，但不能说显著更好。
- `safe_ratio` 只有 `0.04-0.10`，说明该近似层只在少量步骤明显修改 RL 输出。
- 这进一步支持 `checkpoint_1500.pt` 作为主候选，因为它和安全层组合后表现更均衡。
- 该结论仍然只是离线近似，不能替代真实 ROS2 `safe_action_node` service。

## 更强动态障碍离线测试

目的：

- 之前的 dynamic-only 场景太简单，所有 policy 都能 `10/10` 到达，拉不开差距。
- 为了更稳妥地评估动态障碍能力，给 `policy_ros2_style_compare.py` 加了：
  - `--route corridor`
  - `--dynamic-layout path-crossing`
  - `--dynamic-layout head-on`

Path-crossing 动态-only，20 seeds，300 frames：

```bash
/home/ubuntu/miniconda3/envs/NavRL/bin/python quick-demos/policy_ros2_style_compare.py \
  --seeds 20 \
  --frames 300 \
  --device cpu \
  --static-grid-div 0 \
  --dynamic-count 5 \
  --dynamic-layout path-crossing \
  --route corridor \
  --policy author=quick-demos/ckpts/navrl_checkpoint.pt \
  --policy own1500=isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_1500.pt \
  --policy ownfinal=isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_final.pt
```

结果：

```text
author             reach= 20/20  static_col=  0/20  dynamic_col=  0/20  timeout=  0/20  avg_steps= 241.8 avg_final_dist=  0.961 min_static=    inf min_dynamic=  0.668 avg_path= 24.715 rl_ratio= 0.76 safe_ratio= 0.00 safe_delta=  0.000
own1500            reach= 16/20  static_col=  0/20  dynamic_col=  0/20  timeout=  4/20  avg_steps= 284.0 avg_final_dist=  1.216 min_static=    inf min_dynamic=  1.007 avg_path= 24.882 rl_ratio= 0.76 safe_ratio= 0.00 safe_delta=  0.000
ownfinal           reach= 14/20  static_col=  0/20  dynamic_col=  2/20  timeout=  4/20  avg_steps= 274.4 avg_final_dist=  1.912 min_static=    inf min_dynamic=  0.260 avg_path= 23.965 rl_ratio= 0.77 safe_ratio= 0.00 safe_delta=  0.000
```

Path-crossing + `--safe-action` 近似层：

```text
author             reach= 20/20  static_col=  0/20  dynamic_col=  0/20  timeout=  0/20  avg_steps= 241.7 avg_final_dist=  0.964 min_static=    inf min_dynamic=  0.846 avg_path= 24.711 rl_ratio= 0.76 safe_ratio= 0.01 safe_delta=  0.136
own1500            reach= 16/20  static_col=  0/20  dynamic_col=  0/20  timeout=  4/20  avg_steps= 283.6 avg_final_dist=  1.080 min_static=    inf min_dynamic=  1.009 avg_path= 24.940 rl_ratio= 0.75 safe_ratio= 0.02 safe_delta=  0.175
ownfinal           reach= 15/20  static_col=  0/20  dynamic_col=  2/20  timeout=  3/20  avg_steps= 273.5 avg_final_dist=  1.902 min_static=    inf min_dynamic=  0.243 avg_path= 24.036 rl_ratio= 0.76 safe_ratio= 0.03 safe_delta=  0.161
```

Head-on 动态-only，20 seeds，300 frames：

```text
author             reach= 20/20  static_col=  0/20  dynamic_col=  0/20  timeout=  0/20  avg_steps= 235.5 avg_final_dist=  0.943 min_static=    inf min_dynamic=  0.771 avg_path= 24.076 rl_ratio= 0.43 safe_ratio= 0.00 safe_delta=  0.000
own1500            reach= 20/20  static_col=  0/20  dynamic_col=  0/20  timeout=  0/20  avg_steps= 259.6 avg_final_dist=  0.952 min_static=    inf min_dynamic=  0.975 avg_path= 24.479 rl_ratio= 0.43 safe_ratio= 0.00 safe_delta=  0.000
ownfinal           reach= 20/20  static_col=  0/20  dynamic_col=  0/20  timeout=  0/20  avg_steps= 253.5 avg_final_dist=  0.952 min_static=    inf min_dynamic=  1.126 avg_path= 24.301 rl_ratio= 0.43 safe_ratio= 0.00 safe_delta=  0.000
```

解释：

- `path-crossing` 才真正拉开动态障碍差距。
- 作者 checkpoint 在该动态-only 场景里最强，`20/20` 到达且无动态碰撞。
- `checkpoint_1500.pt` 更保守，`16/20` 到达、`4/20` timeout，但没有动态碰撞，最小动态距离更大。
- `checkpoint_final.pt` 更激进，出现 `2/20` 动态碰撞。
- `--safe-action` 近似层只小幅改善 `checkpoint_final.pt` 的 timeout，未消除动态碰撞。
- `head-on` 场景三者都能通过，说明当前难点主要是横穿路径的动态障碍。
- 因此当前候选选择要更细分：
  - 静态障碍 / 混合离线：`checkpoint_1500.pt` 和 `checkpoint_final.pt` 都强；
  - 动态横穿障碍：`checkpoint_1500.pt` 比 final 更安全，但比作者更保守；
  - 如果目标是最稳，不应只看 mixed reach，应优先避免 dynamic collision，所以仍保留 `checkpoint_1500.pt` 为主候选。

## 固定复现评估脚本

为了让后续复现评估可重复，新增固定评估脚本：

```text
quick-demos/run_repro_eval.sh
```

作用：

- 一条命令重跑当前核心文本评估。
- 自动写入 `quick-demos/eval_outputs/` 下的时间戳日志。
- 不启动 Isaac。
- 不启动 ROS2。
- 不训练。
- 只做 CPU 离线 policy 推理和几何评估。

运行方式：

```bash
/home/ubuntu/projects/NavRL/quick-demos/run_repro_eval.sh
```

最近一次输出：

```text
/home/ubuntu/projects/NavRL/quick-demos/eval_outputs/repro_eval_20260417_201502.log
```

该脚本包含 4 组核心评估：

1. ROS2-style mixed，无 safe_action。
2. ROS2-style mixed，启用 safe_action 近似层。
3. ROS2-style dynamic path-crossing，无 safe_action。
4. ROS2-style dynamic path-crossing，启用 safe_action 近似层。

最近一次固定评估摘要：

```text
ROS2-style mixed, no safe_action
author    reach= 2/20  static_col=17/20  dynamic_col=1/20  timeout=0/20
own1000   reach= 4/20  static_col=11/20  dynamic_col=2/20  timeout=3/20
own1500   reach=12/20  static_col= 3/20  dynamic_col=1/20  timeout=4/20
ownfinal  reach=14/20  static_col= 2/20  dynamic_col=1/20  timeout=3/20

ROS2-style mixed, safe_action approximation
author    reach=1/10  static_col=9/10  dynamic_col=0/10  timeout=0/10
own1500   reach=8/10  static_col=0/10  dynamic_col=1/10  timeout=1/10
ownfinal  reach=8/10  static_col=1/10  dynamic_col=0/10  timeout=1/10

ROS2-style dynamic path-crossing, no safe_action
author    reach=20/20  dynamic_col=0/20  timeout=0/20
own1000   reach=11/20  dynamic_col=0/20  timeout=9/20
own1500   reach=16/20  dynamic_col=0/20  timeout=4/20
ownfinal  reach=14/20  dynamic_col=2/20  timeout=4/20

ROS2-style dynamic path-crossing, safe_action approximation
author    reach=20/20  dynamic_col=0/20  timeout=0/20
own1500   reach=16/20  dynamic_col=0/20  timeout=4/20
ownfinal  reach=15/20  dynamic_col=2/20  timeout=3/20
```

解释：

- `ownfinal` 在 mixed 场景 reach 更高，但有动态碰撞风险。
- `own1500` 在 dynamic path-crossing 场景无动态碰撞，但更保守、timeout 更多。
- 作者 checkpoint 在 dynamic path-crossing 上仍明显更接近目标复现表现。
- 因此如果目标是“最稳地接近作者复现”，当前应继续把 `checkpoint_1500.pt` 作为自训练主候选，同时承认它在动态横穿障碍上尚未达到作者 checkpoint。

## 历史 checkpoint 筛选

为了避免漏掉更接近作者动态表现的旧 checkpoint，额外筛过这些候选：

- `isaac-training/ckpts/checkpoint_19500.pt`
- `isaac-training/ckpts/checkpoint_final_5e6.pt`
- `isaac-training/training/ckpts/checkpoint_5000.pt`
- `isaac-training/training/ckpts/checkpoint_10000.pt`
- `isaac-training/training/ckpts/checkpoint_15000.pt`
- `isaac-training/training/ckpts/checkpoint_19500.pt`

筛选场景：

```text
ROS2-style dynamic path-crossing
seeds=10
frames=300
static_grid_div=0
dynamic_count=5
route=corridor
```

结果摘要：

```text
author             reach=10/10 dynamic_col=0/10 timeout=0/10
own1000            reach= 5/10 dynamic_col=0/10 timeout=5/10
own1500            reach= 7/10 dynamic_col=0/10 timeout=3/10
ownfinal           reach= 7/10 dynamic_col=0/10 timeout=3/10
hist_root_19500    reach= 7/10 dynamic_col=3/10 timeout=0/10
hist_root_5e6      reach= 5/10 dynamic_col=5/10 timeout=0/10
hist_train_5000    reach= 4/10 dynamic_col=6/10 timeout=0/10
hist_train_10000   reach= 2/10 dynamic_col=5/10 timeout=3/10
hist_train_15000   reach= 4/10 dynamic_col=6/10 timeout=0/10
hist_train_19500   reach= 4/10 dynamic_col=6/10 timeout=0/10
```

解释：

- 没有发现比 `own1500/ownfinal` 更适合作为自训练候选的历史 checkpoint。
- 历史长训 checkpoint 在这个动态横穿场景里普遍更激进，动态碰撞更多。
- 当前自训练主线仍应围绕 50M run 的 `checkpoint_1500.pt` / `checkpoint_final.pt` 做判断。

## 真实 ROS2 构建预检

目标：

- 检查当前服务器是否能继续构建真实 ROS2 `navigation_runner/safe_action_node`。
- 这一步是为了从 Python 近似 `safe_action` 推进到作者真实 C++ ROS2 service。

作者 README 对 ROS2 部署的要求：

- Ubuntu 22.04 LTS
- ROS2 Humble
- 将 `ros2` 目录复制到 ROS2 workspace 的 `src`
- 执行：

```bash
colcon build --symlink-install
```

本地代码结构：

- `ros2/map_manager`
- `ros2/onboard_detector`
- `ros2/navigation_runner`

`navigation_runner` 依赖：

- `rclcpp`
- `rclpy`
- `onboard_detector`
- `map_manager`
- `visualization_msgs`
- `geometry_msgs`
- `rosidl_default_generators`

真实 safe action 相关文件：

- `ros2/navigation_runner/srv/GetSafeAction.srv`
- `ros2/navigation_runner/src/safe_action_node.cpp`
- `ros2/navigation_runner/include/navigation_runner/safeAction.cpp`
- `ros2/navigation_runner/include/navigation_runner/safeAction.h`
- `ros2/navigation_runner/include/navigation_runner/solver.h`
- `ros2/navigation_runner/cfg/safe_action_param.yaml`

新增预检脚本：

```text
ros2/check_ros2_build_env.sh
```

该脚本只检查环境，不安装、不编译。

当前服务器预检结果：

```text
[NavRL ROS2 preflight] workspace: /home/ubuntu/projects/NavRL/ros2
MISS path /opt/ros/humble/setup.bash
MISS command colcon
MISS command ros2
MISS ROS_DISTRO is not set
[NavRL ROS2 preflight] package files:
OK   path /home/ubuntu/projects/NavRL/ros2/map_manager/package.xml
OK   path /home/ubuntu/projects/NavRL/ros2/onboard_detector/package.xml
OK   path /home/ubuntu/projects/NavRL/ros2/navigation_runner/package.xml
[NavRL ROS2 preflight] FAIL: source ROS2 Humble and install colcon before building.
```

解释：

- 当前服务器的 NavRL ROS2 源码包齐全。
- 但系统没有 ROS2 Humble 环境，也没有 `ros2` / `colcon` 命令。
- 因此现在不能在这台服务器上直接构建真实 `safe_action_node`。
- 这不是 NavRL 代码本身的编译错误，而是 ROS2 构建环境缺失。

如果后续要继续真实 ROS2 构建，需要先具备：

```bash
source /opt/ros/humble/setup.bash
colcon --help
ros2 --help
```

然后在 ROS2 workspace 中放入 `ros2` 包并运行：

```bash
colcon build --symlink-install
```

## `path-crossing` 逐帧动作序列对比

目标：

- 解释为什么 dynamic path-crossing 场景下作者 checkpoint 明显更稳。
- 不只看最终 reach / collision，而是对比碰撞前的最小动态障碍间距、动作方向、速度和 safe_action 介入情况。

新增脚本：

```text
quick-demos/policy_trace_compare.py
```

已生成 trace：

- `quick-demos/eval_outputs/path_crossing_trace_seed14_nosafe.csv`
- `quick-demos/eval_outputs/path_crossing_trace_seed15_nosafe.csv`
- `quick-demos/eval_outputs/path_crossing_trace_seed14_safe.csv`
- `quick-demos/eval_outputs/path_crossing_trace_seed15_safe.csv`

为什么重点看 seed 14 / 15：

- 这两个 seed 里，作者 checkpoint 和 `own1500` 都能通过。
- `ownfinal` 出现 dynamic collision。
- 因此它们比“大家都通过”或“大家都失败”的样本更能解释差距。

seed 14，无 safe_action：

```text
author   final=reached           min_clearance=0.668 @ frame 194
own1500  final=reached           min_clearance=1.638 @ frame 195
ownfinal final=dynamic_collision min_clearance=0.313 @ frame 189
```

关键动作差异：

- `author` 在进入 close range 后仍保持约 `0.95` 的横向动作和约 `1.17` 的速度。
- `own1500` 走得更保守，整个过程最小动态障碍间距仍有 `1.638`，没有进入 `< 1.5` 的近距离区间。
- `ownfinal` 在进入 close range 后速度迅速降到接近 `0`，并停在动态障碍路径附近；碰撞前动作约为 `(0.006, -0.004)`，几乎没有避让输出。

seed 15，无 safe_action：

```text
author   final=reached           min_clearance=0.820 @ frame 099
own1500  final=reached           min_clearance=1.589 @ frame 199
ownfinal final=dynamic_collision min_clearance=0.313 @ frame 191
```

关键动作差异：

- `author` 仍保持接近 `1.0` 的横向动作通过动态障碍区域。
- `own1500` 再次保持更远距离通过。
- `ownfinal` 再次在动态障碍路径附近减速到几乎停止，导致动态障碍追上或横穿撞到机器人。

safe_action 近似层检查：

```text
seed 14, safe_action=True
author     reached
own1500    reached
ownfinal   dynamic_collision

seed 15, safe_action=True
author     reached
own1500    reached
ownfinal   dynamic_collision
```

记录到的 `safe_adjusted` 次数为 0，说明当前 Python 近似 safe_action 没有在这两个样本中真正介入。这个现象可能来自近似 safe_action 的触发条件和真实 ROS2 C++ 服务仍有差异，不能直接当成真实 `safe_action_node` 的结论。

当前解释：

- `ownfinal` 的问题不是单纯“最后一层安全修正缺失”。
- 更像是 policy 在某些动态横穿状态下学到了错误局部行为：接近障碍时减速甚至停止，但停止位置仍在动态障碍路径上。
- `own1500` 虽然更保守、timeout 更多，但在动态横穿安全性上比 `ownfinal` 更适合作为当前自训练主候选。
- 作者 checkpoint 的通过方式更接近“持续横向通过动态障碍区”，这可能反映了作者训练分布或动态障碍编码更能支持横穿场景。

下一步：

- 回读训练代码里的动态障碍采样、动态障碍 observation 编码、reward 和 termination。
- 重点确认当前训练是否给了“停在动态障碍路径上”足够负反馈。
- 如果负反馈不足，再考虑最小训练目标修复；如果是分布不足，再考虑从 `checkpoint_1500.pt` 做小规模继续训练，而不是直接长跑。

## 从 `checkpoint_1500.pt` 接续 10M 短训练

目标：

- 验证“不改 reward、不改环境，只从当前最稳自训练候选 `checkpoint_1500.pt` 继续训练”是否能改善 dynamic path-crossing。
- 这不是长训，也不是最终复现声明；它是为了判断继续训练这个方向是否值得。

运行目录：

```text
isaac-training/runs/navrl_1024_continue1500_10m_20260417_metrics1
```

输入 checkpoint：

```text
isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_1500.pt
```

输出 checkpoint：

```text
checkpoint_0.pt
checkpoint_100.pt
checkpoint_200.pt
checkpoint_300.pt
checkpoint_final.pt
```

文本日志：

```text
isaac-training/runs/navrl_1024_continue1500_10m_20260417_metrics1/logs/train.log
isaac-training/runs/navrl_1024_continue1500_10m_20260417_metrics1/logs/metrics.jsonl
```

训练结果：

```text
[CKPT] loaded checkpoint from .../checkpoint_1500.pt
[NavRL]: model saved at training step: 0
[NavRL]: model saved at training step: 100
[NavRL]: model saved at training step: 200
[NavRL]: model saved at training step: 300
NO_CLOSE_EXIT
```

异常关键词筛查：

- 未命中 `Traceback`
- 未命中 `AttributeError`
- 未命中 `Segmentation fault`
- 未命中 `set_transforms`
- 未命中 `eENABLE_DIRECT_GPU_API`
- 未命中 `Exceeding maximum`
- 未命中 `CUDA error`

metrics 摘要：

```text
num_rows: 306
first: step=0   env_frames=32768    return=70.09    reach_goal=0.0041 collision=0.0
last:  step=305 env_frames=10027008 return=6672.99 reach_goal=0.4003 collision=0.0000916 truncated=0.000305
max_reach_goal: 0.6025
max_collision:  0.0006409
```

解释：

- 训练主路径正常。
- metrics 日志能力已验证可用。
- 训练期 `reach_goal` 在 batch stats 中上升，但这仍然只是训练环境 stats，不等价于论文复现成功。
- 由于 `reach_goal` 不进入 reward / termination，它不能单独证明策略学到了作者期望的动态避障行为。

接续训练后的 dynamic path-crossing 离线评估：

无 safe_action：

```text
author    reach=20/20 dynamic_col=0/20 timeout=0/20  min_dynamic=0.668
own1500   reach=16/20 dynamic_col=0/20 timeout=4/20  min_dynamic=1.007
cont300   reach=14/20 dynamic_col=1/20 timeout=5/20  min_dynamic=0.298
contfinal reach=14/20 dynamic_col=0/20 timeout=6/20  min_dynamic=0.302
```

启用 Python 近似 safe_action：

```text
author    reach=20/20 dynamic_col=0/20 timeout=0/20  min_dynamic=0.846
own1500   reach=16/20 dynamic_col=0/20 timeout=4/20  min_dynamic=1.009
cont300   reach=14/20 dynamic_col=0/20 timeout=6/20  min_dynamic=0.837
contfinal reach=14/20 dynamic_col=0/20 timeout=6/20  min_dynamic=0.853
```

结论：

- 这次 10M 接续训练没有改善 dynamic path-crossing。
- `cont300/contfinal` 比原始 `own1500` 更差，reach 更低、timeout 更多；无 safe_action 时 `cont300` 还出现 1 次 dynamic collision。
- 继续沿“同 reward、同分布、只加训练步数”的方向不值得。
- 当前仍保留 `own1500` 作为自训练主候选；作者 checkpoint 仍是动态横穿参考上限。

下一步调整：

- 不继续盲目加长训练。
- 回到训练目标和分布：
  - 碰撞大惩罚是否应该恢复；
  - `reach_goal` 是否应该作为局部任务的终止或奖励；
  - 是否需要针对 dynamic path-crossing / 停在障碍路径上的状态增加分布或负反馈；
  - 是否应先做很小的 ablation，而不是直接长训。

## Reward Ablation 开关

目标：

- 不改变作者默认训练逻辑。
- 允许用显式配置做最小 ablation，验证 reward / termination 是否是当前自训练 policy 动态横穿不足的原因。
- 所有开关默认关闭，因此默认行为仍与当前作者式训练目标一致。

调整文件：

```text
isaac-training/training/cfg/train.yaml
isaac-training/training/scripts/env.py
```

新增默认配置：

```yaml
reward:
  collision_penalty: 0.0
  success_reward: 0.0
  terminate_on_reach_goal: false
  dynamic_stop_penalty: 0.0
  dynamic_stop_distance: 1.0
  dynamic_stop_speed: 0.2
```

含义：

- `collision_penalty`：恢复或调整碰撞负奖励。默认 `0.0`，保持原代码中碰撞惩罚注释掉的行为。
- `success_reward`：给到达目标的状态额外奖励。默认 `0.0`。
- `terminate_on_reach_goal`：到达目标后是否终止 episode。默认 `false`。
- `dynamic_stop_penalty`：当机器人在动态障碍近距离内速度过低时扣分，用于测试“停在动态障碍路径上”这个失败模式。
- `dynamic_stop_distance`：触发停滞惩罚的动态障碍 2D 距离阈值。
- `dynamic_stop_speed`：触发停滞惩罚的机器人 2D 速度阈值。

验证：

```text
python3 -m py_compile isaac-training/training/scripts/env.py
python3 -m py_compile isaac-training/training/scripts/train_clean_noclose_noeval0.py
```

结果：

- 语法检查通过。
- 尚未说明 ablation 有效，只说明默认关闭的开关可以被编译。

第一个定向 ablation 计划：

- 起点：`checkpoint_1500.pt`。
- 训练长度：5M frames。
- 只打开：

```text
reward.dynamic_stop_penalty=1.0
reward.dynamic_stop_distance=1.2
reward.dynamic_stop_speed=0.2
```

为什么先测这个：

- 逐帧 trace 看到的主要失败模式是 `ownfinal` 在动态障碍靠近时速度降到接近 0，并停在动态障碍路径附近。
- 直接继续训练 10M 没有改善这个问题。
- 所以先用最小定向惩罚验证“停滞行为是否可被 reward 压住”，而不是马上改成功奖励或大范围重构环境。

成功应该看到：

- 训练正常 `NO_CLOSE_EXIT`。
- `metrics.jsonl` 正常增长。
- dynamic path-crossing 的 reach 不低于 `own1500`，dynamic collision 不增加。

失败怎么看：

- 如果训练崩，先按日志关键词区分 Isaac/PhysX 路径和 PPO 路径。
- 如果训练正常但 evaluator 变差，说明这个定向 reward 不该作为主线。
- 如果只减少 collision 但 timeout 增多，说明它只是更保守，不是真正复现作者动态穿越行为。

### Dynamic Stop Ablation 5M 结果

运行目录：

```text
isaac-training/runs/navrl_1024_ablate_dynstop_5m_20260418
```

启动配置：

```text
env.num_envs=1024
env.num_obstacles=350
env_dyn.num_obstacles=80
max_frame_num=5000000
eval_interval=999999
save_interval=50
reward.dynamic_stop_penalty=1.0
reward.dynamic_stop_distance=1.2
reward.dynamic_stop_speed=0.2
+checkpoint=.../navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_1500.pt
```

训练结果：

```text
[Reward Ablation] collision_penalty=0.0, success_reward=0.0, terminate_on_reach_goal=False, dynamic_stop_penalty=1.0, dynamic_stop_distance=1.2, dynamic_stop_speed=0.2
[CKPT] loaded checkpoint from .../checkpoint_1500.pt
[NavRL]: model saved at training step: 0
[NavRL]: model saved at training step: 50
[NavRL]: model saved at training step: 100
[NavRL]: model saved at training step: 150
NO_CLOSE_EXIT
```

输出 checkpoint：

```text
checkpoint_0.pt
checkpoint_50.pt
checkpoint_100.pt
checkpoint_150.pt
checkpoint_final.pt
```

metrics 末尾：

```text
step=152
env_frames=5013504
batch/stats.return=5643.3926
batch/stats.reach_goal=0.2772
batch/stats.collision=0.000244
batch/stats.truncated=0.000305
```

dynamic path-crossing，无 safe_action：

```text
author       reach=20/20 dynamic_col=0/20 timeout=0/20 min_dynamic=0.668
own1500      reach=16/20 dynamic_col=0/20 timeout=4/20 min_dynamic=1.007
dynstop150   reach=19/20 dynamic_col=0/20 timeout=1/20 min_dynamic=0.666
dynstopfinal reach=20/20 dynamic_col=0/20 timeout=0/20 min_dynamic=0.748
```

dynamic path-crossing，启用 Python 近似 safe_action：

```text
author       reach=20/20 dynamic_col=0/20 timeout=0/20 min_dynamic=0.846
own1500      reach=16/20 dynamic_col=0/20 timeout=4/20 min_dynamic=1.009
dynstop150   reach=20/20 dynamic_col=0/20 timeout=0/20 min_dynamic=0.895
dynstopfinal reach=20/20 dynamic_col=0/20 timeout=0/20 min_dynamic=0.871
```

ROS2-style mixed，无 safe_action：

```text
author       reach= 2/20 static_col=17/20 dynamic_col=1/20 timeout=0/20
own1500      reach=12/20 static_col= 3/20 dynamic_col=1/20 timeout=4/20
dynstop150   reach=15/20 static_col= 4/20 dynamic_col=0/20 timeout=1/20
dynstopfinal reach=15/20 static_col= 3/20 dynamic_col=0/20 timeout=2/20
```

ROS2-style mixed，启用 Python 近似 safe_action：

```text
author       reach= 2/20 static_col=18/20 dynamic_col=0/20 timeout=0/20
own1500      reach=14/20 static_col= 1/20 dynamic_col=1/20 timeout=4/20
dynstop150   reach=17/20 static_col= 1/20 dynamic_col=0/20 timeout=2/20
dynstopfinal reach=16/20 static_col= 2/20 dynamic_col=0/20 timeout=2/20
```

当前解释：

- `dynamic_stop_penalty` 这条假设被强支持：它直接针对 trace 里看到的“动态障碍靠近时停在障碍路径上”失败模式，并显著改善了 `path-crossing`。
- 与 10M 无改动继续训练不同，5M 定向 ablation 同时改善了 dynamic path-crossing 和 mixed 场景里的 dynamic collision。
- `dynstopfinal` 是当前最强自训练候选：
  - dynamic path-crossing 无 safe_action 达到 `20/20`；
  - mixed 无 safe_action 比 `own1500` reach 更高，dynamic collision 从 `1/20` 降到 `0/20`；
  - mixed safe_action 下 `dynstop150` reach 最高，`dynstopfinal` 也明显优于 `own1500` 的 dynamic collision。

边界：

- 这仍然是离线简化 evaluator，不是 Isaac eval，也不是完整 ROS2 真机部署。
- `dynamic_stop_penalty` 是复现调试中的最小修复假设，不一定是作者原始训练 reward。
- 如果目标是严格复现作者训练，应把这条改动作为 ablation 结果记录，而不是直接声称“作者就是这样训练的”。

下一步：

- 对 seed 14 / 15 这类旧失败样本做 trace 复查，确认 `dynstopfinal` 是否真的不再停在动态障碍路径上。
- 再补一轮多机器人 quick-demo 或固定 `run_repro_eval.sh`，确认没有明显场景回退。
- 如果要进入更接近最终复现的路线，应优先考虑把 `dynstopfinal` 接入作者 ROS2-style / safe_action 路径，而不是继续长训。

### Seed 14 / 15 Trace 复查

目标：

- 回到旧失败样本，确认 `dynstopfinal` 是否真的修掉了 `ownfinal` 的失败机制。
- 旧失败机制：动态障碍接近时速度降到接近 0，并停在动态障碍路径附近，最终 dynamic collision。

生成 trace：

```text
quick-demos/eval_outputs/path_crossing_trace_seed14_dynstop_compare.csv
quick-demos/eval_outputs/path_crossing_trace_seed15_dynstop_compare.csv
```

seed 14：

```text
author       final=reached           min_clr=0.668 first_slow_close=None win_speed=1.174 win_ay=0.955
own1500      final=reached           min_clr=1.638 first_slow_close=None
ownfinal     final=dynamic_collision min_clr=0.313 first_slow_close=181  win_speed=0.162 win_ay=0.139 speed@min=0.007
dynstopfinal final=reached           min_clr=1.413 first_slow_close=None win_speed=0.840 win_ay=0.838 speed@min=0.849
```

seed 15：

```text
author       final=reached           min_clr=0.820 first_slow_close=None win_speed=1.006 win_ay=0.964
own1500      final=reached           min_clr=1.589 first_slow_close=None
ownfinal     final=dynamic_collision min_clr=0.313 first_slow_close=183  win_speed=0.139 win_ay=0.123 speed@min=0.014
dynstopfinal final=reached           min_clr=1.234 first_slow_close=None win_speed=0.877 win_ay=0.837 speed@min=0.853
```

解释：

- `ownfinal` 在两个旧失败样本中都会进入 close range 后减速到几乎停止。
- `dynstopfinal` 在同样 seed 下保持横向速度，且没有 `first_slow_close`。
- 这说明 `dynamic_stop_penalty` 不是只让统计偶然变好，而是确实改变了之前观察到的失败动作模式。

### 固定评估脚本更新与复跑

调整文件：

```text
quick-demos/run_repro_eval.sh
```

调整内容：

- 如果本地存在 dynstop checkpoint，自动加入：
  - `dynstop150`
  - `dynstopfinal`
- 如果本地不存在这些 checkpoint，脚本仍可用，不会传入不存在的 policy 路径。
- `bash -n quick-demos/run_repro_eval.sh` 通过。

完整复跑日志：

```text
quick-demos/eval_outputs/repro_eval_20260418_003504.log
```

注意：

- 该日志在 `quick-demos/eval_outputs/` 下，当前被 `.gitignore` 忽略。
- 这次全量脚本候选更多，运行明显比单项 evaluator 慢；不要把中途长时间无输出误判成卡死。

固定脚本结果摘要：

ROS2-style mixed，无 safe_action：

```text
author       reach= 2/20 static_col=17/20 dynamic_col=1/20 timeout=0/20
own1000      reach= 4/20 static_col=11/20 dynamic_col=2/20 timeout=3/20
own1500      reach=12/20 static_col= 3/20 dynamic_col=1/20 timeout=4/20
ownfinal     reach=14/20 static_col= 2/20 dynamic_col=1/20 timeout=3/20
dynstop150   reach=15/20 static_col= 4/20 dynamic_col=0/20 timeout=1/20
dynstopfinal reach=15/20 static_col= 3/20 dynamic_col=0/20 timeout=2/20
```

ROS2-style mixed，safe_action 近似，10 seeds：

```text
author       reach=1/10 static_col=9/10 dynamic_col=0/10 timeout=0/10
own1500      reach=8/10 static_col=0/10 dynamic_col=1/10 timeout=1/10
ownfinal     reach=8/10 static_col=1/10 dynamic_col=0/10 timeout=1/10
dynstop150   reach=9/10 static_col=0/10 dynamic_col=0/10 timeout=1/10
dynstopfinal reach=9/10 static_col=0/10 dynamic_col=0/10 timeout=1/10
```

ROS2-style dynamic path-crossing，无 safe_action：

```text
author       reach=20/20 dynamic_col=0/20 timeout=0/20
own1000      reach=11/20 dynamic_col=0/20 timeout=9/20
own1500      reach=16/20 dynamic_col=0/20 timeout=4/20
ownfinal     reach=14/20 dynamic_col=2/20 timeout=4/20
dynstop150   reach=19/20 dynamic_col=0/20 timeout=1/20
dynstopfinal reach=20/20 dynamic_col=0/20 timeout=0/20
```

ROS2-style dynamic path-crossing，safe_action 近似：

```text
author       reach=20/20 dynamic_col=0/20 timeout=0/20
own1500      reach=16/20 dynamic_col=0/20 timeout=4/20
ownfinal     reach=15/20 dynamic_col=2/20 timeout=3/20
dynstop150   reach=20/20 dynamic_col=0/20 timeout=0/20
dynstopfinal reach=20/20 dynamic_col=0/20 timeout=0/20
```

结论：

- 固定脚本复跑支持前面的单项结论：`dynstopfinal` 是当前最强自训练候选。
- `dynstopfinal` 在 dynamic path-crossing 上追平作者 checkpoint 的 reach / collision / timeout。
- 在 mixed 场景里，`dynstopfinal` 没有出现 dynamic collision，但仍有静态碰撞和 timeout，说明它不是完整复现，只是显著推进了动态障碍部分。
- 这仍然是离线 ROS2-style 近似，不是 Isaac eval 或真实 ROS2 节点运行。

## 重要限制

- 这些 quick-demo rollout 不是 Isaac eval。
- 它们不是完整 ROS2 部署。
- 它们没有包含 `safe_action` 服务行为。
- 它们使用简化 2D 几何和碰撞检查。
- 作者 checkpoint 在这些简化测试里表现差，不等于作者 policy 本身差；这可能来自简化测试和论文 / 部署环境之间的差异。
- 自训练 policy 在这些测试里表现好，也不等于论文已经复现成功。

## 当前最佳判断

- 1024 / 350 / 80 GPU 训练在跳过 step-0 eval 后可用。
- 50M 训练产出了有意义的局部避障 policy。
- 原始 50M 里 `checkpoint_1500.pt` 仍是稳定 baseline；`checkpoint_final.pt` 是强竞争 baseline，但动态横穿有碰撞。
- 从 `checkpoint_1500.pt` 继续 10M，在当前 reward / 分布不变的情况下没有改善 dynamic path-crossing，因此不能把“继续加训练步数”作为主线。
- 5M `dynamic_stop_penalty` ablation 显著改善动态横穿；`dynstopfinal` 是当前最强自训练候选。
- `dynstopfinal` 在 ROS2-style dynamic path-crossing 上达到 `20/20` reach、`0/20` dynamic collision、`0/20` timeout；mixed 场景 dynamic collision 也降为 `0/20`。
- 当前主要缺口不是“能不能训练”，而是证明候选 policy 的改善是否稳定、可解释，并尽量靠近作者评估逻辑。
- ROS2/真机链路是后续部署问题，不再作为当前 policy 复现主线。

## 建议下一步

1. 使用 `dynstopfinal` 作为当前自训练主候选。
2. 保留 `checkpoint_1500.pt` 作为无 ablation 稳定 baseline。
3. 保留 `checkpoint_final.pt` / `checkpoint_1000.pt` 作为对照 baseline。
4. 不要直接启动 1.2B 长训练；当前收益来自定向 reward 修复，不是单纯加长训练。
5. 下一步优先做 trace/失败样本复查，确认 `dynstopfinal` 是否真的消除了“停在动态障碍路径上”的失败模式。
6. 只有在 policy 评估结论稳定后，再考虑更接近作者部署路径的 ROS2/真机验证。

## 2026-04-18 主线固定评估复跑

目的：

- 把复现主线收回到 policy 本身：训练产物、固定 evaluator、可解释指标。
- 不再把 ROS2 synthetic 工具作为主证据。
- 用同一固定脚本复跑作者 checkpoint、50M baseline、`dynamic_stop_penalty` ablation。

命令：

```bash
PYTHON_BIN=/home/ubuntu/miniconda3/envs/NavRL/bin/python \
quick-demos/run_repro_eval.sh
```

输出日志：

```text
quick-demos/eval_outputs/repro_eval_20260418_235513.log
```

### Mixed 场景，无 safe_action

```text
author       reach= 2/20 static_col=17/20 dynamic_col=1/20 timeout=0/20
own1000      reach= 4/20 static_col=11/20 dynamic_col=2/20 timeout=3/20
own1500      reach=12/20 static_col= 3/20 dynamic_col=1/20 timeout=4/20
ownfinal     reach=14/20 static_col= 2/20 dynamic_col=1/20 timeout=3/20
dynstop150   reach=15/20 static_col= 4/20 dynamic_col=0/20 timeout=1/20
dynstopfinal reach=15/20 static_col= 3/20 dynamic_col=0/20 timeout=2/20
```

### Mixed 场景，safe_action 近似

```text
author       reach=1/10 static_col=9/10 dynamic_col=0/10 timeout=0/10
own1500      reach=8/10 static_col=0/10 dynamic_col=1/10 timeout=1/10
ownfinal     reach=8/10 static_col=1/10 dynamic_col=0/10 timeout=1/10
dynstop150   reach=9/10 static_col=0/10 dynamic_col=0/10 timeout=1/10
dynstopfinal reach=9/10 static_col=0/10 dynamic_col=0/10 timeout=1/10
```

### Dynamic path-crossing，无 safe_action

```text
author       reach=20/20 static_col=0/20 dynamic_col=0/20 timeout=0/20
own1000      reach=11/20 static_col=0/20 dynamic_col=0/20 timeout=9/20
own1500      reach=16/20 static_col=0/20 dynamic_col=0/20 timeout=4/20
ownfinal     reach=14/20 static_col=0/20 dynamic_col=2/20 timeout=4/20
dynstop150   reach=19/20 static_col=0/20 dynamic_col=0/20 timeout=1/20
dynstopfinal reach=20/20 static_col=0/20 dynamic_col=0/20 timeout=0/20
```

### Dynamic path-crossing，safe_action 近似

```text
author       reach=20/20 static_col=0/20 dynamic_col=0/20 timeout=0/20
own1500      reach=16/20 static_col=0/20 dynamic_col=0/20 timeout=4/20
ownfinal     reach=15/20 static_col=0/20 dynamic_col=2/20 timeout=3/20
dynstop150   reach=20/20 static_col=0/20 dynamic_col=0/20 timeout=0/20
dynstopfinal reach=20/20 static_col=0/20 dynamic_col=0/20 timeout=0/20
```

结论：

- `dynstopfinal` 是当前最强自训练候选。
- 在 dynamic path-crossing 上，`dynstopfinal` 追平作者 checkpoint：`20/20 reach`、`0/20 dynamic_col`、`0/20 timeout`。
- 相比 `own1500`，`dynstopfinal` 主要改善了 timeout 和动态障碍风险。
- mixed 场景仍有静态碰撞和 timeout，说明它不是完整复现成功。
- 作者 checkpoint 在 mixed 简化 evaluator 里表现差，不应解读为作者 policy 差；它更说明这个 evaluator 只适合作为本地对照，不是论文指标。

下一步：

1. 做少量 trace，重点看 `own1500` timeout 和 `ownfinal` dynamic collision 的失败样本，确认 `dynstopfinal` 为什么改善。
2. 如果 trace 支持当前判断，下一步才考虑继续训练或更正式的 Isaac/eval 修复。
3. 不再扩展 ROS2 synthetic 工具，除非进入真机部署阶段。

## 2026-04-18 Path-crossing 失败样本 trace

目的：

- 不是再扩大测试范围，而是解释固定评估里 `dynstopfinal` 为什么更好。
- 对比三个 policy：
  - `own1500`
  - `ownfinal`
  - `dynstopfinal`
- 场景固定为 dynamic path-crossing，无 safe_action，20 个 seed。

命令核心：

```bash
/home/ubuntu/miniconda3/envs/NavRL/bin/python quick-demos/policy_trace_compare.py \
  --seed <0..19> \
  --frames 300 \
  --device cpu \
  --policy own1500=isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_1500.pt \
  --policy ownfinal=isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_final.pt \
  --policy dynstopfinal=isaac-training/runs/navrl_1024_ablate_dynstop_5m_20260418/ckpts/checkpoint_final.pt
```

本地输出：

```text
quick-demos/eval_outputs/path_crossing_trace_dynstop_mainline_20260418.txt
quick-demos/eval_outputs/path_crossing_trace_seed*_mainline.csv
```

这些输出在 `.gitignore` 下，不提交，只把结论写入日志。

### 关键失败 seed

`own1500` timeout：

```text
seed 0:  own1500 timeout, final_dist=1.604; dynstopfinal reached, final_dist=0.982
seed 1:  own1500 timeout, final_dist=2.056; dynstopfinal reached, final_dist=0.934
seed 8:  own1500 timeout, final_dist=1.623; dynstopfinal reached, final_dist=0.982
seed 17: own1500 timeout, final_dist=3.657; dynstopfinal reached, final_dist=0.976
```

`ownfinal` timeout：

```text
seed 1:  ownfinal timeout, final_dist=1.864; dynstopfinal reached, final_dist=0.934
seed 8:  ownfinal timeout, final_dist=1.254; dynstopfinal reached, final_dist=0.982
seed 9:  ownfinal timeout, final_dist=1.061; dynstopfinal reached, final_dist=0.952
seed 11: ownfinal timeout, final_dist=1.290; dynstopfinal reached, final_dist=0.967
```

`ownfinal` dynamic collision：

```text
seed 14: ownfinal dynamic_collision, final_dyn_clearance=0.260; dynstopfinal reached, final_dyn_clearance=6.543
seed 15: ownfinal dynamic_collision, final_dyn_clearance=0.263; dynstopfinal reached, final_dyn_clearance=6.496
```

### Trace 结论

- `dynstopfinal` 在 20 个 path-crossing seed 上全部 reached。
- 它不是只靠“撞了但最后统计变好”；在 `ownfinal` 真正动态碰撞的 seed 14/15，`dynstopfinal` 的最终动态 clearance 都大于 6。
- `own1500` 的主要问题是 timeout，尤其 seed 0/1/8/17；`dynstopfinal` 在这些 seed 都能进入目标半径。
- 这支持当前判断：`dynamic_stop_penalty` 不是偶然改善单个统计项，而是在横穿动态障碍场景里减少停滞/危险路径。

限制：

- 这仍然是 `quick-demos` 的 2D 离线 trace，不是 Isaac eval。
- 不能把它直接等同于论文复现成功。
- 它足以支持下一步：把 `dynstopfinal` 作为当前自训练主候选，而不是继续围绕 `own1500` 长训。

下一步：

1. 如果要继续训练，应基于 `dynstopfinal` 或同类 reward 设计，而不是回到原始 reward 盲目加长。
2. 更正式的复现需要恢复/替代 Isaac eval 的 GPU reset 问题，产出接近作者评估口径的文本指标。
3. 暂时不再扩展 ROS2 synthetic 工具。

## 2026-04-19 干净 Isaac eval-only 入口

目的：

- 回到 policy 复现主线，避免只依赖 quick-demo 近似 evaluator。
- 新增一个干净的 Isaac eval-only 入口，支持任意 checkpoint 路径，输出文本 JSON 指标。
- 不使用历史 `training/scripts/eval.py`，因为它硬编码了旧 checkpoint，且最后会 `sim_app.close()`。

新增文件：

```text
isaac-training/training/scripts/eval_clean_noclose.py
```

脚本行为：

- 启动 `SimulationApp`；
- 构建 `NavigationEnv + VelController + PPO`；
- 通过 `+checkpoint=/abs/path/to/checkpoint.pt` 加载 policy；
- 调用 `utils.evaluate()`；
- 打印 `[EVAL-JSON] {...}`；
- 最后打印 `NO_CLOSE_EXIT`，不调用 `sim_app.close()`。

踩坑修复：

- 第一次用 `checkpoint=...` 会被 Hydra 拒绝，正确写法是 `+checkpoint=...`。
- `PPO` 类把 `train()` 用作 PPO 更新函数，因此不能调用 `policy.eval()`；否则会触发：

```text
TypeError: 'bool' object is not subscriptable
```

- 已删除 `policy.eval()`，和训练脚本保持一致。

小规模 CPU eval 验证：

```bash
export ISAACSIM_PATH=$HOME/.local/share/ov/pkg
export CARB_APP_PATH=$ISAACSIM_PATH/kit
source $ISAACSIM_PATH/setup_conda_env.sh
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
cd /home/ubuntu/projects/NavRL/isaac-training

/home/ubuntu/miniconda3/envs/NavRL/bin/python training/scripts/eval_clean_noclose.py \
  headless=True \
  device=cpu \
  sim.device=cpu \
  sim.use_gpu=False \
  sim.use_gpu_pipeline=False \
  env.num_envs=16 \
  env.num_obstacles=40 \
  env_dyn.num_obstacles=10 \
  env.max_episode_length=300 \
  wandb.mode=disabled \
  +checkpoint=/home/ubuntu/projects/NavRL/policies/dynstopfinal_20260418/checkpoint_final.pt
```

运行注意：

- Isaac eval 必须在沙箱外运行；沙箱内会出现 no CUDA / Kit cache read-only 等误导性问题。
- 本次使用 CPU、小规模、短 episode，只验证入口和指标输出，不作为正式复现结果。

结果：

```text
[EVAL-STATS-RAW] {
  'eval/stats.collision': 0.0,
  'eval/stats.episode_len': 300.0,
  'eval/stats.reach_goal': 0.0625,
  'eval/stats.return': 1573.6507568359375,
  'eval/stats.truncated': 1.0
}

[EVAL-JSON] {
  "eval/stats.collision": 0.0,
  "eval/stats.episode_len": 300.0,
  "eval/stats.reach_goal": 0.0625,
  "eval/stats.return": 1573.6507568359375,
  "eval/stats.truncated": 1.0
}

NO_CLOSE_EXIT
```

解释：

- 入口有效：checkpoint 加载、rollout、stats 输出都成功。
- 这不是正式指标：`num_envs=16`、`num_obstacles=40`、`env_dyn.num_obstacles=10`、`max_episode_length=300` 都远小于作者式配置。
- 但它提供了后续扩大 Isaac eval 的干净起点。

下一步：

1. 继续扩大 Isaac eval 到更接近作者口径。
2. GPU eval 路线必须优先处理 reset / Direct GPU API 报错。
3. 如果短期内不能修 GPU eval，则可以先用 CPU eval 做较小规模但更干净的 policy 对照。

### 中等规模 CPU Isaac eval matrix

目的：

- 用同一个干净 Isaac eval-only 入口比较作者 checkpoint、50M baseline 和当前自训练候选。
- 仍然使用 CPU，是为了绕开 GPU Direct API / reset 问题，先取得干净文本指标。
- 这一步不是正式论文指标，只是比 quick-demo 更接近训练环境的 Isaac 侧对照。

配置：

```text
device=cpu
sim.device=cpu
sim.use_gpu=False
sim.use_gpu_pipeline=False
env.num_envs=32
env.num_obstacles=80
env_dyn.num_obstacles=20
env.max_episode_length=400
```

输出目录：

```text
isaac-training/runs/eval_clean_cpu_matrix_32_80_20_400_20260419
```

结果：

```text
author:
[EVAL-JSON] {"eval/stats.collision": 0.03125, "eval/stats.episode_len": 392.96875, "eval/stats.reach_goal": 0.09375, "eval/stats.return": 2081.90087890625, "eval/stats.truncated": 0.96875}
NO_CLOSE_EXIT

own1500:
[EVAL-JSON] {"eval/stats.collision": 0.03125, "eval/stats.episode_len": 394.96875, "eval/stats.reach_goal": 0.03125, "eval/stats.return": 2007.0126953125, "eval/stats.truncated": 0.96875}
NO_CLOSE_EXIT

dynstopfinal:
[EVAL-JSON] {"eval/stats.collision": 0.0, "eval/stats.episode_len": 400.0, "eval/stats.reach_goal": 0.125, "eval/stats.return": 2029.7965087890625, "eval/stats.truncated": 1.0}
NO_CLOSE_EXIT
```

解释：

- 三个 checkpoint 都能通过同一 Isaac eval-only 入口完成 rollout。
- `dynstopfinal` 在这个 CPU matrix 里 collision 最低，为 `0.0`。
- `dynstopfinal` 的 reach_goal 最高，为 `0.125`，但绝对值仍低，且多数 episode truncate。
- `author` 的 return 最高，但 collision 非零；这说明 return、reach_goal、collision 不能单独看，需要结合作者训练目标理解。
- 这一步支持把 `dynstopfinal` 继续作为当前自训练主候选，但还不能宣称正式复现成功。

### 更大一档 CPU Isaac eval matrix

目的：

- 在 CPU 路径继续扩大规模，看看结论是否稳定。
- 这仍然不是作者默认 `1024 / 350 / 80`，但比上一档更接近正式配置。

配置：

```text
device=cpu
sim.device=cpu
sim.use_gpu=False
sim.use_gpu_pipeline=False
env.num_envs=64
env.num_obstacles=160
env_dyn.num_obstacles=40
env.max_episode_length=500
```

输出目录：

```text
isaac-training/runs/eval_clean_cpu_matrix_64_160_40_500_20260419
```

结果：

```text
author:
[EVAL-JSON] {"eval/stats.collision": 0.046875, "eval/stats.episode_len": 492.90625, "eval/stats.reach_goal": 0.15625, "eval/stats.return": 2579.117431640625, "eval/stats.truncated": 0.953125}
NO_CLOSE_EXIT

own1500:
[EVAL-JSON] {"eval/stats.collision": 0.09375, "eval/stats.episode_len": 483.6875, "eval/stats.reach_goal": 0.09375, "eval/stats.return": 2436.59765625, "eval/stats.truncated": 0.90625}
NO_CLOSE_EXIT

dynstopfinal:
[EVAL-JSON] {"eval/stats.collision": 0.03125, "eval/stats.episode_len": 493.890625, "eval/stats.reach_goal": 0.109375, "eval/stats.return": 2551.800537109375, "eval/stats.truncated": 0.96875}
NO_CLOSE_EXIT
```

解释：

- 三个 checkpoint 在更大 CPU 配置下仍然都能完整 eval。
- `dynstopfinal` 仍然是三者里 collision 最低：`0.03125`。
- `author` 的 reach_goal 和 return 最高：reach_goal `0.15625`，return `2579.1174`。
- `own1500` 在这一档明显落后：collision `0.09375`、reach_goal `0.09375`。
- 这说明 `dynstopfinal` 比原始自训练 baseline 更稳，但还没有在 Isaac eval 的 reach / return 上超过作者 checkpoint。
- 当前最准确表述应该是：
  - 自训练已经得到一个有用候选；
  - 动态障碍行为比早期自训练 baseline 明显改善；
  - 离“按作者口径完整复现”还有差距，尤其是更大规模、GPU eval、真实部署链路。

### 目前最大一档 CPU Isaac eval matrix

目的：

- 继续逼近作者配置，在不触发 GPU reset 问题的前提下看 policy 结论是否稳定。
- 这是目前跑过的最大 CPU Isaac eval，对复现判断权重高于 quick-demo 离线 evaluator。

配置：

```text
device=cpu
sim.device=cpu
sim.use_gpu=False
sim.use_gpu_pipeline=False
env.num_envs=128
env.num_obstacles=240
env_dyn.num_obstacles=64
env.max_episode_length=600
```

输出目录：

```text
isaac-training/runs/eval_clean_cpu_matrix_128_240_64_600_20260419
```

结果：

```text
author:
[EVAL-JSON] {"eval/stats.collision": 0.109375, "eval/stats.episode_len": 579.90625, "eval/stats.reach_goal": 0.1484375, "eval/stats.return": 3035.903564453125, "eval/stats.truncated": 0.890625}
NO_CLOSE_EXIT

own1500:
[EVAL-JSON] {"eval/stats.collision": 0.1171875, "eval/stats.episode_len": 581.3515625, "eval/stats.reach_goal": 0.1171875, "eval/stats.return": 2922.00390625, "eval/stats.truncated": 0.8828125}
NO_CLOSE_EXIT

dynstopfinal:
[EVAL-JSON] {"eval/stats.collision": 0.125, "eval/stats.episode_len": 575.0078125, "eval/stats.reach_goal": 0.140625, "eval/stats.return": 2985.434814453125, "eval/stats.truncated": 0.875}
NO_CLOSE_EXIT
```

解释：

- 三个 checkpoint 都能在这一档 CPU Isaac eval 中完整跑完。
- 环境规模上去后，collision 整体升高：
  - author: `0.109375`
  - own1500: `0.1171875`
  - dynstopfinal: `0.125`
- `author` 在这一档 reach_goal 和 return 都最高。
- `dynstopfinal` 的 reach_goal / return 高于 `own1500`，但 collision 也高于 `own1500`。
- 这推翻了一个过强的早期说法：不能再说 `dynstopfinal` 在 Isaac eval 上稳定低碰撞。
- 更准确的当前判断：
  - `dynstopfinal` 在 quick-demo / path-crossing 离线评估中显著改善动态横穿失败；
  - 在小/中等 CPU Isaac eval 中也一度更低碰撞；
  - 但放大到 `128 / 240 / 64 / 600` 后没有保持低碰撞优势；
  - 因此它是有用候选和 ablation 证据，不是最终复现 policy。

下一步判断：

- 继续盲目加长 `dynstopfinal` 训练不够有根据。
- 更有价值的是回到作者思路：确认作者原始训练是否依赖更长训练、更大 eval、外部 safety/gating，还是当前 reward ablation 引入了分布偏移。
- 如果继续训练，应考虑更接近作者完整系统的目标，而不是只围绕 `dynamic_stop_penalty` 单点优化。

### eval no-render 文本评估开关

目的：

- 原始 `utils.evaluate()` 会强制 `env.enable_render(True)`，并生成 `wandb.Video`。
- 当前复现主线需要的是文本指标，不需要视频。
- 为了让更大 CPU eval 可承受，增加一个默认不改变原行为的可选开关。

调整文件：

```text
isaac-training/training/scripts/utils.py
```

行为：

- 默认不传参数时，仍保持原来的 render/video 行为。
- 传入：

```text
+eval_render=False
```

时：

- 不创建 `RenderCallback`；
- 不生成 `wandb.Video`；
- 仍然执行同样的 rollout；
- 仍然输出 `[EVAL-STATS-RAW]` 和 `[EVAL-JSON]`。

小规模验证：

```text
device=cpu
sim.device=cpu
sim.use_gpu=False
sim.use_gpu_pipeline=False
env.num_envs=16
env.num_obstacles=40
env_dyn.num_obstacles=10
env.max_episode_length=300
+eval_render=False
checkpoint=dynstopfinal
```

输出目录：

```text
isaac-training/runs/eval_clean_cpu_norender_smoke_16_40_10_300_20260419
```

结果：

```text
[EVAL-JSON] {"eval/stats.collision": 0.0, "eval/stats.episode_len": 300.0, "eval/stats.reach_goal": 0.0625, "eval/stats.return": 1573.316650390625, "eval/stats.truncated": 1.0}
NO_CLOSE_EXIT
```

解释：

- no-render 路径保留了文本指标。
- 日志中没有 `Rendering:` 进度和视频记录。
- 这只用于评估加速，不改变 policy、reward、环境 step 或 checkpoint。

### 作者障碍数量 CPU no-render eval matrix

目的：

- 在 CPU eval 稳定可用的前提下，把静态/动态障碍数量调到作者式配置：
  - `env.num_obstacles=350`
  - `env_dyn.num_obstacles=80`
- 并行环境数仍低于作者式 `1024`，本次为 `256`。
- episode 长度为 `800`，低于默认 `2200`。
- 这是目前最接近作者障碍规模的一张干净 CPU 指标表。

配置：

```text
device=cpu
sim.device=cpu
sim.use_gpu=False
sim.use_gpu_pipeline=False
env.num_envs=256
env.num_obstacles=350
env_dyn.num_obstacles=80
env.max_episode_length=800
+eval_render=False
```

输出目录：

```text
isaac-training/runs/eval_clean_cpu_norender_matrix_256_350_80_800_20260419
```

结果：

```text
author:
[EVAL-JSON] {"eval/stats.collision": 0.17578125, "eval/stats.episode_len": 751.9140625, "eval/stats.reach_goal": 0.265625, "eval/stats.return": 3902.00634765625, "eval/stats.truncated": 0.81640625}
NO_CLOSE_EXIT

own1500:
[EVAL-JSON] {"eval/stats.collision": 0.203125, "eval/stats.episode_len": 736.4609375, "eval/stats.reach_goal": 0.19921875, "eval/stats.return": 3676.824951171875, "eval/stats.truncated": 0.79296875}
NO_CLOSE_EXIT

dynstopfinal:
[EVAL-JSON] {"eval/stats.collision": 0.265625, "eval/stats.episode_len": 725.0546875, "eval/stats.reach_goal": 0.234375, "eval/stats.return": 3795.57421875, "eval/stats.truncated": 0.73828125}
NO_CLOSE_EXIT
```

解释：

- 三个 checkpoint 都能在作者障碍数量的 CPU no-render eval 中完整跑完。
- 作者 checkpoint 在这一档同时拥有最高 reach_goal、最高 return、最低 collision：
  - reach_goal `0.265625`
  - return `3902.0063`
  - collision `0.17578125`
- `dynstopfinal` 相比 `own1500`：
  - reach_goal 更高：`0.234375` vs `0.19921875`
  - return 更高：`3795.5742` vs `3676.8250`
  - 但 collision 更高：`0.265625` vs `0.203125`
- 当前最强结论：
  - 自训练候选确实学到了一部分导航/避障能力；
  - `dynamic_stop_penalty` 对 quick-demo 动态横穿有效；
  - 但在更接近作者障碍数量的 Isaac eval 中，自训练候选仍明显落后于作者 checkpoint，尤其 collision。
- 因此当前还不能宣称“自己的 policy 已经复现作者效果”。

下一步判断：

- 如果目标是论文/作者效果复现，下一步不应继续围绕 `dynstopfinal` 单点加训。
- 更合理路线：
  - 要么修 GPU eval，跑更接近 `1024 / 350 / 80 / 2200` 的正式评估；
  - 要么回到作者部署逻辑，把作者 checkpoint 与自训练 checkpoint 接入 ROS2/safe_action/gating 做端到端对照；
  - 要么基于作者 checkpoint 反推评估口径，确认 reach/collision 在当前 Isaac eval 中是否和作者实际使用的指标一致。

### 512 并行环境 CPU no-render eval pair

目的：

- 继续逼近作者的 `1024 / 350 / 80` 规模。
- 为控制耗时，只比较作者 checkpoint 与当前自训练主候选 `dynstopfinal`。
- 这一步仍然是 CPU eval，不是 GPU 正式 eval。

配置：

```text
device=cpu
sim.device=cpu
sim.use_gpu=False
sim.use_gpu_pipeline=False
env.num_envs=512
env.num_obstacles=350
env_dyn.num_obstacles=80
env.max_episode_length=1000
+eval_render=False
```

输出目录：

```text
isaac-training/runs/eval_clean_cpu_norender_pair_512_350_80_1000_20260419
```

结果：

```text
author:
[EVAL-JSON] {"eval/stats.collision": 0.234375, "eval/stats.episode_len": 900.462890625, "eval/stats.reach_goal": 0.31640625, "eval/stats.return": 4909.01513671875, "eval/stats.truncated": 0.75390625}
NO_CLOSE_EXIT

dynstopfinal:
[EVAL-JSON] {"eval/stats.collision": 0.310546875, "eval/stats.episode_len": 867.14453125, "eval/stats.reach_goal": 0.23828125, "eval/stats.return": 4751.76904296875, "eval/stats.truncated": 0.6875}
NO_CLOSE_EXIT
```

解释：

- `512 / 350 / 80 / 1000` 在 CPU no-render 路径可以跑完。
- 作者 checkpoint 继续明显领先：
  - reach_goal 更高：`0.3164` vs `0.2383`
  - collision 更低：`0.2344` vs `0.3105`
  - return 更高：`4909.0` vs `4751.8`
- 这进一步支持当前判断：
  - 自训练 policy 已经有能力，但还没有达到作者 checkpoint 的 Isaac eval 表现；
  - `dynstopfinal` 的 quick-demo 动态横穿优势不能外推为作者口径复现成功；
  - 下一步如果继续追求复现，应优先研究作者 policy/部署/eval 口径，而不是继续加长当前 ablation 训练。

下一步：

- CPU 稳路线最多还可以尝试 `1024 / 350 / 80` 的 no-render eval，但耗时会更高。
- 更有价值的下一步可能是把作者 checkpoint 和 `dynstopfinal` 接入同一 ROS2-style/safe_action 端到端链路，对比是否外部 safety/gating 缩小差距。
- GPU eval 修复仍是正式 Isaac 口径的工程缺口。

### 小规模 GPU Isaac eval 诊断

目的：

- 验证 GPU eval 路径是否已经干净，或是否仍存在 reset / Direct GPU API 问题。
- 这不是 policy 指标测试，而是 eval 路径诊断。

配置：

```text
device=cuda:0
sim.device=cuda:0
sim.use_gpu=True
sim.use_gpu_pipeline=True
env.num_envs=16
env.num_obstacles=40
env_dyn.num_obstacles=10
env.max_episode_length=300
checkpoint=dynstopfinal
```

输出目录：

```text
isaac-training/runs/eval_clean_gpu_dynstopfinal_diag_16_40_10_300_20260419
```

结果：

```text
[EVAL-JSON] {"eval/stats.collision": 0.0, "eval/stats.episode_len": 300.0, "eval/stats.reach_goal": 0.125, "eval/stats.return": 1550.3299560546875, "eval/stats.truncated": 1.0}
NO_CLOSE_EXIT
```

同时日志里仍然出现：

```text
PhysX error: PxArticulationLink::setGlobalPose(): it is illegal to call this method if PxSceneFlag::eENABLE_DIRECT_GPU_API is enabled!
```

解释：

- 小规模 GPU eval 这次没有崩，能输出指标和 `NO_CLOSE_EXIT`。
- 但 Direct GPU API / `setGlobalPose` 报错仍然存在，说明 GPU eval/reset 路径没有真正修干净。
- 不能把这个结果外推为 `1024 / 350 / 80` GPU eval 已经可用。
- 当前应继续把两件事分开：
  - policy 候选有效性：优先看 quick-demo 固定 evaluator、trace、CPU Isaac eval；
  - GPU eval 工程问题：单独修 reset / pose update / Direct GPU API 路径。

### GPU no-pipeline 绕行尝试

目的：

- 尝试保留 `cuda:0`，但关闭 `sim.use_gpu_pipeline`，看是否可以绕开 Direct GPU API 的 pose 写入限制。

配置：

```text
device=cuda:0
sim.device=cuda:0
sim.use_gpu=True
sim.use_gpu_pipeline=False
env.num_envs=16
env.num_obstacles=40
env_dyn.num_obstacles=10
env.max_episode_length=300
checkpoint=dynstopfinal
```

输出目录：

```text
isaac-training/runs/eval_clean_gpu_nopipeline_dynstopfinal_diag_16_40_10_300_20260419
```

结果：

```text
RuntimeError: Expected all tensors to be on the same device, but found at least two devices, cuda:0 and cpu!
```

触发位置：

```text
NavigationEnv(cfg)
  -> self.drone.initialize()
  -> self._view.post_reset()
  -> XFormPrimView.post_reset()
  -> self.set_world_poses(...)
  -> omni_drones/views/__init__.py:273
```

解释：

- 这条配置没有走到 eval rollout；它在 drone initialize / post_reset 阶段就失败。
- 因此不能把 `sim.use_gpu_pipeline=False` 直接当成 GPU eval 修复方案。
- 当前可用路线仍是：
  - CPU eval 用来拿干净 policy 对照；
  - GPU eval 需要代码级处理 reset / pose 写入路径，或改成全 CPU eval；
  - 训练主路径继续使用跳过 step-0 eval 的 GPU noeval0 入口。

补充诊断：

- 也测试了更一致的组合：

```text
device=cpu
sim.device=cuda:0
sim.use_gpu=True
sim.use_gpu_pipeline=False
```

- 输出目录：

```text
isaac-training/runs/eval_clean_cpu_tensor_gpu_physx_nopipeline_dynstopfinal_diag_16_40_10_300_20260419
```

- 结果仍然失败，错误相同：

```text
RuntimeError: Expected all tensors to be on the same device, but found at least two devices, cuda:0 and cpu!
```

- 触发位置仍是：

```text
NavigationEnv(cfg)
  -> self.drone.initialize()
  -> self._view.post_reset()
  -> XFormPrimView.post_reset()
  -> self.set_world_poses(...)
  -> omni_drones/views/__init__.py:273
```

- 当前结论：
  - 两种 no-pipeline 配置都不能无代码绕行；
  - 真要走这条路，需要最小代码 patch：在 OmniDrones view 写 pose 前，把 `positions/orientations` 移到 `poses.device`，然后再验证是否还会遇到后续 device mismatch；
  - 这个 patch 可能影响共享底层 view，必须作为诊断分支小步测试，不能直接视为复现修复。

临时 patch 诊断：

- 尝试过在 `isaac-training/third_party/OmniDrones/omni_drones/views/__init__.py` 的 `set_world_poses()` 里做最小 device 对齐：
  - 先把 `positions/orientations` 对齐到 `poses.device`；
  - 再尝试把 `indices` 按原始输入 pose 的 device 传给 PhysX backend。
- 这两个 patch 都没有形成可用修复：
  - 第一个 patch 从 tensor device mismatch 推进到 PhysX backend index device 报错；
  - 第二个 patch 仍然报 `Failed to set root link transforms in backend`，日志里还有 `Incompatible device of index tensor in function setRootTransforms: expected device -1, received device 0`。
- 因为没有通过小规模 eval，已经撤回这两个临时 patch，避免污染稳定训练/CPU eval 路线。
- 当前判断：
  - no-pipeline 方向不是简单一两行 device cast 能解决；
  - 若继续修 GPU eval，应单独开诊断分支研究 PhysX tensor backend 的 index/device 规则；
  - 主线仍应先保留 CPU Isaac eval + GPU noeval0 training 的稳定组合。


## 2026-04-18 ROS2 辅助验证附录（压缩版）

说明：这一段只保留对复现有帮助的 ROS2/部署侧结论。详细逐条命令和长输出已经删去，避免偏离当前主线。当前主线仍是：训练出 policy，并用固定 evaluator 验证它是否可行。

### 已完成的辅助检查

1. ROS2 workspace 可以构建作者包。

- workspace：`/home/ubuntu/projects/navrl_ros2_ws`
- symlink 包：`onboard_detector`、`map_manager`、`navigation_runner`
- 已确认 `safe_action_node`、`navigation_node.py`、`dynamic_detector_node` 可以启动或被服务调用。

2. `navigation_node.py` 可以加载 checkpoint。

- 作者默认 checkpoint：`ros2/navigation_runner/scripts/ckpts/navrl_checkpoint.pt`
- 自训练候选：`policies/dynstopfinal_20260418/checkpoint_final.pt`
- 两者都能在 ROS2 节点层加载并输出动作。

3. 最小 ROS2 闭环曾经跑通。

链路：

```text
odom + goal -> navigation_node.py -> safe_action_node -> /unitree_go2/cmd_vel
```

这只证明部署链路可连通，不评价 policy 是否复现成功。

4. 动态障碍 stub / synthetic detector 只是辅助工具。

相关脚本：

```text
ros2/tools/dynamic_obstacle_stub.py
ros2/tools/run_policy_stub_scan.py
ros2/tools/run_policy_stub_rollout.py
ros2/tools/synthetic_sensor_publisher.py
ros2/tools/run_synthetic_detector_preflight.sh
ros2/tools/run_synthetic_e2e_preflight.sh
```

保留原因：

- 后续真机或 ROS2 集成时可以复用。
- 可以证明 policy `.pt` 不只是离线文件，也能进入作者 ROS2 节点。

但这些都不是当前复现主证据。

### 重要辅助结论

- `dynstopfinal` 可以通过 `NAVRL_CHECKPOINT_FILE=/home/ubuntu/projects/NavRL/policies/dynstopfinal_20260418/checkpoint_final.pt` 被 `navigation_node.py` 加载。
- 在 synthetic detector 输入下，`/onboard_detector/get_dynamic_obstacles` 可以返回非空障碍物。
- `policy -> safe_action -> cmd_vel` 能产生文本可见的速度输出。
- synthetic moving depth patch 能形成 tracked bbox，但不能稳定触发 motion-only dynamic classification；不应把这个失败解释为 policy 失败。

### 为什么降级为附录

- 这些检查回答的是“部署链路能不能连上”，不是“policy 是否学会导航”。
- 当前用户目标是复现 policy，因此主线证据应该来自训练配置、checkpoint、固定 evaluator、成功率/碰撞率/失败样本。
- 后续除非进入真机部署阶段，否则 ROS2 synthetic 工具只作为辅助，不再继续扩展。

## 当前主线结论（2026-04-18 收敛版）

当前最值得继续验证的 policy：

```text
policies/dynstopfinal_20260418/checkpoint_final.pt
```

主要对照：

```text
quick-demos/ckpts/navrl_checkpoint.pt
policies/own1500_20260417/checkpoint_1500.pt
```

当前判断：

- 1024 / 350 / 80 GPU 训练路径在 `noeval0` 入口下可用。
- 训练能跑完不等于复现成功。
- `dynstopfinal` 是目前离线评估中表现最好的自训练候选。
- 它来自定向 reward ablation，而不是盲目加长训练。
- 下一步应该是固定 evaluator 的干净复跑和结果表格，而不是继续扩展 ROS2 synthetic 工具。

## 下一步

1. 用 `quick-demos/run_repro_eval.sh` 或等价固定命令，重新跑作者 checkpoint、`own1500`、`dynstopfinal`。
2. 记录每个 policy 的 reach / static collision / dynamic collision / timeout。
3. 对 `dynstopfinal` 做少量失败样本 trace，确认它不是偶然变好。
4. 如果结果稳定，再决定是否需要继续训练；如果不稳定，优先查 evaluator/训练 reward，而不是直接长训。
