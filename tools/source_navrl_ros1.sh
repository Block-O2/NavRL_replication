#!/usr/bin/env bash

# Source this file in every terminal before running the ROS1 NavRL simulator.
# It keeps the ROS Noetic Python packages and the NavRL policy dependencies in
# the same shell without requiring conda.

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "Please source this script instead of executing it:"
    echo "  source tools/source_navrl_ros1.sh"
    exit 1
fi

export NAVRL_REPO_DIR="${NAVRL_REPO_DIR:-/home/hank/research/NavRL_replication}"
export NAVRL_CATKIN_WS="${NAVRL_CATKIN_WS:-/home/hank/catkin_ws}"
export NAVRL_VENV="${NAVRL_VENV:-/home/hank/venvs/navrl-ros1}"

if [[ ! -f "${NAVRL_VENV}/bin/activate" ]]; then
    echo "NavRL venv not found: ${NAVRL_VENV}" >&2
    return 1
fi

if [[ ! -f /opt/ros/noetic/setup.bash ]]; then
    echo "ROS Noetic setup not found: /opt/ros/noetic/setup.bash" >&2
    return 1
fi

if [[ ! -f "${NAVRL_CATKIN_WS}/devel/setup.bash" ]]; then
    echo "Catkin setup not found: ${NAVRL_CATKIN_WS}/devel/setup.bash" >&2
    echo "Build it first: cd ${NAVRL_CATKIN_WS} && catkin_make" >&2
    return 1
fi

source "${NAVRL_VENV}/bin/activate"
source /opt/ros/noetic/setup.bash
source "${NAVRL_CATKIN_WS}/devel/setup.bash"

export ROS_PACKAGE_PATH="${NAVRL_CATKIN_WS}/src:${ROS_PACKAGE_PATH}"

echo "NavRL ROS1 environment ready"
echo "  repo:      ${NAVRL_REPO_DIR}"
echo "  catkin_ws: ${NAVRL_CATKIN_WS}"
echo "  venv:      ${NAVRL_VENV}"
