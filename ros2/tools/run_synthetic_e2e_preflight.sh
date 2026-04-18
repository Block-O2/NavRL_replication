#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAVRL_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ROS2_WS="${NAVRL_ROS2_WS:-/home/ubuntu/projects/navrl_ros2_ws}"
CONDA_PYTHON="${NAVRL_CONDA_PYTHON:-/home/ubuntu/miniconda3/envs/NavRL/bin/python}"
ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/humble/setup.bash}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-198}"
NAVRL_CHECKPOINT_FILE="${NAVRL_CHECKPOINT_FILE:-}"
OUT="${1:-$NAVRL_ROOT/runs/ros2_synthetic_e2e_preflight_$(date +%Y%m%d_%H%M%S)}"

mkdir -p "$OUT"

source "$ROS_DISTRO_SETUP"
source "$ROS2_WS/install/setup.bash"
export PATH="$(dirname "$CONDA_PYTHON"):$PATH"
export ROS_LOG_DIR="${ROS_LOG_DIR:-$ROS2_WS/log/ros}"
export ROS_DOMAIN_ID

ros2 run map_manager occupancy_map_node > "$OUT/map.log" 2>&1 &
map_pid=$!
ros2 run navigation_runner safe_action_node > "$OUT/safe_action.log" 2>&1 &
safe_pid=$!
ros2 run onboard_detector dynamic_detector_node \
  --ros-args \
  --params-file "$NAVRL_ROOT/ros2/onboard_detector/cfg/dynamic_detector_param.yaml" \
  -p constrain_size:=false \
  > "$OUT/detector.log" 2>&1 &
det_pid=$!
nav_cmd=(ros2 run navigation_runner navigation_node.py --ros-args -p debug_action_topics:=true)
if [[ -n "$NAVRL_CHECKPOINT_FILE" ]]; then
  nav_cmd+=(-p "checkpoint_file:=$NAVRL_CHECKPOINT_FILE")
fi
"${nav_cmd[@]}" > "$OUT/navigation.log" 2>&1 &
nav_pid=$!

"$CONDA_PYTHON" "$NAVRL_ROOT/ros2/tools/synthetic_sensor_publisher.py" \
  --duration 25 \
  --rate 10 \
  --depth-mm 0 \
  --patch-depth-mm 2000 \
  --patch-size 160 \
  --yolo-box \
  --yolo-box-width 250 \
  --yolo-box-height 390 \
  --yolo-box-x-offset -12 \
  --yolo-box-y-offset 73 \
  > "$OUT/publisher.log" 2>&1 &
pub_pid=$!

ros2 topic pub -r 10 /unitree_go2/odom nav_msgs/msg/Odometry \
  "{header: {frame_id: map}, child_frame_id: base_link, pose: {pose: {position: {x: 0.0, y: 0.0, z: 1.0}, orientation: {w: 1.0}}}, twist: {twist: {linear: {x: 0.0, y: 0.0, z: 0.0}}}}" \
  > "$OUT/odom_pub.log" 2>&1 &
odom_pid=$!

cleanup() {
  kill "$map_pid" "$safe_pid" "$det_pid" "$nav_pid" "$pub_pid" "$odom_pid" 2>/dev/null || true
}
trap cleanup EXIT

sleep 8
ros2 topic pub --once /goal_pose geometry_msgs/msg/PoseStamped \
  "{header: {frame_id: map}, pose: {position: {x: 5.0, y: 0.0, z: 1.0}, orientation: {w: 1.0}}}" \
  > "$OUT/goal_pub.log" 2>&1 || true
sleep 8

timeout 8 ros2 service call /onboard_detector/get_dynamic_obstacles onboard_detector/srv/GetDynamicObstacles \
  "{current_position: {x: 0.0, y: 0.0, z: 1.0}, range: 5.0}" \
  > "$OUT/detector_service.txt" || true
timeout 8 ros2 topic echo --once /navigation_runner/debug/raw_cmd_vel_world > "$OUT/raw_cmd.txt" || true
timeout 8 ros2 topic echo --once /navigation_runner/debug/safe_cmd_vel_world > "$OUT/safe_cmd.txt" || true
timeout 8 ros2 topic echo --once /unitree_go2/cmd_vel > "$OUT/cmd_vel.txt" || true

echo "[NavRL] synthetic e2e preflight output: $OUT"
echo "[NavRL] detector service:"
sed -n "1,100p" "$OUT/detector_service.txt"
echo "[NavRL] raw policy action:"
sed -n "1,80p" "$OUT/raw_cmd.txt"
echo "[NavRL] safe action:"
sed -n "1,80p" "$OUT/safe_cmd.txt"
echo "[NavRL] cmd_vel:"
sed -n "1,100p" "$OUT/cmd_vel.txt"
echo "[NavRL] navigation log tail:"
tail -40 "$OUT/navigation.log"
