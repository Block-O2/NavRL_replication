# FCU Notes for NavRL ROS1 Bridge

This document summarizes the FCU facts used by the NavRL-FCU bridge. It is based
on the official `fcu_core_v2` source and docs, plus the local NavRL reproduction
work log.

## Sources

- FCU docs: https://www.fancinnov.com/fcu_core_v2
- FCU source: https://github.com/fancinnov/fcu_core_v2
- NavRL source: https://github.com/Zhefan-Xu/NavRL
- Local reproduction log: `WORKLOG_NAVRL_REPRO.md`

## FCU ROS Nodes

Official FCU launch starts:

- `fcu_bridge_001` through `fcu_bridge_006`
- `fcu_command`
- `fcu_mission`
- RViz and robot state publisher helpers

For a single aircraft, the relevant path is usually:

```text
odom source -> fcu_bridge_001 -> odom_global_001
goal source -> fcu_mission -> mission_001 -> fcu_bridge_001 -> FCU
```

The NavRL bridge does not replace `fcu_bridge_001`. It publishes the same
`mission_001` message that `fcu_mission` publishes, so FCU handling remains in
the official FCU stack.

## `fcu_bridge_001`

Important parameters from official code:

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

Important topics in the official launch:

```text
~odometry_001    -> /vins_estimator/odometry
~odom_global_001 -> odom_global_001
~goal_001        -> /move_base_simple/goal
~command         -> /fcu_command/command
~mission_001     -> /fcu_mission/mission_001
~motion_001      -> motion_001
```

In `fcu_bridge_001.cpp`, `missionHandler()` accepts only messages with exactly
11 float elements and forwards them to `mav_send_target()`.

## `mission_001` Message Layout

Message type:

```text
std_msgs/Float32MultiArray
```

Element layout:

```text
data[0]  yaw       rad
data[1]  yaw_rate  rad/s
data[2]  px        m
data[3]  py        m
data[4]  pz        m
data[5]  vx        m/s
data[6]  vy        m/s
data[7]  vz        m/s
data[8]  ax        m/s^2
data[9]  ay        m/s^2
data[10] az        m/s^2
```

`simple_target=true` in FCU means the target is treated as a simple target point:
position is primary, and velocity/acceleration are not the main interface. The
NavRL bridge therefore defaults to `use_velocity_fields=false` and sends a short
horizon position target derived from the policy velocity. This keeps the adapter
thin while avoiding a direct "velocity as low-level motor command" interpretation.

If you want to test velocity fields explicitly, launch with:

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch use_velocity_fields:=true
```

Do this only during controlled dry-run first.

## Coordinate Frames

The official FCU comments say:

```text
mission_xxx topics sent to the FCU use target position in FRU
and target attitude in FRD.
```

The official code repeatedly flips y:

- Odom from FCU to ROS: `odom_pub.pose.pose.position.y = -pose.y * 0.01`
- Goal from FCU mission packet to ROS goal: `goal_pub.pose.position.y = -set_position_target.y`
- Goal from ROS to mission: `mission_001.data[3] = -goal->pose.position.y`
- PositionCommand to mission: `mission_001.data[6] = -pose_plan->velocity.y`

The NavRL bridge follows the same boundary rule:

```text
ROS/NavRL FLU x  -> FCU mission x
ROS/NavRL FLU y  -> FCU mission -y
ROS/NavRL FLU z  -> FCU mission z
ROS/NavRL yaw    -> FCU mission -yaw
ROS/NavRL vy     -> FCU mission -vy, only if use_velocity_fields=true
```

This conversion is implemented in:

```text
ros1/navigation_runner/scripts/navrl_fcu_bridge.py
```

Specifically in `build_mission()`.

## NavRL Policy Layer

From the paper and official ROS code:

- NavRL policy is a local navigation / obstacle avoidance policy.
- It consumes robot internal state, static obstacle raycast, dynamic obstacle
  representation, and goal direction.
- It outputs velocity control, not motor commands.
- Deployment includes obstacle gating and optional safety shield.

The ROS1 bridge keeps these semantics:

- `state`: 8 dimensions, as in official ROS deployment.
- `lidar`: `1 x 36 x 4` raycast-derived static obstacle input.
- `direction`: goal direction vector.
- `dynamic_obstacle`: `1 x 5 x 10`.
- policy action: world velocity.

It does not change the observation/action definition.

## Bridge Inputs and Outputs

Default inputs:

```text
odom_topic: /odom_global_001
goal_topic: /move_base_simple/goal
emergency_stop_topic: /navrl_fcu_bridge/emergency_stop
raycast_service: /occupancy_map/raycast
dynamic_obstacle_service: /onboard_detector/get_dynamic_obstacles
safe_action_service: /rl_navigation/get_safe_action
```

Default outputs:

```text
dry_run=true:
  /navrl_fcu_bridge/dry_run_mission_001

dry_run=false:
  /fcu_mission/mission_001
```

The bridge logs:

- checkpoint path
- odom topic
- goal topic
- mission topic
- dry-run state
- obstacle gate state
- safe-action availability fallback
- current odom/goal distance
- policy velocity and final limited velocity
- safety hold reasons

## Launch Parameters

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

## Recommended Dry-Run Procedure

1. Source ROS and the catkin workspace.

```bash
source /opt/ros/noetic/setup.bash
source /path/to/catkin_ws/devel/setup.bash
```

2. Start FCU core.

```bash
roslaunch fcu_core fcu_core.launch
```

3. Start NavRL bridge in dry-run mode.

```bash
conda activate NavRL
roslaunch navigation_runner navrl_fcu_bridge.launch dry_run:=true checkpoint_file:=navrl_checkpoint.pt
```

4. Verify odom.

```bash
rostopic echo /odom_global_001
```

5. Send or inspect goal.

```bash
rostopic echo /move_base_simple/goal
```

6. Inspect dry-run mission output.

```bash
rostopic echo /navrl_fcu_bridge/dry_run_mission_001
```

7. Confirm sign convention:

- ROS goal `+y` should produce mission `data[3] < 0`.
- ROS yaw `+yaw` should produce mission `data[0] < 0`.

8. Test emergency stop.

```bash
rostopic pub /navrl_fcu_bridge/emergency_stop std_msgs/Bool "data: true" -1
```

9. Only after all checks pass, test real mission output at low speed.

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch \
  dry_run:=false \
  checkpoint_file:=navrl_checkpoint.pt \
  max_horizontal_speed:=0.2
```

## Policy Selection for FCU Tests

Default:

```text
author checkpoint: ros1/navigation_runner/scripts/ckpts/navrl_checkpoint.pt
```

Alternatives:

```text
policies/dynstopfinal_20260418/checkpoint_final.pt
policies/own1500_20260417/checkpoint_1500.pt
```

Use alternatives only with explicit labels in logs. Do not replace the author
checkpoint by default just because a simplified offline evaluator looks better.

## Known Gaps

- This bridge has not been flight-tested.
- Missing raycast/dynamic-obstacle services are tolerated by zero fallback, but
  that is only a compatibility mode for bring-up.
- Real safety claims require the actual ROS C++ `safe_action_node`, real odom,
  real perception, FCU dry-run checks, and controlled flight testing.
- The bridge currently sends short-horizon position targets by default. This is
  deliberate because FCU `simple_target=true` emphasizes target position.
- If the real FCU setup expects a different `simple_target` mode or external
  mission manager behavior, verify with FCU source before changing the bridge.
