import argparse
import os
import random

import numpy as np
import torch

from env import generate_obstacles_grid, sample_free_goal, sample_free_start
from policy_probe import GOAL_SPEED, has_obstacle, init_policy, plan
from utils import get_ray_cast, get_robot_state


MAP_HALF_SIZE = 16.0
OBSTACLE_REGION_MIN = -15.0
OBSTACLE_REGION_MAX = 15.0
MIN_RADIUS = 0.3
MAX_RADIUS = 0.5
MAX_RAY_LENGTH = 4.0
DT = 0.1
GOAL_REACHED_THRESHOLD = 0.3
HRES_DEG = 10.0
VFOV_ANGLES_DEG = [-10.0, 0.0, 10.0, 20.0]
GRID_DIV = 10
ROBOT_RADIUS = 0.25


def parse_policy(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError("policy must be label=/path/to/checkpoint.pt")
    label, checkpoint = value.split("=", 1)
    checkpoint = os.path.abspath(os.path.expanduser(checkpoint))
    if not label or not checkpoint:
        raise argparse.ArgumentTypeError("policy must be label=/path/to/checkpoint.pt")
    return label, checkpoint


def min_clearance(pos, obstacles):
    if not obstacles:
        return float("inf")
    return min(float(np.linalg.norm(pos - np.array([ox, oy])) - radius) for ox, oy, radius in obstacles)


def rollout(policy, device, seed, mode, frames):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    obstacles = generate_obstacles_grid(
        GRID_DIV,
        OBSTACLE_REGION_MIN,
        OBSTACLE_REGION_MAX,
        MIN_RADIUS,
        MAX_RADIUS,
    )
    goal = sample_free_goal(obstacles, OBSTACLE_REGION_MIN, OBSTACLE_REGION_MAX)
    robot_pos = sample_free_start(obstacles, goal, OBSTACLE_REGION_MIN, OBSTACLE_REGION_MAX)
    robot_vel = np.array([0.0, 0.0])
    target_dir = goal - robot_pos
    min_seen_clearance = float("inf")
    path_len = 0.0

    for frame in range(frames):
        dist_to_goal = float(np.linalg.norm(goal - robot_pos))
        min_seen_clearance = min(min_seen_clearance, min_clearance(robot_pos, obstacles))
        if dist_to_goal < GOAL_REACHED_THRESHOLD:
            return {
                "reached": True,
                "collided": False,
                "steps": frame,
                "final_dist": dist_to_goal,
                "min_clearance": min_seen_clearance,
                "path_len": path_len,
            }
        if min_seen_clearance <= ROBOT_RADIUS:
            return {
                "reached": False,
                "collided": True,
                "steps": frame,
                "final_dist": dist_to_goal,
                "min_clearance": min_seen_clearance,
                "path_len": path_len,
            }

        robot_state = get_robot_state(robot_pos, goal, robot_vel, target_dir, device=device)
        static_obs_input, _, _ = get_ray_cast(
            robot_pos,
            obstacles,
            max_range=MAX_RAY_LENGTH,
            hres_deg=HRES_DEG,
            vfov_angles_deg=VFOV_ANGLES_DEG,
            start_angle_deg=np.degrees(np.arctan2(target_dir[1], target_dir[0])),
            device=device,
        )
        dyn_obs_input = torch.zeros((1, 1, 5, 10), dtype=torch.float, device=device)
        target_dir_tensor = torch.tensor(
            np.append(target_dir[:2], 0.0), dtype=torch.float, device=device
        ).unsqueeze(0).unsqueeze(0)

        if mode == "ros-gated" and not has_obstacle(static_obs_input, dyn_obs_input):
            velocity = target_dir / max(np.linalg.norm(target_dir), 1e-6) * GOAL_SPEED
        else:
            velocity = plan(policy, robot_state, static_obs_input, dyn_obs_input, target_dir_tensor, device)

        step = velocity * DT
        robot_pos = robot_pos + step
        robot_vel = velocity.copy()
        path_len += float(np.linalg.norm(step))

    return {
        "reached": False,
        "collided": min_clearance(robot_pos, obstacles) <= ROBOT_RADIUS,
        "steps": frames,
        "final_dist": float(np.linalg.norm(goal - robot_pos)),
        "min_clearance": min(min_seen_clearance, min_clearance(robot_pos, obstacles)),
        "path_len": path_len,
    }


def summarize(label, results):
    n = len(results)
    reached = sum(item["reached"] for item in results)
    collided = sum(item["collided"] for item in results)
    timeouts = n - reached - collided
    final_dist = np.mean([item["final_dist"] for item in results])
    min_clear = np.min([item["min_clearance"] for item in results])
    avg_steps = np.mean([item["steps"] for item in results])
    avg_path = np.mean([item["path_len"] for item in results])
    print(
        f"{label:18s} reach={reached:3d}/{n:<3d} "
        f"collision={collided:3d}/{n:<3d} timeout={timeouts:3d}/{n:<3d} "
        f"avg_steps={avg_steps:6.1f} avg_final_dist={final_dist:7.3f} "
        f"min_clearance={min_clear:7.3f} avg_path={avg_path:7.3f}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--policy",
        action="append",
        type=parse_policy,
        help="Repeatable label=/path/to/checkpoint.pt.",
    )
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--mode", choices=["quickdemo", "ros-gated"], default="quickdemo")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    policies = args.policy or [
        ("author", os.path.abspath(os.path.join("ckpts", "navrl_checkpoint.pt"))),
    ]
    device = torch.device(args.device)
    print(f"mode={args.mode} seeds={args.seeds} frames={args.frames} device={device}")

    for label, checkpoint in policies:
        policy = init_policy(device, checkpoint)
        results = [rollout(policy, device, seed, args.mode, args.frames) for seed in range(args.seeds)]
        summarize(label, results)


if __name__ == "__main__":
    main()
