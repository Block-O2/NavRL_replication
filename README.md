# NavRL Replication and FCU Integration Notes

This repository is a reproduction and deployment-preparation fork of the official
NavRL project. It keeps the original NavRL code structure, adds reproduction
logs/checkpoints/evaluators, and now includes a minimal ROS1 bridge for preparing
NavRL policy output for the Fancinnov FCU interface.

The goal of this repo is not to redesign NavRL. The current direction is:

- Preserve the official NavRL policy observation/action semantics.
- Treat the policy as a local navigation and obstacle-avoidance module, not a
  low-level flight controller.
- Keep the official checkpoint as the most important deployment baseline.
- Keep self-trained checkpoints as controlled alternatives with clearly recorded
  evidence and limitations.
- Bridge to FCU through the official `mission_001` interface rather than inventing
  a new low-level flight interface.

## Credits

This work is based on:

- Official NavRL repository: https://github.com/Zhefan-Xu/NavRL
- NavRL paper: Zhefan Xu, Xinming Han, Haoyu Shen, Hanyu Jin, and Kenji Shimada,
  "NavRL: Learning Safe Flight in Dynamic Environments", IEEE Robotics and
  Automation Letters, 2025.
- FCU core reference: https://github.com/fancinnov/fcu_core_v2 and
  https://www.fancinnov.com/fcu_core_v2

Please cite the original NavRL paper if you use this project:

```bibtex
@ARTICLE{NavRL,
  author={Xu, Zhefan and Han, Xinming and Shen, Haoyu and Jin, Hanyu and Shimada, Kenji},
  journal={IEEE Robotics and Automation Letters},
  title={NavRL: Learning Safe Flight in Dynamic Environments},
  year={2025},
  volume={10},
  number={4},
  pages={3668-3675},
  doi={10.1109/LRA.2025.3546069}
}
```

## Repository Map

Important files and directories:

- `WORKLOG_NAVRL_REPRO.md`
  - The main reproduction log. Read this first before changing training,
    evaluation, or deployment code.
- `policies/`
  - Selected reproduction checkpoints and policy notes.
- `quick-demos/`
  - Official quick demos plus text evaluators and policy comparison tools.
- `isaac-training/`
  - Training and Isaac eval code, including clean no-close/no-eval helpers.
- `ros1/`
  - Official ROS1 deployment packages plus the new FCU bridge.
- `ros2/`
  - Official ROS2 deployment packages and synthetic preflight tools used during
    reproduction.
- `docs/FCU_NAVRL_BRIDGE.md`
  - Detailed notes on FCU topics, message fields, coordinate conversion, and
    the dry-run checklist.

## Current Policy Status

The policy conclusions below come from `WORKLOG_NAVRL_REPRO.md`. They should not
be replaced by memory or a single new evaluator run.

### Official Author Checkpoint

Path:

```text
quick-demos/ckpts/navrl_checkpoint.pt
ros1/navigation_runner/scripts/ckpts/navrl_checkpoint.pt
ros2/navigation_runner/scripts/ckpts/navrl_checkpoint.pt
```

Role:

- Primary baseline for "closest to author intent".
- Stronger than the self-trained checkpoints in larger Isaac CPU evals that are
  closer to the author's obstacle counts.
- Still not a direct real-robot safety guarantee; it must be tested through the
  full deployment chain.

### Self-Trained Checkpoints

Paths:

```text
policies/own1500_20260417/checkpoint_1500.pt
policies/dynstopfinal_20260418/checkpoint_final.pt
```

Current interpretation:

- `own1500` is the stable no-ablation self-trained baseline.
- `dynstopfinal` is the strongest self-trained candidate in ROS2-style
  offline/path-crossing tests, but it comes from a `dynamic_stop_penalty` reward
  ablation.
- `dynstopfinal` should not silently replace the author checkpoint for real
  deployment preparation.
- `ownfinal` is not the preferred deployment candidate because previous traces
  showed it can slow down or stop in the path of crossing dynamic obstacles.

## What Has Already Been Done

From the work log:

- 1024 / 350 / 80 GPU 50M training completed and checkpoints were preserved.
- Quick-demo evaluators, ROS2-style offline evaluator, and path-crossing dynamic
  scenarios were built.
- A short 10M continuation from `checkpoint_1500.pt` was tested and did not
  improve dynamic path-crossing.
- Reward ablation was tested; `dynamic_stop_penalty` produced `dynstopfinal`.
- Isaac CPU eval-only entry points were added and used to compare author vs
  self-trained checkpoints.
- ROS2 synthetic preflight verified that both author checkpoint and
  `dynstopfinal` can be loaded by the real ROS2 navigation node and can produce
  raw/safe/cmd velocities.

Do not repeat these steps unless the work log is intentionally being updated
with a new controlled experiment.

## What Is Not Proven Yet

These are important boundaries:

- Training completion is not paper reproduction.
- Quick-demo and ROS2-style offline results are not real-robot evidence.
- Python safe-action approximations are not equivalent to the real C++ ROS
  `safe_action_node`.
- `dynstopfinal` is useful evidence, but not proof that the self-trained policy
  has reached the official author's performance.
- The FCU bridge in this repository is a dry-run-first deployment adapter, not a
  flight-tested autonomy stack.

## NavRL to FCU Bridge

New files:

```text
ros1/navigation_runner/scripts/navrl_fcu_bridge.py
ros1/navigation_runner/launch/navrl_fcu_bridge.launch
docs/FCU_NAVRL_BRIDGE.md
```

The bridge is intentionally thin:

- It subscribes to ROS odometry and goal topics.
- It builds the same NavRL observation structure used by the official ROS
  deployment code.
- It loads a specified checkpoint.
- It keeps the author-style obstacle gate:
  - no obstacle in range: direct velocity toward goal;
  - obstacle in range: use RL policy.
- It optionally calls the real ROS1 C++ safe-action service:
  - `/rl_navigation/get_safe_action`
- It converts the final velocity into a short-horizon FCU `mission_001`
  `Float32MultiArray`.
- It defaults to `dry_run=true`, publishing to a debug topic instead of
  commanding FCU.

### FCU Output Message

The FCU bridge expects `std_msgs/Float32MultiArray` with 11 elements:

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

The FCU code expects mission target position in FRU and attitude in FRD. The ROS
side used here is FLU. Therefore the bridge explicitly flips `y`, `vy`, and
`yaw` at the FCU boundary. This matches the official FCU code comments and
implementation.

### Dry-Run Start

Use dry-run first:

```bash
conda activate NavRL
source /opt/ros/noetic/setup.bash
source /path/to/catkin_ws/devel/setup.bash
roslaunch navigation_runner navrl_fcu_bridge.launch dry_run:=true device:=cuda:0 checkpoint_file:=navrl_checkpoint.pt
```

Dry-run output:

```text
/navrl_fcu_bridge/dry_run_mission_001
```

Only after checking odom, goal, signs, mission fields, and emergency stop should
you disable dry-run:

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch dry_run:=false checkpoint_file:=navrl_checkpoint.pt
```

For Jetson/CPU-only testing:

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch dry_run:=true device:=cpu checkpoint_file:=navrl_checkpoint.pt
```

## Suggested Real-Robot Preparation Flow

1. Read `WORKLOG_NAVRL_REPRO.md`.
2. Build/source the ROS1 workspace containing this repository's `ros1` packages.
3. Install and build official `fcu_core_v2` in the same or an overlay ROS1
   workspace.
4. Start FCU core using the official launch:

```bash
roslaunch fcu_core fcu_core.launch
```

5. Start NavRL perception/safety if those services are available:

```bash
roslaunch navigation_runner safety_and_perception_real.launch use_safety_shield:=true
```

6. Start the FCU bridge in dry-run mode:

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch dry_run:=true checkpoint_file:=navrl_checkpoint.pt
```

7. Check topics:

```bash
rostopic echo /odom_global_001
rostopic echo /move_base_simple/goal
rostopic echo /navrl_fcu_bridge/dry_run_mission_001
rostopic list | grep get_safe_action
```

8. Confirm signs:

- Positive ROS `x` should command positive FCU mission `x`.
- Positive ROS `y` should appear as negative FCU mission `y`.
- Positive ROS yaw should appear as negative FCU mission yaw.

9. Publish emergency stop test:

```bash
rostopic pub /navrl_fcu_bridge/emergency_stop std_msgs/Bool "data: true" -1
```

10. Only then consider `dry_run:=false`, with low speed limits first:

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch \
  dry_run:=false \
  checkpoint_file:=navrl_checkpoint.pt \
  max_horizontal_speed:=0.2
```

## Recommended Checkpoint Choices for Deployment Preparation

Start with the author checkpoint:

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch \
  dry_run:=true \
  checkpoint_file:=navrl_checkpoint.pt
```

Test `dynstopfinal` only as a controlled alternative:

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch \
  dry_run:=true \
  checkpoint_file:=$(pwd)/policies/dynstopfinal_20260418/checkpoint_final.pt
```

Keep `own1500` as the conservative no-ablation self-trained baseline:

```bash
roslaunch navigation_runner navrl_fcu_bridge.launch \
  dry_run:=true \
  checkpoint_file:=$(pwd)/policies/own1500_20260417/checkpoint_1500.pt
```

## Validation Commands

Syntax checks:

```bash
python3 -m py_compile ros1/navigation_runner/scripts/navrl_fcu_bridge.py
bash -n quick-demos/run_repro_eval.sh
```

ROS launch parameter dump:

```bash
source /opt/ros/noetic/setup.bash
source /path/to/catkin_ws/devel/setup.bash
roslaunch navigation_runner navrl_fcu_bridge.launch --dump-params
```

Fixed policy reproduction evaluator:

```bash
./quick-demos/run_repro_eval.sh
```

## Development Rules for This Repository

- Read `WORKLOG_NAVRL_REPRO.md` before changing training/eval/deployment logic.
- Do not restart long training unless there is a specific logged hypothesis.
- Do not replace the author checkpoint as the default deployment baseline.
- Do not change NavRL observation/action semantics casually.
- Do not treat offline approximations as real-robot evidence.
- Keep bridge/adaptation code thin and reversible.
