#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAVRL_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ROS2_WS="${NAVRL_ROS2_WS:-/home/ubuntu/projects/navrl_ros2_ws}"
CONDA_PYTHON="${NAVRL_CONDA_PYTHON:-/home/ubuntu/miniconda3/envs/NavRL/bin/python}"
ROS_DISTRO_SETUP="${ROS_DISTRO_SETUP:-/opt/ros/humble/setup.bash}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-196}"
OUT="${1:-$NAVRL_ROOT/runs/ros2_synthetic_detector_preflight_$(date +%Y%m%d_%H%M%S)}"

mkdir -p "$OUT"

source "$ROS_DISTRO_SETUP"
source "$ROS2_WS/install/setup.bash"
export PATH="$(dirname "$CONDA_PYTHON"):$PATH"
export ROS_LOG_DIR="${ROS_LOG_DIR:-$ROS2_WS/log/ros}"
export ROS_DOMAIN_ID

ros2 run onboard_detector dynamic_detector_node \
  --ros-args \
  --params-file "$NAVRL_ROOT/ros2/onboard_detector/cfg/dynamic_detector_param.yaml" \
  -p constrain_size:=false \
  > "$OUT/detector.log" 2>&1 &
det_pid=$!

"$CONDA_PYTHON" "$NAVRL_ROOT/ros2/tools/synthetic_sensor_publisher.py" \
  --duration 18 \
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

cleanup() {
  kill "$det_pid" "$pub_pid" 2>/dev/null || true
}
trap cleanup EXIT

sleep 5

timeout 8 ros2 topic echo --once /yolo_detector/detected_bounding_boxes > "$OUT/yolo_topic.txt" || true
timeout 8 ros2 topic echo --once /onboard_detector/dynamic_bboxes > "$OUT/dynamic_bboxes.txt" || true
timeout 12 ros2 service call /onboard_detector/get_dynamic_obstacles onboard_detector/srv/GetDynamicObstacles \
  "{current_position: {x: 0.0, y: 0.0, z: 1.0}, range: 5.0}" \
  > "$OUT/service_call.txt" || true

echo "[NavRL] synthetic detector preflight output: $OUT"
echo "[NavRL] YOLO topic:"
sed -n "1,80p" "$OUT/yolo_topic.txt"
echo "[NavRL] dynamic bboxes:"
sed -n "1,120p" "$OUT/dynamic_bboxes.txt"
echo "[NavRL] service:"
sed -n "1,120p" "$OUT/service_call.txt"
