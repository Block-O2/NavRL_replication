#!/usr/bin/env python3
"""Run controlled ROS2 NavRL policy comparisons with a dynamic-obstacle stub."""

import argparse
import csv
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
    ("front_static", 2.0, 0.0, 1.0, 0.0, 0.0, 0.0),
    ("front_oncoming", 2.0, 0.0, 1.0, -1.0, 0.0, 0.0),
    ("cross_yneg_to_path", 2.0, -1.0, 1.0, 0.0, 1.0, 0.0),
    ("cross_ypos_to_path", 2.0, 1.0, 1.0, 0.0, -1.0, 0.0),
    ("side_static_ypos", 2.0, 1.0, 1.0, 0.0, 0.0, 0.0),
]


class ActionProbe(Node):
    def __init__(self):
        super().__init__("navrl_action_probe")
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

    def publish_inputs(self):
        odom = Odometry()
        odom.header.frame_id = "map"
        odom.pose.pose.position.x = 0.0
        odom.pose.pose.position.y = 0.0
        odom.pose.pose.position.z = 1.0
        odom.pose.pose.orientation.w = 1.0

        goal = PoseStamped()
        goal.header.frame_id = "map"
        goal.pose.position.x = 5.0
        goal.pose.position.y = 0.0
        goal.pose.position.z = 1.0
        goal.pose.orientation.w = 1.0

        self.odom_pub.publish(odom)
        self.goal_pub.publish(goal)


def vector_to_tuple(msg):
    if msg is None:
        return ("", "", "")
    return (float(msg.x), float(msg.y), float(msg.z))


def cmd_to_tuple(msg):
    if msg is None:
        return ("", "", "", "", "", "")
    return (
        float(msg.linear.x),
        float(msg.linear.y),
        float(msg.linear.z),
        float(msg.angular.x),
        float(msg.angular.y),
        float(msg.angular.z),
    )


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


def run_case(policy_name, checkpoint, case, domain_id, startup_wait, message_wait):
    case_name, x, y, z, vx, vy, vz = case
    label = f"{case_name}_{policy_name}"
    env = make_env(domain_id)
    processes = []

    try:
        processes.append(
            start_process(
                ["ros2", "run", "map_manager", "occupancy_map_node"],
                LOG_DIR / f"scan_{label}_occupancy.log",
                env,
            )
        )
        processes.append(
            start_process(
                ["ros2", "run", "navigation_runner", "safe_action_node"],
                LOG_DIR / f"scan_{label}_safe_action.log",
                env,
            )
        )
        processes.append(
            start_process(
                [
                    str(CONDA_BIN / "python"),
                    str(REPO_ROOT / "ros2/tools/dynamic_obstacle_stub.py"),
                    "--x",
                    str(x),
                    "--y",
                    str(y),
                    "--z",
                    str(z),
                    "--vx",
                    str(vx),
                    "--vy",
                    str(vy),
                    "--vz",
                    str(vz),
                    "--sx",
                    "0.8",
                    "--sy",
                    "0.8",
                    "--sz",
                    "1.0",
                ],
                LOG_DIR / f"scan_{label}_dyn_stub.log",
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
        processes.append(
            start_process(nav_cmd, LOG_DIR / f"scan_{label}_navigation.log", env)
        )

        time.sleep(startup_wait)

        os.environ["ROS_DOMAIN_ID"] = str(domain_id)
        rclpy.init()
        probe = ActionProbe()
        started = time.monotonic()
        while time.monotonic() - started < message_wait:
            probe.publish_inputs()
            rclpy.spin_once(probe, timeout_sec=0.2)
            if probe.raw is not None and probe.safe is not None and probe.cmd is not None:
                break
        raw = vector_to_tuple(probe.raw)
        safe = vector_to_tuple(probe.safe)
        cmd = cmd_to_tuple(probe.cmd)
        probe.destroy_node()
        rclpy.shutdown()

        return {
            "case": case_name,
            "policy": policy_name,
            "checkpoint": checkpoint or "navrl_checkpoint.pt",
            "obs_x": x,
            "obs_y": y,
            "obs_z": z,
            "obs_vx": vx,
            "obs_vy": vy,
            "obs_vz": vz,
            "raw_x": raw[0],
            "raw_y": raw[1],
            "raw_z": raw[2],
            "safe_x": safe[0],
            "safe_y": safe[1],
            "safe_z": safe[2],
            "cmd_x": cmd[0],
            "cmd_y": cmd[1],
            "cmd_z": cmd[2],
            "cmd_yaw": cmd[5],
        }
    finally:
        if rclpy.ok():
            rclpy.shutdown()
        stop_processes(processes)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "ros2/tools/policy_stub_scan_latest.csv"),
        help="CSV output path.",
    )
    parser.add_argument("--domain-start", type=int, default=70)
    parser.add_argument("--startup-wait", type=float, default=8.0)
    parser.add_argument("--message-wait", type=float, default=10.0)
    return parser.parse_args()


def main():
    args = parse_args()
    rows = []
    domain_id = args.domain_start
    for case in CASES:
        for policy_name, checkpoint in POLICIES:
            print(f"[scan] case={case[0]} policy={policy_name} domain={domain_id}", flush=True)
            row = run_case(
                policy_name=policy_name,
                checkpoint=checkpoint,
                case=case,
                domain_id=domain_id,
                startup_wait=args.startup_wait,
                message_wait=args.message_wait,
            )
            rows.append(row)
            domain_id += 1

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"[scan] wrote {output}")
    for row in rows:
        print(
            f"{row['case']:20s} {row['policy']:12s} "
            f"raw=({row['raw_x']}, {row['raw_y']}, {row['raw_z']}) "
            f"cmd=({row['cmd_x']}, {row['cmd_y']}, {row['cmd_z']})"
        )


if __name__ == "__main__":
    main()
