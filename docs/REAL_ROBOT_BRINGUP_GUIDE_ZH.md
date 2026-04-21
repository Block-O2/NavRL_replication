# NavRL + FCU 真机接入与 RViz 标点指南

这份指南用于把当前复现仓库里的 NavRL policy，按作者部署思路，通过最小桥接接到 Fancinnov FCU 真机链路。

请先记住边界：

- NavRL policy 是局部导航/避障策略，不是底层飞控控制器。
- 真机主路径使用 `navrl_fcu_bridge.py`，不是直接使用作者的 `navigation_node.py` 控制 FCU。
- 默认使用作者 checkpoint：`navrl_checkpoint.pt`。
- `dynstopfinal` 和 `own1500` 只能作为带标签的自训练备选，不能默认替代作者 checkpoint。
- `dry_run=true` 是第一步，不要一上来向 FCU 真发 `/fcu_mission/mission_001`。

## 0. 打开正确仓库

当前应该使用你的复现仓库：

```text
https://github.com/Block-O2/NavRL_replication
```

不要继续在原作者 upstream 仓库里改；本机旧的 `/home/hank/research/NavRL` 已经删除：

```text
https://github.com/Zhefan-Xu/NavRL
```

在本机检查当前目录是不是复现仓库：

```bash
git remote -v
```

正确结果应该包含：

```text
git@github.com:Block-O2/NavRL_replication.git
```

如果看到的是：

```text
https://github.com/Zhefan-Xu/NavRL.git
```

说明你打开的是原作者仓库，不是复现仓库。

建议把复现仓库克隆到一个持久目录，例如：

```bash
cd /home/hank/research
git clone git@github.com:Block-O2/NavRL_replication.git NavRL_replication
code /home/hank/research/NavRL_replication
```

如果你已经在 VS Code 里打开了错误目录：

```text
File -> Open Folder -> /home/hank/research/NavRL_replication
```

或者终端执行：

```bash
code /home/hank/research/NavRL_replication
```

### 源码仓库和 ROS 工作空间的关系

这里最容易乱。请把两个概念分开：

```text
源码仓库:
  /home/hank/research/NavRL_replication

ROS1 catkin 工作空间:
  /home/hank/catkin_ws
```

`NavRL_replication` 是你用 IDE 打开、改代码、看文档、提交 Git 的地方。

`catkin_ws` 是 ROS 真正用来 `rospack find`、`roslaunch`、`rosrun` 的工作空间。

现在 `/home/hank/catkin_ws/src` 里应该有这些符号链接：

```text
/home/hank/catkin_ws/src/navigation_runner -> /home/hank/research/NavRL_replication/ros1/navigation_runner
/home/hank/catkin_ws/src/map_manager       -> /home/hank/research/NavRL_replication/ros1/map_manager
/home/hank/catkin_ws/src/onboard_detector  -> /home/hank/research/NavRL_replication/ros1/onboard_detector
/home/hank/catkin_ws/src/uav_simulator     -> /home/hank/research/NavRL_replication/ros1/uav_simulator
```

用下面命令检查：

```bash
ls -la /home/hank/catkin_ws/src
source /opt/ros/noetic/setup.bash
source /home/hank/catkin_ws/devel/setup.bash
rospack find navigation_runner
```

期望输出：

```text
/home/hank/catkin_ws/src/navigation_runner
```

再确认这个路径实际链接到复现仓库：

```bash
readlink -f /home/hank/catkin_ws/src/navigation_runner
```

期望输出：

```text
/home/hank/research/NavRL_replication/ros1/navigation_runner
```

如果 `rospack find navigation_runner` 指到 `/home/hank/research/NavRL/ros1/navigation_runner`，说明又回到了原作者仓库或旧 symlink，必须先修正 symlink。

可以直接用仓库里的工具脚本修正：

```bash
cd /home/hank/research/NavRL_replication
./tools/link_ros1_catkin_ws.sh /home/hank/catkin_ws
./tools/check_ros1_workspace.sh /home/hank/catkin_ws
```

### 推荐 source 顺序

本机现在没有 conda，也不需要为了 ROS1 仿真硬装 conda。当前已经配置好的环境是：

```text
NavRL policy venv: /home/hank/venvs/navrl-ros1
ROS1 catkin workspace: /home/hank/catkin_ws
源码仓库: /home/hank/research/NavRL_replication
```

每个要跑 NavRL ROS1 节点的新终端，都先执行一个统一入口：

```bash
cd /home/hank/research/NavRL_replication
source tools/source_navrl_ros1.sh
```

这个脚本内部做三件事：

- 激活 `/home/hank/venvs/navrl-ros1`，提供 `torch`、`hydra`、`tensordict`、`torchrl` 等 policy 推理依赖。
- source `/opt/ros/noetic/setup.bash`，提供 `roscore`、`roslaunch`、`rostopic` 等 ROS Noetic 基础命令。
- source `/home/hank/catkin_ws/devel/setup.bash`，把当前 catkin 工作空间里的 `navigation_runner`、`map_manager`、`onboard_detector`、`uav_simulator` 加入 ROS 环境。

如果这个终端只跑 `roscore`，可以只 source ROS：

```bash
source /opt/ros/noetic/setup.bash
roscore
```

如果这个终端要跑 `fcu_core`，还必须确保 `fcu_core` 也在当前 catkin 工作空间或另一个已经 source 的 overlay 工作空间里：

```bash
rospack find fcu_core
```

如果找不到 `fcu_core`，`roslaunch fcu_core fcu_core.launch` 一定会失败。`fcu_core` 只是真机 FCU 需要，本机 Gazebo 仿真不需要。

### 本机 Gazebo 仿真启动命令

仿真优先跑作者原始 ROS1 链路，不走 `navrl_fcu_bridge.py`。原因是 `navrl_fcu_bridge.py` 是给真机 FCU `mission_001` 做 dry-run/低速接入的，Gazebo 里的四旋翼实际听的是 `/CERLAB/quadcopter/cmd_vel` 和 setpoint。

终端 1，ROS master：

```bash
source /opt/ros/noetic/setup.bash
roscore
```

终端 2，Gazebo 四旋翼仿真：

```bash
cd /home/hank/research/NavRL_replication
source tools/source_navrl_ros1.sh
roslaunch uav_simulator start.launch
```

终端 3，地图、fake detector、safe action、RViz：

```bash
cd /home/hank/research/NavRL_replication
source tools/source_navrl_ros1.sh
roslaunch navigation_runner safety_and_perception_sim.launch \
  use_px4:=false \
  use_safety_shield:=true \
  rviz:=true
```

终端 4，作者 ROS1 navigation node 加载 checkpoint 并输出仿真控制：

```bash
cd /home/hank/research/NavRL_replication
source tools/source_navrl_ros1.sh
rosrun navigation_runner navigation_node.py
```

RViz 里用 `2D Nav Goal` 标点。标点后目标会发布到 `/move_base_simple/goal`，`navigation_node.py` 订阅目标和 `/CERLAB/quadcopter/odom`，再向 Gazebo 发布 `/CERLAB/quadcopter/cmd_vel`。

### 真机 FCU 启动命令速查

旧的 `/home/hank/research/NavRL` 已经删除后，所有命令都统一使用：

```text
源码目录: /home/hank/research/NavRL_replication
ROS 工作空间: /home/hank/catkin_ws
```

终端 1，只跑 ROS master：

```bash
source /opt/ros/noetic/setup.bash
roscore
```

终端 2，启动 FCU：

```bash
cd /home/hank/research/NavRL_replication
source tools/source_navrl_ros1.sh
roslaunch fcu_core fcu_core.launch
```

如果 `roslaunch fcu_core ...` 失败，先检查：

```bash
rospack find fcu_core
```

终端 3，启动感知和 safety：

```bash
cd /home/hank/research/NavRL_replication
source tools/source_navrl_ros1.sh
roslaunch navigation_runner safety_and_perception_real.launch \
  use_safety_shield:=true \
  rviz:=true
```

终端 4，启动 NavRL bridge，先 dry-run：

```bash
cd /home/hank/research/NavRL_replication
source tools/source_navrl_ros1.sh
roslaunch navigation_runner navrl_fcu_bridge.launch \
  dry_run:=true \
  device:=cpu \
  checkpoint_file:=navrl_checkpoint.pt
```

有 CUDA 且确认当前 venv 的 PyTorch 支持 CUDA 时，再把 `device:=cpu` 改成：

```text
device:=cuda:0
```

低速真发只在 dry-run 检查全部通过后执行：

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch \
  dry_run:=false \
  device:=cpu \
  checkpoint_file:=navrl_checkpoint.pt \
  max_horizontal_speed:=0.2 \
  command_horizon:=0.2
```

### 本机旧目录处理

本机曾经还有一个原作者 upstream clone：

```text
/home/hank/research/NavRL
```

它的 remote 是：

```text
https://github.com/Zhefan-Xu/NavRL.git
```

现在这个旧目录已经删除，也不再被 `/home/hank/catkin_ws/src` 的 ROS symlink 使用。后续开发、文档和真机 bring-up 都以：

```text
/home/hank/research/NavRL_replication
```

为准。

如果以后需要重新参考原作者 upstream，另行 clone 到一个明确的归档/参考目录，不要再占用 `/home/hank/research/NavRL` 这个容易混淆的名字。

当前本机只应存在：

```text
/home/hank/research/NavRL_replication
```

`navigation_runner` 必须指向 `NavRL_replication`，而不是旧的 `NavRL`：

```bash
readlink -f /home/hank/catkin_ws/src/navigation_runner
```

## 1. 代码框架怎么理解

核心文件：

```text
ros1/navigation_runner/scripts/navrl_fcu_bridge.py
ros1/navigation_runner/launch/navrl_fcu_bridge.launch
ros1/navigation_runner/scripts/navigation.py
ros1/navigation_runner/scripts/navigation_node.py
ros1/navigation_runner/scripts/utils.py
ros1/navigation_runner/scripts/policy_server.py
```

### `utils.py`

`utils.py` 里最重要的是：

```text
vec_to_new_frame()
```

它把世界系向量转到以目标方向为 x 轴的局部目标坐标系。NavRL 的 observation 依赖这个坐标变换，不要随意改。

### `navigation_node.py` 和 `navigation.py`

这是作者 ROS1 原始部署入口。它的主要链路是：

```text
/move_base_simple/goal
  -> Navigation
  -> NavRL observation
  -> policy/direct-goal gate
  -> safe_action
  -> MAVROS/PX4 setpoint 或仿真 cmd_vel
```

这个节点适合理解作者逻辑，但 FCU 真机接入时不要让它和 `navrl_fcu_bridge.py` 同时控制同一架飞机。

### `policy_server.py`

这是一个把 policy 包成 ROS service 的旧式/可选节点。当前真机 bridge 已经直接加载 checkpoint，不需要现场额外启动它。

### `navrl_fcu_bridge.py`

这是当前 FCU 接入主节点。它做的事情是：

```text
订阅 FCU odom
订阅 RViz goal
按作者定义构建 NavRL observation
加载 checkpoint 做 policy 推理
保留作者 obstacle gate
可选调用 C++ safe_action_node
限速
做 ROS/FCU 坐标转换
发布 FCU mission_001
```

注意：它是部署适配器，不是新 planner。

## 2. 真机数据流

完整数据流：

```text
FCU / localization
  -> /odom_global_001
  -> navrl_fcu_bridge.py
  -> NavRL observation
  -> author checkpoint policy
  -> optional /rl_navigation/get_safe_action
  -> clamp
  -> ROS FLU to FCU mission frame conversion
  -> /fcu_mission/mission_001
  -> fcu_bridge_001
  -> flight controller
```

RViz 标点数据流：

```text
RViz 2D Nav Goal
  -> /move_base_simple/goal
  -> navrl_fcu_bridge.py goal_callback
  -> target_dir
  -> control loop
```

### FCU 关键接口事实

这些事实来自官方 `fcu_core_v2` 代码和资料，是 bridge 代码实现的依据。

官方 FCU launch 会启动：

```text
fcu_bridge_001 ... fcu_bridge_006
fcu_command
fcu_mission
RViz / robot_state_publisher 辅助节点
```

单机接入时，最相关的是 `fcu_bridge_001`：

```text
odom source -> fcu_bridge_001 -> /odom_global_001
NavRL bridge -> /fcu_mission/mission_001 -> fcu_bridge_001 -> FCU
```

`fcu_bridge_001` 官方 launch 里常见 remap：

```text
~odometry_001    -> /vins_estimator/odometry
~odom_global_001 -> odom_global_001
~goal_001        -> /move_base_simple/goal
~command         -> /fcu_command/command
~mission_001     -> /fcu_mission/mission_001
~motion_001      -> motion_001
```

`fcu_bridge_001.cpp` 里的 `missionHandler()` 只接受长度为 `11` 的 `Float32MultiArray`，然后转发给 `mav_send_target()`。

官方参数里最需要认识的是：

```text
DRONE_IP
USB_PORT
BANDRATE
channel
offboard
use_uwb
set_goal
simple_target
odom_init_x
odom_init_y
odom_init_z
```

其中 `simple_target=true` 表示 FCU 侧把目标当作简单目标点，位置是主接口，速度/加速度不是主要接口。因此当前 NavRL bridge 默认：

```text
use_velocity_fields=false
```

也就是把 policy 输出速度转换成短时间 horizon 后的位置目标，而不是把 policy 速度直接当底层速度控制命令。

如果以后要测试速度字段，只能先 dry-run：

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch \
  dry_run:=true \
  use_velocity_fields:=true
```

不要在没有 dry-run 验证的情况下直接对真机打开速度字段。

## 3. 启动前检查

先确认 ROS 环境：

```bash
source /opt/ros/noetic/setup.bash
source /home/hank/catkin_ws/devel/setup.bash
```

确认当前工作区包含 `navigation_runner`：

```bash
rospack find navigation_runner
```

确认当前仓库是复现仓库：

```bash
git remote -v
```

确认 checkpoint 存在：

```bash
ls ros1/navigation_runner/scripts/ckpts/navrl_checkpoint.pt
```

## 4. 官方起飞前安全检查

这一节不是 NavRL 的算法要求，而是 Fancinnov/FanciSwarm 真机起飞前检查。不要跳过。

官方资料里明确提到的电池事项：

- 不使用无人机时，确保电池与飞控扩展板彻底断开。
- 电池充满后及时从充电器拔下，避免过充/过放。
- 低电量报警时，应及时充电或更换电池。
- 严禁使用鼓包、漏液、包装破损的电池。
- 锂电池长时间不用时，电压至少维护到 `7.6V-7.7V`。
- 严禁将锂电池放电到 `6.4V` 以下，过放会造成不可逆损伤。

我目前没有在官方 FCU 资料里找到“允许起飞的最低电压必须是 X.X V”的明确阈值，所以不要在代码或流程里硬编一个起飞电压阈值。现场应按电池规格、App/FCU 显示、电池报警和实验室安全规范决定是否允许起飞。

FCU ROS 工程启动成功后，`fcu_bridge_001` 会打印类似信息：

```text
fcu_bridge 001 connect succeed
voltage: ... V
current: ... A
sat: ...
gnss: ...
```

起飞前必须看这些信息：

- `fcu_bridge 001 connect succeed` 已出现。
- 电压/电流在终端中正常打印。
- 没有低电压报警声。
- 定位状态满足当前场景要求。
- RViz 中轨迹显示正确。

官方资料里明确提到的环境/姿态检查：

- 无人机放置在水平面。
- 用户面朝机尾。
- 无人机前、后、左、右 `2m` 范围内空旷，无墙壁、无杂物。
- 室内飞行应确认地面纹理清晰，避免纯色、过暗、过亮、强反光地面。
- 室外搭载高精度 GNSS 模组时，关注 GNSS 定位状态；官方快速入门里写到 GNSS 定位状态为 `2` 时表示信号良好。
- 如果是没有高精度 GNSS、依赖室内定位/光流/测距的机型，按官方说明在启动提示音结束后，将飞机垂直地面拿起一次，超过 `1m` 后放下，用于确认激光测距/定位链路正常。

ROS 侧进入 NavRL 前，还要做这几个检查：

```bash
rostopic echo /odom_global_001
rostopic echo -n 1 /odom_global_001/header
rostopic info /fcu_mission/mission_001
```

拿起飞机在安全状态下小范围移动一圈，通过 RViz 检查轨迹方向是否正确。只有轨迹方向、坐标轴、`y/yaw` 符号都确认过，才进入 NavRL dry-run。

## 5. 连接真机并启动 FCU

先启动 FCU core：

```bash
roslaunch fcu_core fcu_core.launch
```

检查 odom：

```bash
rostopic echo /odom_global_001
```

检查 FCU mission 入口：

```bash
rostopic info /fcu_mission/mission_001
```

你需要看到 FCU 相关节点在订阅 `/fcu_mission/mission_001`。如果没有订阅者，不要进入 `dry_run=false`。

## 6. 启动感知与安全节点

如果现场要跑作者式感知/安全链路：

```bash
roslaunch navigation_runner safety_and_perception_real.launch use_safety_shield:=true rviz:=true
```

检查 safe action 服务：

```bash
rosservice list | grep safe_action
rosservice info /rl_navigation/get_safe_action
```

如果 `/rl_navigation/get_safe_action` 不存在，bridge 仍然可以跑，但这只是 bring-up 兼容模式，不能当成完整作者部署链路。

## 7. 启动 NavRL FCU bridge，先 dry-run

默认 CPU dry-run：

```bash
cd /home/hank/research/NavRL_replication
source tools/source_navrl_ros1.sh
roslaunch navigation_runner navrl_fcu_bridge.launch \
  dry_run:=true \
  device:=cpu \
  checkpoint_file:=navrl_checkpoint.pt
```

只有在确认当前 venv 的 PyTorch 支持 CUDA 后，才把 `device:=cpu` 改成 `device:=cuda:0`。

启动后应看到类似日志：

```text
[navrl_fcu_bridge] checkpoint: ...
[navrl_fcu_bridge] odom_topic: /odom_global_001
[navrl_fcu_bridge] goal_topic: /move_base_simple/goal
[navrl_fcu_bridge] mission_topic: /fcu_mission/mission_001
[navrl_fcu_bridge] dry_run_topic: /navrl_fcu_bridge/dry_run_mission_001
[navrl_fcu_bridge] dry_run: True
[navrl_fcu_bridge] author_obstacle_gate: True
[navrl_fcu_bridge] use_safe_action: True
```

如果 checkpoint 路径错，节点会在加载 policy 时失败。

bridge launch 的主要参数：

```text
dry_run                 default true
device                  default cuda:0
checkpoint_file         default navrl_checkpoint.pt
odom_topic              default /odom_global_001
goal_topic              default /move_base_simple/goal
mission_topic           default /fcu_mission/mission_001
dry_run_mission_topic   default /navrl_fcu_bridge/dry_run_mission_001
use_safe_action         default true
author_obstacle_gate    default true
height_control          default false
hold_current_z          default true
use_velocity_fields     default false
max_horizontal_speed    default 0.5
max_vertical_speed      default 0.3
command_horizon         default 0.2
control_rate            default 10.0
```

## 8. 打开 RViz 并标点

如果没有自动打开 RViz：

```bash
rosrun rviz rviz
```

设置 Fixed Frame。先看 odom frame：

```bash
rostopic echo -n 1 /odom_global_001/header
```

如果 header frame 是 `map`，RViz Fixed Frame 就填：

```text
map
```

如果 header frame 是 `odom`，就填：

```text
odom
```

在 RViz 里选择：

```text
2D Nav Goal
```

然后在地图/视图里点一个目标。它会发布：

```text
/move_base_simple/goal
```

确认 goal：

```bash
rostopic echo /move_base_simple/goal
```

bridge 收到后会打印：

```text
[navrl_fcu_bridge] goal: x=... y=... z=...
```

当前默认：

```text
hold_current_z=true
```

所以 RViz 目标主要控制水平 `x/y`，高度保持当前 odom 高度。

## 9. Dry-run 检查 mission 输出

查看 dry-run 输出：

```bash
rostopic echo /navrl_fcu_bridge/dry_run_mission_001
```

消息是 11 维：

```text
data[0]  yaw
data[1]  yaw_rate
data[2]  px
data[3]  py
data[4]  pz
data[5]  vx
data[6]  vy
data[7]  vz
data[8]  ax
data[9]  ay
data[10] az
```

默认 `use_velocity_fields=false`，所以主要看位置目标：

```text
data[2] x
data[3] y
data[4] z
```

必须检查坐标符号：

```text
ROS/NavRL x -> FCU mission x
ROS/NavRL y -> FCU mission -y
ROS/NavRL yaw -> FCU mission -yaw
```

也就是说，如果你在 RViz 点正 y 方向，dry-run mission 的 `data[3]` 应该往负方向变化。

## 10. 无障碍时它怎么飞

如果 raycast 和动态障碍都认为附近没有障碍：

```text
check_obstacle = False
  -> direct_goal_velocity
  -> optional safe_action
  -> clamp
  -> build_mission
```

日志里会看到：

```text
direct_goal_no_obstacle dry_run=True mission=[...]
odom=(...) goal=(...) dist=... obstacle=False policy=(...) final=(...)
```

这里即使实际选择的是直飞目标，代码仍会计算 policy velocity 用于日志对照。

## 11. 有障碍时它怎么避障

如果静态 raycast 或动态障碍服务报告附近有障碍：

```text
check_obstacle = True
  -> navrl_policy
  -> optional safe_action
  -> clamp
  -> build_mission
```

日志里会看到：

```text
navrl_policy dry_run=True mission=[...]
odom=(...) goal=(...) dist=... obstacle=True policy=(...) final=(...)
```

如果 `safe_action_node` 修改了动作，`policy=(...)` 和 `final=(...)` 会不同。

如果限幅触发，日志 reason 会带 `clamped`。

## 12. Emergency stop 测试

dry-run 阶段先测：

```bash
rostopic pub /navrl_fcu_bridge/emergency_stop std_msgs/Bool "data: true" -1
```

恢复：

```bash
rostopic pub /navrl_fcu_bridge/emergency_stop std_msgs/Bool "data: false" -1
```

注意：这个 emergency stop 是 bridge 层停止继续发新运动目标，不等价于物理急停。现场必须保留遥控器/FCU/电源级接管手段。

## 13. 真发前门槛

只有全部满足才考虑 `dry_run=false`：

- 电池状态确认过，没有低电压报警。
- FCU 终端正常打印电压/电流。
- 飞机周围 `2m` 空旷。
- 室内地面纹理或室外 GNSS 状态满足官方要求。
- `/odom_global_001` 稳定更新。
- `/move_base_simple/goal` 能收到 RViz 标点。
- `/navrl_fcu_bridge/dry_run_mission_001` 维度为 11。
- `x/y/z/yaw` 符号检查通过，尤其是 `y` 和 `yaw` 取反。
- `/fcu_mission/mission_001` 有 FCU 订阅者。
- `/rl_navigation/get_safe_action` 状态明确。
- 遥控器/人工接管准备好。
- 场地空旷。
- 第一次限速足够低。

第一次真发建议：

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch \
  dry_run:=false \
  device:=cuda:0 \
  checkpoint_file:=navrl_checkpoint.pt \
  max_horizontal_speed:=0.2 \
  command_horizon:=0.2
```

CPU：

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch \
  dry_run:=false \
  device:=cpu \
  checkpoint_file:=navrl_checkpoint.pt \
  max_horizontal_speed:=0.2 \
  command_horizon:=0.2
```

## 14. 常用检查命令

```bash
rostopic echo /odom_global_001
rostopic echo /move_base_simple/goal
rostopic echo /navrl_fcu_bridge/dry_run_mission_001
rostopic info /fcu_mission/mission_001
rosservice list | grep safe_action
rosservice list | grep occupancy_map
rosservice list | grep onboard_detector
```

如果 bridge 没动：

```bash
rostopic hz /odom_global_001
rostopic echo /move_base_simple/goal
```

如果没有 goal，它会等待 RViz 标点。

如果没有 odom，它会等待 FCU odom。

## 15. checkpoint 怎么选

默认作者 checkpoint：

```bash
checkpoint_file:=navrl_checkpoint.pt
```

自训练候选只能作为对照：

```bash
checkpoint_file:=/absolute/path/to/policies/dynstopfinal_20260418/checkpoint_final.pt
```

或者：

```bash
checkpoint_file:=/absolute/path/to/policies/own1500_20260417/checkpoint_1500.pt
```

现场主线建议：

```text
先作者 checkpoint
再 dry-run
再低速真发
再考虑自训练 checkpoint 对照
```

## 16. 不能做的事

不要同时运行：

```text
navigation_node.py
navrl_fcu_bridge.py
```

去控制同一架真机。

不要一开始就：

```text
dry_run=false
max_horizontal_speed=0.5 或更高
```

不要把 Python safe-action 近似结果当成真实 C++ `safe_action_node` 结论。

不要把 ROS2-style 离线 evaluator 当成真机飞行结论。

不要把 `dynstopfinal` 的离线优势当成默认部署理由。

## 17. 一句话流程

```text
FCU 发布 /odom_global_001；
RViz 发布 /move_base_simple/goal；
navrl_fcu_bridge.py 构建作者 NavRL observation；
无障碍时直飞目标；
有障碍时调用作者 checkpoint policy；
可选经过 C++ safe_action_node；
限速；
转换 y/yaw 符号；
dry-run 时发布 /navrl_fcu_bridge/dry_run_mission_001；
真发时发布 /fcu_mission/mission_001；
FCU 负责底层执行。
```

## 18. 资料来源

本指南的 FCU/电池/起飞前检查内容来自以下资料和代码：

- Fancinnov FanciSwarm 快速入门/支持页面。
- Fancinnov Mcontroller v7 / fcu_core_v2 ROS 说明页面。
- `fcu_core_v2/src/fcu_bridge_001.cpp` 中的 heartbeat 电压、电流、卫星和 GNSS 打印逻辑。
- `fcu_core_v2/src/fcu_mission.cpp` 中的 `mission_001` 字段与 y/yaw 取反逻辑。
