#!/usr/bin/env python3
"""Run short closed-loop ROS2 NavRL rollouts with controlled dynamic obstacles."""

import argparse
import csv
import math
import os
import subprocess
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped, Twist, Vector3
from nav_msgs.msg import Odometry
from rclpy.node import Node


REPO_ROOT = Path(__file__).resolve().parents[2]
ROS2_WS = REPO_ROOT.parent / "navrl_ros2_ws"
LOG_DIR = ROS2_WS / "log"
CONDA_BIN = Path("/home/ubuntu/miniconda3/envs/NavRL/bin")

POLICIES = [
    ("author", ""),
    (
        "own1500",
        str(
            REPO_ROOT
            / "isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_1500.pt"
        ),
    ),
    (
        "dynstopfinal",
        str(
            REPO_ROOT
            / "isaac-training/runs/navrl_1024_ablate_dynstop_5m_20260418/ckpts/checkpoint_final.pt"
        ),
    ),
]

CASES = [
    ("front_oncoming", 2.0, 0.0, 1.0, -1.0, 0.0, 0.0),
    ("cross_yneg_to_path", 2.0, -1.0, 1.0, 0.0, 1.0, 0.0),
]


class RolloutProbe(Node):
    def __init__(self):
        super().__init__("navrl_rollout_probe")
        self.raw = None
        self.safe = None
        self.cmd = None
        self.odom_pub = self.create_publisher(Odometry, "/unitree_go2/odom", 10)
        self.goal_pub = self.create_publisher(PoseStamped, "/goal_pose", 10)
        self.create_subscription(Vector3, "/navigation_runner/debug/raw_cmd_vel_world", self._raw_cb, 10)
        self.create_subscription(Vector3, "/navigation_runner/debug/safe_cmd_vel_world", self._safe_cb, 10)
        self.create_subscription(Twist, "/unitree_go2/cmd_vel", self._cmd_cb, 10)

    def _raw_cb(self, msg):
        self.raw = msg

    def _safe_cb(self, msg):
        self.safe = msg

    def _cmd_cb(self, msg):
        self.cmd = msg

    def publish_inputs(self, x, y, z, yaw):
        odom = Odometry()
        odom.header.frame_id = "map"
        odom.pose.pose.position.x = x
        odom.pose.pose.position.y = y
        odom.pose.pose.position.z = z
        odom.pose.pose.orientation.w = math.cos(0.5 * yaw)
        odom.pose.pose.orientation.z = math.sin(0.5 * yaw)

        goal = PoseStamped()
        goal.header.frame_id = "map"
        goal.pose.position.x = 5.0
        goal.pose.position.y = 0.0
        goal.pose.position.z = 1.0
        goal.pose.orientation.w = 1.0

        self.odom_pub.publish(odom)
        self.goal_pub.publish(goal)


def msg_vec(msg):
    if msg is None:
        return ("", "", "")
    return (float(msg.x), float(msg.y), float(msg.z))


def make_env(domain_id):
    env = os.environ.copy()
    env["ROS_DOMAIN_ID"] = str(domain_id)
    env["ROS_LOG_DIR"] = str(LOG_DIR / "ros")
    env["PATH"] = f"{CONDA_BIN}:{env.get('PATH', '')}"
    return env


def start_process(cmd, log_path, env):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w")
    proc = subprocess.Popen(
        cmd,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=str(ROS2_WS),
        env=env,
        text=True,
    )
    return proc, log_file


def stop_processes(processes):
    for proc, _ in processes:
        if proc.poll() is None:
            proc.terminate()
    time.sleep(1.0)
    for proc, _ in processes:
        if proc.poll() is None:
            proc.kill()
    for _, log_file in processes:
        log_file.close()


def start_nodes(policy_name, checkpoint, case, domain_id):
    case_name, obs_x, obs_y, obs_z, obs_vx, obs_vy, obs_vz = case
    label = f"rollout_{case_name}_{policy_name}"
    env = make_env(domain_id)
    processes = []
    processes.append(
        start_process(["ros2", "run", "map_manager", "occupancy_map_node"], LOG_DIR / f"{label}_occupancy.log", env)
    )
    processes.append(
        start_process(["ros2", "run", "navigation_runner", "safe_action_node"], LOG_DIR / f"{label}_safe_action.log", env)
    )
    processes.append(
        start_process(
            [
                str(CONDA_BIN / "python"),
                str(REPO_ROOT / "ros2/tools/dynamic_obstacle_stub.py"),
                "--x",
                str(obs_x),
                "--y",
                str(obs_y),
                "--z",
                str(obs_z),
                "--vx",
                str(obs_vx),
                "--vy",
                str(obs_vy),
                "--vz",
                str(obs_vz),
                "--sx",
                "0.8",
                "--sy",
                "0.8",
                "--sz",
                "1.0",
                "--integrate-velocity",
            ],
            LOG_DIR / f"{label}_dyn_stub.log",
            env,
        )
    )

    nav_cmd = [
        "ros2",
        "run",
        "navigation_runner",
        "navigation_node.py",
        "--ros-args",
        "-p",
        "debug_action_topics:=true",
    ]
    if checkpoint:
        nav_cmd += ["-p", f"checkpoint_file:={checkpoint}"]
    processes.append(start_process(nav_cmd, LOG_DIR / f"{label}_navigation.log", env))
    return processes


def run_rollout(policy_name, checkpoint, case, domain_id, startup_wait, dt, steps):
    case_name, obs_x, obs_y, obs_z, obs_vx, obs_vy, obs_vz = case
    processes = start_nodes(policy_name, checkpoint, case, domain_id)
    rows = []
    try:
        time.sleep(startup_wait)
        os.environ["ROS_DOMAIN_ID"] = str(domain_id)
        rclpy.init()
        probe = RolloutProbe()
        x, y, z, yaw = 0.0, 0.0, 1.0, 0.0
        warmup_end = time.monotonic() + 5.0
        while time.monotonic() < warmup_end:
            probe.publish_inputs(x, y, z, yaw)
            rclpy.spin_once(probe, timeout_sec=0.1)
            if probe.raw is not None and probe.safe is not None and probe.cmd is not None:
                break

        for step in range(steps):
            t = step * dt
            probe.publish_inputs(x, y, z, yaw)
            end = time.monotonic() + dt
            while time.monotonic() < end:
                rclpy.spin_once(probe, timeout_sec=0.05)

            cmd = probe.cmd
            raw = msg_vec(probe.raw)
            safe = msg_vec(probe.safe)
            if cmd is not None:
                local_x = float(cmd.linear.x)
                local_y = float(cmd.linear.y)
                world_x = math.cos(yaw) * local_x - math.sin(yaw) * local_y
                world_y = math.sin(yaw) * local_x + math.cos(yaw) * local_y
                x += world_x * dt
                y += world_y * dt
                yaw += float(cmd.angular.z) * dt
            else:
                local_x = local_y = world_x = world_y = ""

            curr_obs_x = obs_x + obs_vx * t
            curr_obs_y = obs_y + obs_vy * t
            obs_dist = math.hypot(x - curr_obs_x, y - curr_obs_y)
            goal_dist = math.hypot(5.0 - x, y)
            rows.append(
                {
                    "case": case_name,
                    "policy": policy_name,
                    "step": step,
                    "time": t,
                    "agent_x": x,
                    "agent_y": y,
                    "agent_yaw": yaw,
                    "obs_x": curr_obs_x,
                    "obs_y": curr_obs_y,
                    "obs_dist_2d": obs_dist,
                    "goal_dist_2d": goal_dist,
                    "raw_x": raw[0],
                    "raw_y": raw[1],
                    "raw_z": raw[2],
                    "safe_x": safe[0],
                    "safe_y": safe[1],
                    "safe_z": safe[2],
                    "cmd_x": local_x,
                    "cmd_y": local_y,
                    "world_cmd_x": world_x,
                    "world_cmd_y": world_y,
                }
            )

        probe.destroy_node()
        rclpy.shutdown()
        return rows
    finally:
        if rclpy.ok():
            rclpy.shutdown()
        stop_processes(processes)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "ros2/tools/policy_stub_rollout_latest.csv"),
    )
    parser.add_argument("--domain-start", type=int, default=100)
    parser.add_argument("--startup-wait", type=float, default=8.0)
    parser.add_argument("--dt", type=float, default=0.1)
    parser.add_argument("--steps", type=int, default=60)
    return parser.parse_args()


def main():
    args = parse_args()
    all_rows = []
    domain_id = args.domain_start
    for case in CASES:
        for policy_name, checkpoint in POLICIES:
            print(f"[rollout] case={case[0]} policy={policy_name} domain={domain_id}", flush=True)
            rows = run_rollout(policy_name, checkpoint, case, domain_id, args.startup_wait, args.dt, args.steps)
            all_rows.extend(rows)
            final = rows[-1]
            min_obs = min(float(row["obs_dist_2d"]) for row in rows)
            print(
                f"[rollout] final case={case[0]} policy={policy_name} "
                f"agent=({final['agent_x']:.3f},{final['agent_y']:.3f}) "
                f"goal_dist={final['goal_dist_2d']:.3f} min_obs={min_obs:.3f}",
                flush=True,
            )
            domain_id += 1

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"[rollout] wrote {output}")


if __name__ == "__main__":
    main()
