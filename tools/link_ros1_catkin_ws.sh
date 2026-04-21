#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CATKIN_WS="${1:-/home/hank/catkin_ws}"
CATKIN_SRC="${CATKIN_WS}/src"

mkdir -p "${CATKIN_SRC}"

if [ ! -e "${CATKIN_SRC}/CMakeLists.txt" ]; then
  if [ -e /opt/ros/noetic/share/catkin/cmake/toplevel.cmake ]; then
    ln -s /opt/ros/noetic/share/catkin/cmake/toplevel.cmake "${CATKIN_SRC}/CMakeLists.txt"
  else
    echo "ERROR: /opt/ros/noetic/share/catkin/cmake/toplevel.cmake not found." >&2
    echo "Source or install ROS Noetic before setting up the workspace." >&2
    exit 1
  fi
fi

for pkg in map_manager navigation_runner onboard_detector uav_simulator; do
  ln -sfn "${REPO_ROOT}/ros1/${pkg}" "${CATKIN_SRC}/${pkg}"
  echo "${CATKIN_SRC}/${pkg} -> ${REPO_ROOT}/ros1/${pkg}"
done

echo
echo "Next:"
echo "  source /opt/ros/noetic/setup.bash"
echo "  cd ${CATKIN_WS}"
echo "  catkin_make"
echo "  source ${CATKIN_WS}/devel/setup.bash"
echo "  tools/check_ros1_workspace.sh ${CATKIN_WS}"
