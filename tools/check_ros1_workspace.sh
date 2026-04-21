#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CATKIN_WS="${1:-/home/hank/catkin_ws}"

if [ ! -f /opt/ros/noetic/setup.bash ]; then
  echo "ERROR: /opt/ros/noetic/setup.bash not found." >&2
  exit 1
fi

source /opt/ros/noetic/setup.bash

if [ -f "${CATKIN_WS}/devel/setup.bash" ]; then
  source "${CATKIN_WS}/devel/setup.bash"
else
  echo "WARN: ${CATKIN_WS}/devel/setup.bash not found. Run catkin_make first if rospack cannot find packages." >&2
fi

status=0
for pkg in map_manager navigation_runner onboard_detector uav_simulator; do
  expected="${REPO_ROOT}/ros1/${pkg}"
  link_path="${CATKIN_WS}/src/${pkg}"
  actual_link="$(readlink -f "${link_path}" 2>/dev/null || true)"
  rospack_path="$(rospack find "${pkg}" 2>/dev/null || true)"

  echo "${pkg}:"
  echo "  symlink: ${actual_link:-MISSING}"
  echo "  rospack: ${rospack_path:-MISSING}"

  if [ "${actual_link}" != "${expected}" ]; then
    echo "  ERROR: expected symlink target ${expected}" >&2
    status=1
  fi

  if [ -z "${rospack_path}" ]; then
    echo "  ERROR: rospack cannot find ${pkg}" >&2
    status=1
  fi
done

echo
if rospack find fcu_core >/dev/null 2>&1; then
  echo "fcu_core: $(rospack find fcu_core)"
else
  echo "WARN: fcu_core not found in the sourced ROS workspace."
  echo "      roslaunch fcu_core fcu_core.launch will fail until FCU core is installed and sourced."
fi

exit "${status}"
