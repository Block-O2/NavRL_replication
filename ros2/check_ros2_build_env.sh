#!/usr/bin/env bash
set -u

echo "[NavRL ROS2 preflight] workspace: $(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

status=0

check_cmd() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    echo "OK   command $name: $(command -v "$name")"
  else
    echo "MISS command $name"
    status=1
  fi
}

check_path() {
  local path="$1"
  if [ -e "$path" ]; then
    echo "OK   path $path"
  else
    echo "MISS path $path"
    status=1
  fi
}

check_path /opt/ros/humble/setup.bash
check_cmd colcon
check_cmd ros2

if [ -n "${ROS_DISTRO:-}" ]; then
  echo "OK   ROS_DISTRO=$ROS_DISTRO"
else
  echo "MISS ROS_DISTRO is not set"
  status=1
fi

echo "[NavRL ROS2 preflight] package files:"
for pkg in map_manager onboard_detector navigation_runner; do
  check_path "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$pkg/package.xml"
done

if [ "$status" -eq 0 ]; then
  echo "[NavRL ROS2 preflight] PASS: build environment appears ready."
else
  echo "[NavRL ROS2 preflight] FAIL: source ROS2 Humble and install colcon before building."
fi

exit "$status"
