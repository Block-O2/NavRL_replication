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
- `[done]` 加入 safe_action Python 近似层。
- `[done]` 加入更强动态横穿场景 `path-crossing`。
- `[done]` 建立固定复现评估脚本 `quick-demos/run_repro_eval.sh`。
- `[done]` 检查真实 ROS2 构建环境，确认当前服务器缺 ROS2 Humble / colcon。
- `[done]` 做 author / own1500 / ownfinal 在 `path-crossing` 场景下的逐帧动作序列对比。
- `[done]` 回到训练代码阅读，重点查动态障碍分布、reward、termination、dynamic obstacle encoding 是否和作者部署一致。
- `[done]` 给干净 noeval0 训练入口增加默认关闭的 JSONL metrics 日志，方便后续继续训练时保留文本证据。
- `[done]` 给干净 noeval0 训练入口增加默认关闭的 checkpoint 加载参数，方便从 `checkpoint_1500.pt` 做短阶段继续训练。
- `[done]` 执行一次从 `checkpoint_1500.pt` 接续的 10M 短阶段训练，并保留 metrics。
- `[done]` 分析为什么 10M 接续训练没有改善 dynamic path-crossing，避免沿错误方向继续加长训练。
- `[done]` 添加默认关闭的 reward ablation 开关：碰撞惩罚、成功奖励/终止、动态障碍近距离停滞惩罚。
- `[done]` 跑一个 5M 定向 ablation：只打开动态障碍近距离停滞惩罚，验证是否能减少 `path-crossing` 中停在障碍路径上的坏行为。
- `[done]` 用固定离线 evaluator 对 ablation checkpoint 做 dynamic path-crossing 和 mixed 场景对比。
- `[doing]` 把 `dynstopfinal` 作为新的自训练候选，继续做更接近作者部署路径的验证和边界确认。
- `[next]` 做 trace/失败样本复查，确认 `dynstopfinal` 是否真的消除了“停在动态障碍路径上”的失败模式，而不是只在统计上偶然变好。
- `[optional]` 如果确认是动态横穿训练不足，再设计小规模继续训练实验，而不是直接 1.2B 长训。
- `[blocked]` 真实 ROS2 `safe_action_node` 构建：当前服务器缺 `/opt/ros/humble/setup.bash`、`ros2`、`colcon`。

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
- 当前主要缺口不是“能不能训练”，而是继续把候选 policy 放到更接近作者部署路径的验证里：
  - ROS2 输入编码；
  - 动态障碍服务；
  - `safe_action`；
  - 目标减速 / 停止逻辑；
  - 最终还需要 Isaac eval，或另一个不会触发 GPU reset bug 的文本评估。

## 建议下一步

1. 使用 `dynstopfinal` 作为当前自训练主候选。
2. 保留 `checkpoint_1500.pt` 作为无 ablation 稳定 baseline。
3. 保留 `checkpoint_final.pt` / `checkpoint_1000.pt` 作为对照 baseline。
4. 不要直接启动 1.2B 长训练；当前收益来自定向 reward 修复，不是单纯加长训练。
5. 下一步优先做 trace/失败样本复查，确认 `dynstopfinal` 是否真的消除了“停在动态障碍路径上”的失败模式。
6. 再推进更接近作者部署路径的验证：真实 ROS2 环境、safe_action_node、目标减速/停止逻辑。

## 2026-04-18 ROS2 部署链路预检

目的：

- 复现目标不能只停留在 Isaac training / quick-demo 层面，需要推进到作者 ROS2 部署链路。
- 这一阶段先确认作者提供的 ROS2 包能否在服务器上编译、被 ROS2 发现、并运行 `safe_action_node` 的最小服务调用。
- 这一步不评价 policy 成功率，只验证部署基础链路。

执行前提：

- 用户已在服务器安装 ROS2。
- 使用 ROS2 Humble：`/opt/ros/humble/setup.bash`。
- 为避免污染仓库，ROS2 workspace 放在仓库外层项目目录：
  - `/home/ubuntu/projects/navrl_ros2_ws`
- workspace 里通过 symlink 引入作者包：
  - `/home/ubuntu/projects/NavRL/ros2/onboard_detector`
  - `/home/ubuntu/projects/NavRL/ros2/map_manager`
  - `/home/ubuntu/projects/NavRL/ros2/navigation_runner`

预检命令：

```bash
source /opt/ros/humble/setup.bash
bash ros2/check_ros2_build_env.sh
```

结果：

```text
PASS: ROS2 build environment preflight checks passed.
```

包发现命令：

```bash
cd /home/ubuntu/projects/navrl_ros2_ws
source /opt/ros/humble/setup.bash
colcon list
```

结果：

```text
map_manager          src/map_manager          (ros.ament_cmake)
navigation_runner    src/navigation_runner    (ros.ament_cmake)
onboard_detector     src/onboard_detector     (ros.ament_cmake)
```

首次编译命令：

```bash
cd /home/ubuntu/projects/navrl_ros2_ws
source /opt/ros/humble/setup.bash
colcon build --symlink-install
```

结果：

```text
Finished <<< onboard_detector [2min 0s]
Finished <<< map_manager [2min 30s]
Finished <<< navigation_runner [30.0s]
Summary: 3 packages finished [5min 1s]
```

编译后可执行文件检查：

```bash
source /opt/ros/humble/setup.bash
source /home/ubuntu/projects/navrl_ros2_ws/install/setup.bash
ros2 pkg executables navigation_runner
ros2 pkg executables map_manager
ros2 pkg executables onboard_detector
```

结果：

```text
navigation_runner navigation_node.py
navigation_runner safe_action_node
map_manager esdf_map_node
map_manager occupancy_map_node
onboard_detector dynamic_detector_node
onboard_detector yolo_detector_node.py
```

`safe_action` 服务接口检查：

```bash
ros2 interface show navigation_runner/srv/GetSafeAction
```

确认接口包含：

- agent position / velocity / size；
- dynamic obstacles position / velocity / size；
- static laser points；
- max velocity；
- RL velocity；
- 返回 safe action。

最小运行验收：

```bash
source /opt/ros/humble/setup.bash
source /home/ubuntu/projects/navrl_ros2_ws/install/setup.bash
export ROS_LOG_DIR=/home/ubuntu/projects/navrl_ros2_ws/log/ros
export ROS_DOMAIN_ID=43
ros2 run navigation_runner safe_action_node
```

然后调用：

```bash
ros2 service call /safe_action/get_safe_action navigation_runner/srv/GetSafeAction \
"{agent_position: {x: 0.0, y: 0.0, z: 1.0}, agent_velocity: {x: 0.0, y: 0.0, z: 0.0}, agent_size: 0.3, obs_position: [], obs_velocity: [], obs_size: [], laser_points: [], laser_range: 5.0, laser_res: 0.1, max_velocity: 1.0, rl_velocity: {x: 0.5, y: 0.0, z: 0.0}}"
```

结果：

```text
/safe_action/get_safe_action
response:
navigation_runner.srv.GetSafeAction_Response(
  safe_action=geometry_msgs.msg.Vector3(x=0.5, y=0.0, z=0.0)
)
```

判断：

- ROS2 安装已满足当前 NavRL 作者 ROS2 包的基础编译需求。
- `onboard_detector`、`map_manager`、`navigation_runner` 三个包均能在 Humble 上编译。
- `safe_action_node` 不只是能编译，最小服务请求链路也能跑通。
- 空障碍输入下，`safe_action` 等于 RL velocity，符合预期。

注意事项：

- 在 Codex 默认沙盒内直接运行 ROS2 service/list 会因为 socket 权限报 `Operation not permitted`；这不是 NavRL 代码错误。
- 运行 ROS2 节点时需要让日志写到可写目录，例如：
  - `ROS_LOG_DIR=/home/ubuntu/projects/navrl_ros2_ws/log/ros`
- 目前只完成了 `safe_action_node` 的最小服务验收，还没有启动完整 `navigation_node.py`、map 服务、detector 服务，也还没有接入真实 policy 推理和传感器数据。

## 当前滚动计划

1. 已完成：1024 / 350 / 80 GPU 训练路径确认，`noeval0` 可跑。
2. 已完成：50M 自训练 policy 和 5M `dynamic_stop_penalty` ablation。
3. 已完成：quick-demo/ROS2-style 离线评估，当前最强候选是 `dynstopfinal`。
4. 已完成：ROS2 三个作者包编译通过。
5. 已完成：`safe_action_node` 最小服务调用通过。
6. 下一步：阅读并验证 `navigation_node.py` 的 policy 加载、输入编码、目标减速/停止逻辑。
7. 下一步：做最小 ROS2 policy 推理链路测试，优先不启动真实传感器，只验证作者节点能否加载 checkpoint 并构造 action。
8. 下一步：把 `dynstopfinal` 和作者 checkpoint 都放到更接近 ROS2 节点的输入路径里对比。
9. 暂缓：1.2B 长训练。当前更值得先确认部署链路和任务信号，而不是直接加长训练。

## 2026-04-18 ROS2 `navigation_node.py` 启动与 checkpoint 加载

目的：

- 继续靠近作者真实部署路径。
- 验证 `navigation_node.py` 的 Python 依赖、Hydra 配置、checkpoint 路径、PPO 网络结构是否能在服务器上跑通。
- 这一步仍不评价导航效果，只确认 ROS2 policy 节点能否启动到模型加载阶段。

代码阅读结论：

- `navigation_node.py` 使用 Hydra 读取 `ros2/navigation_runner/scripts/cfg/train.yaml`。
- `Navigation.__init__()` 会先等待 `/occupancy_map/raycast` 服务，然后才加载模型。
- 模型默认参数：
  - ROS 参数名：`checkpoint_file`
  - 默认值：`navrl_checkpoint.pt`
  - 实际路径：`ros2/navigation_runner/scripts/ckpts/navrl_checkpoint.pt`
- ROS2 侧作者 checkpoint SHA256：

```text
51fa3dbdc6ba89626b5dad3a4638deb53d40aa6f0caa9b289657da4a8e0b60c3  navrl_checkpoint.pt
```

Python 环境检查：

```bash
source /opt/ros/humble/setup.bash
python3 - <<'PY'
import torch
PY
```

系统 Python 结果：

```text
/usr/bin/python3
torch FAIL ModuleNotFoundError No module named 'torch'
torchrl FAIL ModuleNotFoundError No module named 'torchrl'
tensordict FAIL ModuleNotFoundError No module named 'tensordict'
hydra FAIL ModuleNotFoundError No module named 'hydra'
rclpy OK
```

NavRL conda Python 结果：

```text
/home/ubuntu/miniconda3/envs/NavRL/bin/python
torch OK 2.0.1+cu118
torchrl OK 0.4.0+3725bcc
tensordict OK 0.4.0+3725bcc
hydra OK 1.3.2
rclpy OK
```

判断：

- 直接 `ros2 run navigation_runner navigation_node.py` 会走系统 Python，因此缺 `torch`。
- 最小可行方式不是把训练依赖装进系统 Python，而是在运行 ROS2 Python 节点时把 NavRL conda Python 放到 `PATH` 前面：

```bash
export PATH=/home/ubuntu/miniconda3/envs/NavRL/bin:$PATH
```

短启动测试 1：

```bash
source /opt/ros/humble/setup.bash
source /home/ubuntu/projects/navrl_ros2_ws/install/setup.bash
export PATH=/home/ubuntu/miniconda3/envs/NavRL/bin:$PATH
export ROS_LOG_DIR=/home/ubuntu/projects/navrl_ros2_ws/log/ros
timeout 8 ros2 run navigation_runner navigation_node.py
```

结果：

```text
[navRunner]: Velocity limit: 1.0.
[navRunner]: Visualize raycast is set to: False.
[navRunner]: Odom topic name: /unitree_go2/odom.
[navRunner]: Command topic name: /unitree_go2/cmd_vel.
[navRunner]: Service /occupancy_map/raycast not available, waiting...
```

判断：

- conda Python 方式能通过 import 阶段。
- 节点卡在等待 `/occupancy_map/raycast` 是代码预期行为，不是错误。

短启动测试 2：

先启动 map 服务：

```bash
source /opt/ros/humble/setup.bash
source /home/ubuntu/projects/navrl_ros2_ws/install/setup.bash
export PATH=/home/ubuntu/miniconda3/envs/NavRL/bin:$PATH
export ROS_LOG_DIR=/home/ubuntu/projects/navrl_ros2_ws/log/ros
ros2 run map_manager occupancy_map_node
```

再短启动 navigation：

```bash
timeout 15 ros2 run navigation_runner navigation_node.py
```

结果：

```text
[navRunner]: Checkpoint: navrl_checkpoint.pt.
[navRunner]: Model load successfully.
[navRunner]: Start running!
```

末尾有：

```text
rclpy._rclpy_pybind11.RCLError: failed to shutdown: rcl_shutdown already called
```

判断：

- 该错误来自 `timeout` 强制结束节点后的 ROS2 shutdown 清理，不是 checkpoint 加载失败。
- 作者 ROS2 `navigation_node.py` 已经能在本服务器上加载作者 checkpoint 并进入运行状态。

当前 ROS2 侧结论：

- 编译链路：通过。
- `safe_action_node` 最小服务：通过。
- `navigation_node.py` Python 依赖：需要 conda Python PATH。
- `navigation_node.py` checkpoint 加载：通过。
- 尚未完成：完整 ROS2 runtime 输入链路，也就是 odom / goal / raycast / dynamic obstacle / safe_action / cmd_vel 的闭环文本验证。

更新后的下一步：

1. 启动 `occupancy_map_node`、`dynamic_detector_node`、`safe_action_node`、`navigation_node.py`。
2. 用文本方式发布最小 odom 和 goal。
3. 订阅 `/unitree_go2/cmd_vel`，确认节点是否能产生命令。
4. 如果能产生命令，再比较作者 checkpoint 与 `dynstopfinal` 在 ROS2 节点输入路径下的动作差异。

## 2026-04-18 ROS2 最小闭环：odom/goal 到 cmd_vel

目的：

- 验证不依赖 Isaac、不依赖 quick-demo 的 ROS2 runtime 最小闭环。
- 这一步启动作者 ROS2 节点，然后只用文本发布 odom 和 goal，观察 `/unitree_go2/cmd_vel`。
- 这不是导航成功率评估，只是验证作者 ROS2 节点链路已经能从输入走到速度命令输出。

启动的节点：

- `map_manager occupancy_map_node`
- `onboard_detector dynamic_detector_node`
- `navigation_runner safe_action_node`
- `navigation_runner navigation_node.py`

关键环境：

```bash
source /opt/ros/humble/setup.bash
source /home/ubuntu/projects/navrl_ros2_ws/install/setup.bash
export PATH=/home/ubuntu/miniconda3/envs/NavRL/bin:$PATH
export ROS_LOG_DIR=/home/ubuntu/projects/navrl_ros2_ws/log/ros
```

服务发现结果：

```text
/occupancy_map/raycast
/onboard_detector/get_dynamic_obstacles
/safe_action/get_safe_action
```

发布输入：

```bash
ros2 topic pub --once /unitree_go2/odom nav_msgs/msg/Odometry \
"{header: {frame_id: map}, pose: {pose: {position: {x: 0.0, y: 0.0, z: 1.0}, orientation: {w: 1.0, x: 0.0, y: 0.0, z: 0.0}}}, twist: {twist: {linear: {x: 0.0, y: 0.0, z: 0.0}}}}"

ros2 topic pub --once /goal_pose geometry_msgs/msg/PoseStamped \
"{header: {frame_id: map}, pose: {position: {x: 5.0, y: 0.0, z: 1.0}, orientation: {w: 1.0}}}"
```

作者 checkpoint 输出：

```text
linear:
  x: 1.0
  y: 0.0
  z: 0.0
angular:
  x: 0.0
  y: 0.0
  z: 0.0
```

日志检查：

- `navigation_node` 输出：

```text
[navRunner]: Checkpoint: navrl_checkpoint.pt.
[navRunner]: Model load successfully.
[navRunner]: Start running!
```

- 四个节点日志未命中：

```text
Traceback|ERROR|Exception|failed|Aborted|Segmentation
```

判断：

- 作者 checkpoint 已经能在 ROS2 节点闭环里从 odom/goal 走到 `/unitree_go2/cmd_vel`。
- 当前场景没有真实障碍，输出 `x=1.0` 符合“朝目标直行”的直觉和代码逻辑。
- 这仍不是复现实验结果，只是部署链路向前推进了一步。

## 2026-04-18 ROS2 最小闭环：加载自训练 `dynstopfinal`

目的：

- 确认自训练 checkpoint 不是只能在 training / quick-demo 脚本里使用。
- 验证它能通过作者 ROS2 `navigation_node.py` 的真实 checkpoint 加载路径，并输出 `/unitree_go2/cmd_vel`。

checkpoint：

```text
/home/ubuntu/projects/NavRL/isaac-training/runs/navrl_1024_ablate_dynstop_5m_20260418/ckpts/checkpoint_final.pt
```

运行方式：

```bash
ros2 run navigation_runner navigation_node.py --ros-args \
  -p checkpoint_file:=/home/ubuntu/projects/NavRL/isaac-training/runs/navrl_1024_ablate_dynstop_5m_20260418/ckpts/checkpoint_final.pt
```

日志：

```text
[navRunner]: Checkpoint: /home/ubuntu/projects/NavRL/isaac-training/runs/navrl_1024_ablate_dynstop_5m_20260418/ckpts/checkpoint_final.pt.
[navRunner]: Model load successfully.
[navRunner]: Start running!
```

同样 odom/goal 输入下输出：

```text
linear:
  x: 1.0
  y: 0.0
  z: 0.0
angular:
  x: 0.0
  y: 0.0
  z: 0.0
```

日志检查：

- 未命中：

```text
Traceback|ERROR|Exception|failed|Aborted|Segmentation
```

判断：

- `dynstopfinal` 已经能进入作者 ROS2 `navigation_node.py` 推理路径。
- 这说明自训练 policy 与作者 ROS2 PPO 网络结构、checkpoint 格式、Hydra 配置至少在加载层面兼容。
- 由于这个最小场景没有障碍，输出 `x=1.0` 主要验证链路，不足以区分作者 checkpoint 和 `dynstopfinal` 的避障能力。

更新后的下一步：

1. 构造 ROS2 节点层面的动态障碍输入，避免只测无障碍直行。
2. 优先不改作者节点：可以通过动态障碍服务输入或轻量 stub 服务控制 obstacle response。
3. 对比作者 checkpoint、`own1500`、`dynstopfinal` 在同一 ROS2 输入下的 `cmd_vel`。
4. 如果 ROS2 层动作差异符合 quick-demo 趋势，再考虑是否需要进一步接 Isaac eval 或实机前仿真。

## 2026-04-18 ROS2 动态障碍 stub 对比

目的：

- 无障碍最小闭环只能证明 ROS2 节点能输出直行速度，不能区分 policy。
- 为了继续靠近作者部署路径，同时保持输入可控，新增一个测试辅助 stub：
  - `ros2/tools/dynamic_obstacle_stub.py`
- 该 stub 不改作者 `navigation_node.py`，只提供同名服务：
  - `/onboard_detector/get_dynamic_obstacles`
- 用它固定返回一个动态障碍，然后比较作者 checkpoint 与 `dynstopfinal` 的 `/unitree_go2/cmd_vel`。

新增文件：

```text
ros2/tools/dynamic_obstacle_stub.py
```

语法检查：

```bash
source /opt/ros/humble/setup.bash
/home/ubuntu/miniconda3/envs/NavRL/bin/python -m py_compile ros2/tools/dynamic_obstacle_stub.py
```

结果：通过。

测试输入：

- odom：
  - position = `(0.0, 0.0, 1.0)`
  - orientation yaw = `0`
  - velocity = `(0.0, 0.0, 0.0)`
- goal：
  - position = `(5.0, 0.0, 1.0)`
- dynamic obstacle stub：
  - position = `(2.0, 0.0, 1.0)`
  - velocity = `(0.0, 0.0, 0.0)`
  - size = `(0.8, 0.8, 1.0)`

启动节点：

- `map_manager occupancy_map_node`
- `navigation_runner safe_action_node`
- `ros2/tools/dynamic_obstacle_stub.py`
- `navigation_runner navigation_node.py`

作者 checkpoint 结果：

```text
[navRunner]: Checkpoint: navrl_checkpoint.pt.
[navRunner]: Model load successfully.
[navRunner]: Start running!

linear:
  x: 0.5279386043548584
  y: 0.13685071468353271
  z: 0.0
angular:
  x: 0.0
  y: 0.0
  z: 0.0
```

`dynstopfinal` 结果：

```text
[navRunner]: Checkpoint: /home/ubuntu/projects/NavRL/isaac-training/runs/navrl_1024_ablate_dynstop_5m_20260418/ckpts/checkpoint_final.pt.
[navRunner]: Model load successfully.
[navRunner]: Start running!

linear:
  x: 0.10706663131713867
  y: 0.285952091217041
  z: 0.0
angular:
  x: 0.0
  y: 0.0
  z: 0.0
```

日志检查：

```text
Traceback|ERROR|Error|Exception|failed|Aborted|Segmentation|terminate
```

结果：未命中。

判断：

- ROS2 节点层面已经进入障碍相关路径，不再只是无障碍直行。
- 同一受控动态障碍输入下，作者 checkpoint 输出仍以前向为主，略向 `+y` 偏转：
  - `x≈0.528`
  - `y≈0.137`
- `dynstopfinal` 输出更保守的前向速度和更明显横向绕让：
  - `x≈0.107`
  - `y≈0.286`
- 这和之前 `dynamic_stop_penalty` ablation 的趋势一致：`dynstopfinal` 更倾向于避免停在/冲进动态障碍路径。

限制：

- 这个测试里的动态障碍是 stub，不是真实 detector 由深度图/颜色图推出来的障碍。
- 这个测试仍没有真实里程计闭环、地图更新、连续控制轨迹，也不是实机安全验证。
- 输出是最终 `cmd_vel`，包含 policy、坐标变换、safe_action、目标距离逻辑共同作用；还不是纯 policy raw action。

下一步建议：

1. 增加可选 debug 日志或 debug topic，记录 `cmd_vel_world` 与 `safe_cmd_vel_world`，区分 policy raw action 和 safe_action 后处理。
2. 用同一个动态障碍 stub 做多组位置/速度扫描，例如：
   - 前方静止障碍；
   - 横穿障碍；
   - 侧前方障碍；
   - 障碍远离目标路径。
3. 对比作者 checkpoint、`own1500`、`dynstopfinal` 的 ROS2 节点输出表。
4. 如果节点层对比稳定，再决定是否接入真实 detector 输入或回到 Isaac eval 修复。

## 2026-04-18 ROS2 action debug topic

目的：

- 上一节只能看到最终 `/unitree_go2/cmd_vel`。
- 最终速度包含：
  - policy 输出；
  - world/local 坐标变换；
  - `safe_action_node` 后处理；
  - 目标距离逻辑；
  - `height_control=False` 时 z 方向置零。
- 为了区分 policy raw action 和 safe_action 后处理，给 `navigation_node.py` 增加默认关闭的 debug topic。

最小代码改动：

文件：

```text
ros2/navigation_runner/scripts/navigation.py
```

新增 ROS 参数：

```text
debug_action_topics: false
```

开启后发布：

```text
/navigation_runner/debug/raw_cmd_vel_world
/navigation_runner/debug/safe_cmd_vel_world
```

说明：

- 默认关闭，不改变作者节点原行为。
- debug topic 使用 `geometry_msgs/msg/Vector3`。
- raw topic 记录 policy 输出的 world velocity。
- safe topic 记录调用 `safe_action_node` 后的 world velocity。
- 最终 `/unitree_go2/cmd_vel` 仍然是局部坐标下实际发布给机器人的命令。

语法检查：

```bash
source /opt/ros/humble/setup.bash
/home/ubuntu/miniconda3/envs/NavRL/bin/python -m py_compile \
  ros2/navigation_runner/scripts/navigation.py \
  ros2/tools/dynamic_obstacle_stub.py
```

结果：通过。

同一动态障碍 stub 输入：

```text
agent: (0.0, 0.0, 1.0), yaw=0
goal:  (5.0, 0.0, 1.0)
obs:   pos=(2.0, 0.0, 1.0), vel=(0.0, 0.0, 0.0), size=(0.8, 0.8, 1.0)
```

作者 checkpoint debug 输出：

```text
raw_cmd_vel_world:
  x: 0.5279386043548584
  y: 0.13685071468353271
  z: 0.46702325344085693

safe_cmd_vel_world:
  x: 0.5279386043548584
  y: 0.13685071468353271
  z: 0.0

final /unitree_go2/cmd_vel:
  linear.x: 0.5279386043548584
  linear.y: 0.13685071468353271
  linear.z: 0.0
  angular.z: 0.0
```

`dynstopfinal` debug 输出：

```text
raw_cmd_vel_world:
  x: 0.10706663131713867
  y: 0.285952091217041
  z: -0.032970964908599854

safe_cmd_vel_world:
  x: 0.10706663131713867
  y: 0.285952091217041
  z: -0.032970964908599854

final /unitree_go2/cmd_vel:
  linear.x: 0.10706663131713867
  linear.y: 0.285952091217041
  linear.z: 0.0
  angular.z: 0.0
```

日志检查：

```text
Traceback|ERROR|Error|Exception|failed|Aborted|Segmentation|terminate
```

结果：未命中。

判断：

- 在这个受控动态障碍场景中，作者 checkpoint 和 `dynstopfinal` 的 x/y 差异主要来自 policy raw action，不是 `safe_action_node` 把二者改成不同方向。
- 作者 checkpoint 的 raw z 较大，但 safe_action / final command 把 z 压到 0；这符合当前 `height_control=False` 的平面控制路径。
- `dynstopfinal` raw x 更小、y 更大，说明它在 ROS2 节点输入编码下也表现出更强绕让倾向。

接下来更值得做的事：

1. 用 debug topic 做一个小表格扫描，而不是只测一个障碍点。
2. 扫描维度优先：
   - obstacle y：`0.0, 0.5, -0.5`
   - obstacle vx/vy：静止、横穿、迎面
   - checkpoint：author、own1500、dynstopfinal
3. 暂时不引入真实相机/点云，因为当前目标是先确认 policy 在 ROS2 编码路径下的行为是否稳定。

## 2026-04-18 ROS2 横穿动态障碍单点对比

目的：

- 前方静止动态障碍只是一种输入，不足以代表动态避障。
- 增加一个横穿障碍点，检查三组 checkpoint 在 ROS2 节点编码路径下的 raw/safe/final 输出。

输入：

```text
agent: (0.0, 0.0, 1.0), yaw=0
goal:  (5.0, 0.0, 1.0)
obs:   pos=(2.0, -1.0, 1.0), vel=(0.0, 1.0, 0.0), size=(0.8, 0.8, 1.0)
```

作者 checkpoint：

```text
raw_cmd_vel_world:
  x: -0.6430521011352539
  y: 0.706621527671814
  z: 0.3293442726135254

safe_cmd_vel_world:
  x: -0.6430521011352539
  y: 0.706621527671814
  z: 0.0

final /unitree_go2/cmd_vel:
  linear.x: -0.6430521011352539
  linear.y: 0.706621527671814
  linear.z: 0.0
```

`own1500`：

```text
raw_cmd_vel_world:
  x: 0.2829403877258301
  y: 0.5323700904846191
  z: 0.24598252773284912

safe_cmd_vel_world:
  x: 0.2829403877258301
  y: 0.5323700904846191
  z: 0.0

final /unitree_go2/cmd_vel:
  linear.x: 0.2829403877258301
  linear.y: 0.5323700904846191
  linear.z: 0.0
```

`dynstopfinal`：

```text
raw_cmd_vel_world:
  x: 0.4294644594192505
  y: 0.5816572904586792
  z: -0.0476108193397522

safe_cmd_vel_world:
  x: 0.4294644594192505
  y: 0.5816572904586792
  z: -0.0476108193397522

final /unitree_go2/cmd_vel:
  linear.x: 0.4294644594192505
  linear.y: 0.5816572904586792
  linear.z: 0.0
```

日志检查：

```text
Traceback|ERROR|Error|Exception|failed|Aborted|Segmentation|terminate
```

结果：未命中。

判断：

- 该横穿输入下，作者 checkpoint 的 raw policy 最保守，直接给出负 x，也就是后退避让。
- `own1500` 和 `dynstopfinal` 都保持正 x，同时给出较明显 `+y` 横向避让。
- 这说明不能用单个场景简单说某个 checkpoint “总是更保守”或“总是更好”。
- 需要做一个小规模 ROS2 节点层输入扫描，记录每个 checkpoint 的 raw/safe/final action。
- 在当前两个动态障碍单点中，x/y 差异都主要来自 raw policy；`safe_action_node` 主要影响 z 或不改变 x/y。

下一步优先级：

1. 将当前手工 ROS2 对比整理成可复跑脚本，避免每次手写长命令。
2. 用 6 到 9 个受控动态障碍输入形成小表。
3. 再决定是否需要把 debug topic 保留为复现辅助，或只作为本地调试 patch。

## 2026-04-18 ROS2 动态障碍 stub 扫描脚本

目的：

- 把前面手工执行的 ROS2 动态障碍对比变成可复跑脚本。
- 每个 case 自动启动：
  - `occupancy_map_node`
  - `safe_action_node`
  - `dynamic_obstacle_stub.py`
  - `navigation_node.py`
- 自动发布固定 odom / goal。
- 自动订阅：
  - `/navigation_runner/debug/raw_cmd_vel_world`
  - `/navigation_runner/debug/safe_cmd_vel_world`
  - `/unitree_go2/cmd_vel`
- 输出 CSV，方便后续继续扩展 case。

新增脚本：

```text
ros2/tools/run_policy_stub_scan.py
```

语法检查：

```bash
source /opt/ros/humble/setup.bash
/home/ubuntu/miniconda3/envs/NavRL/bin/python -m py_compile \
  ros2/tools/dynamic_obstacle_stub.py \
  ros2/tools/run_policy_stub_scan.py \
  ros2/navigation_runner/scripts/navigation.py
```

结果：通过。

运行命令：

```bash
source /opt/ros/humble/setup.bash
source /home/ubuntu/projects/navrl_ros2_ws/install/setup.bash
export PATH=/home/ubuntu/miniconda3/envs/NavRL/bin:$PATH
export ROS_LOG_DIR=/home/ubuntu/projects/navrl_ros2_ws/log/ros

/home/ubuntu/miniconda3/envs/NavRL/bin/python \
  /home/ubuntu/projects/NavRL/ros2/tools/run_policy_stub_scan.py \
  --output /home/ubuntu/projects/NavRL/ros2/tools/policy_stub_scan_20260418.csv \
  --domain-start 80
```

输出：

```text
ros2/tools/policy_stub_scan_20260418.csv
```

扫描配置：

- checkpoints：
  - `author`
  - `own1500`
  - `dynstopfinal`
- odom：
  - `(0.0, 0.0, 1.0)`, yaw = 0
- goal：
  - `(5.0, 0.0, 1.0)`
- dynamic obstacle size：
  - `(0.8, 0.8, 1.0)`
- cases：
  - `front_static`: `(2.0, 0.0, 1.0)`, velocity `(0.0, 0.0, 0.0)`
  - `front_oncoming`: `(2.0, 0.0, 1.0)`, velocity `(-1.0, 0.0, 0.0)`
  - `cross_yneg_to_path`: `(2.0, -1.0, 1.0)`, velocity `(0.0, 1.0, 0.0)`
  - `cross_ypos_to_path`: `(2.0, 1.0, 1.0)`, velocity `(0.0, -1.0, 0.0)`
  - `side_static_ypos`: `(2.0, 1.0, 1.0)`, velocity `(0.0, 0.0, 0.0)`

结果表：

| case | policy | raw x | raw y | raw z | cmd x | cmd y | speed_xy |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| front_static | author | 0.528 | 0.137 | 0.467 | 0.528 | 0.137 | 0.545 |
| front_static | own1500 | 0.100 | 0.091 | 0.353 | 0.100 | 0.091 | 0.135 |
| front_static | dynstopfinal | 0.107 | 0.286 | -0.033 | 0.107 | 0.286 | 0.305 |
| front_oncoming | author | -0.036 | 0.488 | 0.465 | -0.036 | 0.488 | 0.489 |
| front_oncoming | own1500 | -0.314 | -0.310 | 0.107 | -0.314 | -0.310 | 0.441 |
| front_oncoming | dynstopfinal | -0.007 | 0.010 | -0.001 | -0.007 | 0.010 | 0.012 |
| cross_yneg_to_path | author | -0.643 | 0.707 | 0.329 | -0.643 | 0.707 | 0.955 |
| cross_yneg_to_path | own1500 | 0.283 | 0.532 | 0.246 | 0.283 | 0.532 | 0.603 |
| cross_yneg_to_path | dynstopfinal | 0.429 | 0.582 | -0.048 | 0.429 | 0.582 | 0.723 |
| cross_ypos_to_path | author | -0.559 | 0.581 | 0.599 | -0.559 | 0.581 | 0.807 |
| cross_ypos_to_path | own1500 | -0.163 | -0.083 | 0.607 | -0.163 | -0.083 | 0.183 |
| cross_ypos_to_path | dynstopfinal | -0.015 | 0.019 | 0.006 | -0.015 | 0.019 | 0.024 |
| side_static_ypos | author | 0.948 | -0.870 | 0.581 | 0.948 | -0.870 | 1.287 |
| side_static_ypos | own1500 | 0.189 | -0.720 | 0.741 | 0.189 | -0.720 | 0.744 |
| side_static_ypos | dynstopfinal | 0.555 | -0.603 | 0.148 | 0.555 | -0.603 | 0.820 |

日志检查：

```text
Traceback|ERROR|Error|Exception|failed|Aborted|Segmentation|terminate
```

结果：未命中。

观察：

- 在这 15 个节点层测试里，`safe_action_node` 没有改变 x/y。
- `safe_action_node` 主要把部分 checkpoint 的 z 速度压到 0。
- 最终 `/unitree_go2/cmd_vel` 因 `height_control=False` 也会把 z 方向置 0。
- 因此这些 case 的平面动作差异主要来自 policy raw action，而不是 safe_action 后处理。

初步解释：

- `dynstopfinal` 在 `front_static` 中比 `own1500` 给出更明显横向绕让。
- `dynstopfinal` 在 `front_oncoming` 和 `cross_ypos_to_path` 中几乎停住，说明它对某些直接威胁输入非常保守。
- 作者 checkpoint 在两个横穿 case 中给出明显后退 + 横向避让，说明作者 policy 在这些 ROS2 编码输入下并不弱；之前 quick-demo 中作者表现差，更可能是简化 evaluator 与真实 ROS2 输入分布不一致。
- `own1500` 和 `dynstopfinal` 在 `cross_yneg_to_path` 中保持前进并横向避让；这不一定坏，但需要连续轨迹验证，单步 action 不能直接等价为成功。

边界：

- 这是单步 ROS2 节点层 action probe，不是闭环轨迹评估。
- dynamic obstacle 是 stub，不是真实 depth/color detector 输出。
- 这个结果主要用于检查输入编码和 policy 行为趋势，不能直接宣称复现成功。

下一步：

1. 如果继续做 ROS2 节点层验证，应把单步 probe 扩展为短 horizon rollout：把上一帧 `cmd_vel` 积分成下一帧 odom，再重复调用节点。
2. 或者回到 Isaac eval，尝试绕过 GPU reset bug 后做文本化 eval。
3. 在真实 ROS2/机器人前，必须保留作者 checkpoint 作为部署参考，不应只依赖自训练 policy。

## 2026-04-18 ROS2 短 horizon stub rollout

目的：

- 单步 action probe 只能看一帧动作。
- 为了更接近闭环行为，新增短 horizon rollout：
  - 用 ROS2 `navigation_node.py` 输出 `/unitree_go2/cmd_vel`；
  - 将 `cmd_vel` 积分成下一帧 odom；
  - 持续发布 odom 和 goal；
  - dynamic obstacle stub 根据速度随时间移动。
- 这仍是简化文本闭环，不是真实机器人/仿真动力学。

新增/调整：

```text
ros2/tools/run_policy_stub_rollout.py
ros2/tools/dynamic_obstacle_stub.py
```

`dynamic_obstacle_stub.py` 新增：

```text
--integrate-velocity
```

开启后，stub 返回的障碍位置会按 `pos0 + velocity * elapsed_time` 移动。

语法检查：

```bash
source /opt/ros/humble/setup.bash
/home/ubuntu/miniconda3/envs/NavRL/bin/python -m py_compile \
  ros2/tools/dynamic_obstacle_stub.py \
  ros2/tools/run_policy_stub_rollout.py \
  ros2/tools/run_policy_stub_scan.py \
  ros2/navigation_runner/scripts/navigation.py
```

结果：通过。

运行命令：

```bash
source /opt/ros/humble/setup.bash
source /home/ubuntu/projects/navrl_ros2_ws/install/setup.bash
export PATH=/home/ubuntu/miniconda3/envs/NavRL/bin:$PATH
export ROS_LOG_DIR=/home/ubuntu/projects/navrl_ros2_ws/log/ros

/home/ubuntu/miniconda3/envs/NavRL/bin/python \
  /home/ubuntu/projects/NavRL/ros2/tools/run_policy_stub_rollout.py \
  --output /home/ubuntu/projects/NavRL/ros2/tools/policy_stub_rollout_20260418.csv \
  --domain-start 130 \
  --steps 60 \
  --dt 0.1
```

输出：

```text
ros2/tools/policy_stub_rollout_20260418.csv
```

检查：

```text
rows=360
blank_cmd_rows=0
Traceback|ERROR|Error|Exception|failed|Aborted|Segmentation|terminate: 未命中
```

配置：

- checkpoints：
  - `author`
  - `own1500`
  - `dynstopfinal`
- agent 初始位置：
  - `(0.0, 0.0, 1.0)`
- goal：
  - `(5.0, 0.0, 1.0)`
- rollout：
  - `dt=0.1`
  - `steps=60`
  - 约 6 秒
- cases：
  - `front_oncoming`: obstacle `(2.0, 0.0, 1.0)`, velocity `(-1.0, 0.0, 0.0)`
  - `cross_yneg_to_path`: obstacle `(2.0, -1.0, 1.0)`, velocity `(0.0, 1.0, 0.0)`

结果表：

| case | policy | final x | final y | goal dist | min obs dist |
| --- | --- | ---: | ---: | ---: | ---: |
| cross_yneg_to_path | author | 4.128 | 0.422 | 0.969 | 0.527 |
| cross_yneg_to_path | dynstopfinal | 4.062 | 0.105 | 0.944 | 0.916 |
| cross_yneg_to_path | own1500 | 4.022 | 0.053 | 0.980 | 0.929 |
| front_oncoming | author | 4.182 | 0.407 | 0.914 | 0.176 |
| front_oncoming | dynstopfinal | 4.015 | 0.144 | 0.996 | 0.076 |
| front_oncoming | own1500 | 4.019 | 0.061 | 0.983 | 0.059 |

观察：

- 在 `front_oncoming` 中，三者都接近目标，但最小障碍距离都很小：
  - `author`: `0.176`
  - `own1500`: `0.059`
  - `dynstopfinal`: `0.076`
- 在这个简化闭环里，`front_oncoming` 不能证明任何一个 policy 足够安全。
- 在 `cross_yneg_to_path` 中：
  - `author` 最小障碍距离 `0.527`
  - `own1500` 最小障碍距离 `0.929`
  - `dynstopfinal` 最小障碍距离 `0.916`
- 这个横穿场景里，自训练两个 checkpoint 在简化闭环中保留了更大障碍距离。

重要解释：

- 这是非常简化的文本闭环：
  - 没有真实动力学；
  - 没有控制延迟；
  - 没有真实地图更新；
  - 没有真实 detector；
  - 没有机器人尺寸碰撞判定；
  - 只是把 `/cmd_vel` 积分为下一帧 odom。
- 因此它只能作为 ROS2 节点输入/输出链路和 policy 行为趋势证据，不能当作最终复现实验。
- 但它比单步 action probe 更进一步，因为它至少让 odom 随 policy 输出滚动变化。

下一步判断：

- 如果继续 ROS2 文本闭环，应加入：
  - 机器人半径；
  - 障碍半径；
  - collision 判定；
  - reach 判定；
  - 多 seed / 多 obstacle case；
  - 轨迹 CSV 汇总脚本。
- 如果想更接近论文复现，下一阶段应回到 Isaac eval 或真实仿真，而不是无限扩展文本 stub。

### ROS2 rollout 增加 reach / collision 判定

目的：

- 上一版 rollout 只有 final position、goal distance、min obstacle distance。
- 新版额外生成 summary CSV，加入简化几何判定：
  - `reached`
  - `collision`
  - `timeout`
  - `min_clearance_2d`

脚本更新：

```text
ros2/tools/run_policy_stub_rollout.py
```

新增参数：

```text
--robot-radius 0.3
--obstacle-size-xy 0.8
--reach-distance 1.0
--summary-output <path>
```

默认计算：

```text
obs_radius = sqrt(0.8^2 + 0.8^2) / 2 = 0.5657
min_clearance_2d = min_obs_dist_2d - robot_radius - obs_radius
collision = min_clearance_2d <= 0
reached = final_goal_dist <= 1.0
```

注意：

- 这仍是简化 2D 几何判定。
- collision 优先级高于 reached；如果轨迹中擦到障碍但最后进了 goal range，状态记为 `collision`。

运行命令：

```bash
source /opt/ros/humble/setup.bash
source /home/ubuntu/projects/navrl_ros2_ws/install/setup.bash
export PATH=/home/ubuntu/miniconda3/envs/NavRL/bin:$PATH
export ROS_LOG_DIR=/home/ubuntu/projects/navrl_ros2_ws/log/ros

/home/ubuntu/miniconda3/envs/NavRL/bin/python \
  /home/ubuntu/projects/NavRL/ros2/tools/run_policy_stub_rollout.py \
  --output /home/ubuntu/projects/NavRL/ros2/tools/policy_stub_rollout_20260418.csv \
  --domain-start 150 \
  --steps 60 \
  --dt 0.1
```

输出：

```text
ros2/tools/policy_stub_rollout_20260418.csv
ros2/tools/policy_stub_rollout_20260418_summary.csv
```

检查：

```text
rows=360
blank_cmd_rows=0
Traceback|ERROR|Error|Exception|failed|Aborted|Segmentation|terminate: 未命中
```

summary 结果：

| case | policy | status | reached | collision | final x | final y | goal dist | min obs dist | min clearance |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| front_oncoming | author | collision | 1 | 1 | 4.163 | 0.381 | 0.920 | 0.164 | -0.702 |
| front_oncoming | own1500 | collision | 1 | 1 | 4.019 | 0.062 | 0.983 | 0.060 | -0.806 |
| front_oncoming | dynstopfinal | collision | 1 | 1 | 4.013 | 0.147 | 0.997 | 0.076 | -0.789 |
| cross_yneg_to_path | author | collision | 1 | 1 | 4.132 | 0.419 | 0.964 | 0.512 | -0.354 |
| cross_yneg_to_path | own1500 | reached | 1 | 0 | 4.026 | 0.056 | 0.976 | 0.927 | 0.062 |
| cross_yneg_to_path | dynstopfinal | reached | 1 | 0 | 4.062 | 0.105 | 0.943 | 0.915 | 0.050 |

解释：

- `front_oncoming` 在当前简化闭环中，三组 checkpoint 都会发生几何 collision。
- 这说明这个 case 不能用来证明任何 policy 足够安全。
- `cross_yneg_to_path` 中：
  - 作者 checkpoint 在该简化闭环里 collision；
  - `own1500` 和 `dynstopfinal` 都 reached，且 min clearance 略为正；
  - 两者 clearance 都不大，因此仍不能作为真机安全证据。
- 这个结果比单步 action probe 更接近闭环，但仍不等价于真实仿真或实机。

当前服务器侧最有价值的下一步：

1. 增加更多 rollout cases 和重复 seeds。
2. 把 rollout summary 做成一张稳定表。
3. 尝试接 Isaac eval 或真实传感器链路，避免在文本 stub 上过度优化。

### ROS2 rollout 扩展到 5 个动态障碍 case

目的：

- 上一版短闭环只有两个 case，覆盖太窄。
- 将 rollout case 扩展到与单步 scan 一致的 5 个输入：
  - `front_static`
  - `front_oncoming`
  - `cross_yneg_to_path`
  - `cross_ypos_to_path`
  - `side_static_ypos`

脚本更新：

```text
ros2/tools/run_policy_stub_rollout.py
```

运行：

```bash
source /opt/ros/humble/setup.bash
source /home/ubuntu/projects/navrl_ros2_ws/install/setup.bash
export PATH=/home/ubuntu/miniconda3/envs/NavRL/bin:$PATH
export ROS_LOG_DIR=/home/ubuntu/projects/navrl_ros2_ws/log/ros

/home/ubuntu/miniconda3/envs/NavRL/bin/python \
  /home/ubuntu/projects/NavRL/ros2/tools/run_policy_stub_rollout.py \
  --output /home/ubuntu/projects/NavRL/ros2/tools/policy_stub_rollout_20260418.csv \
  --domain-start 170 \
  --steps 60 \
  --dt 0.1
```

检查：

```text
rollout_rows=900
blank_cmd_rows=0
summary_rows=15
Traceback|ERROR|Error|Exception|failed|Aborted|Segmentation|terminate: 未命中
```

summary：

| case | policy | status | reached | collision | timeout | goal dist | min clearance |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| front_static | author | timeout | 0 | 0 | 1 | 2.856 | 0.886 |
| front_static | own1500 | timeout | 0 | 0 | 1 | 2.327 | 0.631 |
| front_static | dynstopfinal | timeout | 0 | 0 | 1 | 2.856 | 1.082 |
| front_oncoming | author | collision | 1 | 1 | 0 | 0.918 | -0.691 |
| front_oncoming | own1500 | collision | 1 | 1 | 0 | 0.978 | -0.805 |
| front_oncoming | dynstopfinal | collision | 1 | 1 | 0 | 0.998 | -0.789 |
| cross_yneg_to_path | author | collision | 1 | 1 | 0 | 0.942 | -0.399 |
| cross_yneg_to_path | own1500 | reached | 1 | 0 | 0 | 0.979 | 0.064 |
| cross_yneg_to_path | dynstopfinal | reached | 1 | 0 | 0 | 0.944 | 0.051 |
| cross_ypos_to_path | author | reached | 1 | 0 | 0 | 0.920 | 0.064 |
| cross_ypos_to_path | own1500 | reached | 1 | 0 | 0 | 0.965 | 0.016 |
| cross_ypos_to_path | dynstopfinal | reached | 1 | 0 | 0 | 0.971 | 0.064 |
| side_static_ypos | author | reached | 1 | 0 | 0 | 0.979 | 0.647 |
| side_static_ypos | own1500 | timeout | 0 | 0 | 1 | 1.093 | 0.987 |
| side_static_ypos | dynstopfinal | reached | 1 | 0 | 0 | 0.974 | 0.872 |

按 policy 汇总：

```text
author:       reached=2, collision=2, timeout=1
own1500:      reached=2, collision=1, timeout=2
dynstopfinal: reached=3, collision=1, timeout=1
```

观察：

- `front_static` 三者都不碰撞，但 6 秒内都没到 goal range；说明 horizon 太短或绕行过大。
- `front_oncoming` 三者都 collision，是当前文本闭环中最危险的 case。
- `cross_yneg_to_path` 中作者 checkpoint collision，两个自训练 checkpoint reached。
- `cross_ypos_to_path` 三者都 reached，但 `own1500` clearance 很小。
- `side_static_ypos` 中 `dynstopfinal` 和作者 reached，`own1500` timeout。

当前谨慎结论：

- 在这组简化 ROS2 文本闭环里，`dynstopfinal` 的 summary 最好：
  - reached 3/5；
  - collision 1/5；
  - timeout 1/5。
- 但这个结论不能外推到真实仿真或真机，因为：
  - 动态障碍来自 stub；
  - 没有真实感知；
  - 没有真实动力学；
  - 没有控制延迟；
  - 没有多障碍、多 seed。
- 它的价值是：证明 `dynstopfinal` 在作者 ROS2 `navigation_node.py` 输入/输出路径下不只是能加载，还在若干受控闭环场景里表现出合理避障趋势。

下一步：

- 若继续 ROS2 文本路线：增加多 seed、多障碍和轨迹图。
- 若继续复现主线：优先尝试真实/合成 depth 或 pointcloud 输入，让 `dynamic_detector_node` 和 `occupancy_map_node` 不再只是空图/stub。

## 2026-04-18 Policy 备份到 GitHub

目的：

- 服务器可能被回收，需要把关键自训练 policy 保存到 GitHub。
- 不把整个 `runs/` 目录推上去，只保存当前最有价值的少数 checkpoint。
- 这一步是备份复现实验产物，不表示复现已经完成。

新增目录：

```text
policies/
```

保存的 checkpoint：

```text
policies/dynstopfinal_20260418/checkpoint_final.pt
policies/own1500_20260417/checkpoint_1500.pt
policies/README.md
```

SHA256：

```text
2644f67a3979d42e409090c7935316838cbb7a01f0aa54843e80cdb25dd4907e  policies/dynstopfinal_20260418/checkpoint_final.pt
b40a309fdaa5e1a9e1c1bcd8c0c77ec997428e881aeeab9f86f5ad44b64cc435  policies/own1500_20260417/checkpoint_1500.pt
```

选择理由：

- `dynstopfinal_20260418`：
  - 当前最强自训练候选；
  - 来自 5M `dynamic_stop_penalty` ablation；
  - 在 quick-demo dynamic path-crossing 和 ROS2 节点层动态障碍输入里表现最好或最有价值。
- `own1500_20260417`：
  - 无 ablation 的稳定 baseline；
  - 用于后续判断 `dynamic_stop_penalty` 的收益是否真实。

注意：

- `.pt` 文件被 `.gitignore` 默认忽略，提交时需要显式 `git add -f`。
- 暂时不提交完整 `runs/`、`ckpts/`、`logs/`。
- 暂时不提交所有中间 checkpoint，避免仓库膨胀。
