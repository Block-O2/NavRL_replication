import argparse
import os
import random

import numpy as np
import torch
from tensordict.tensordict import TensorDict
from torchrl.envs.utils import ExplorationType, set_exploration_type

from env import generate_obstacles_grid
from policy_rollout_compare import parse_policy
from policy_probe import init_policy
from utils import get_dyn_obs_state, get_ray_cast, get_robot_state


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
NUM_ROBOTS = 8
ROBOT_RADIUS = 0.25


def tensor_summary(name, value):
    finite = torch.isfinite(value).all().item()
    if finite:
        return (
            f"{name}: finite=True min={value.min().item():.6g} "
            f"max={value.max().item():.6g} mean={value.float().mean().item():.6g}"
        )
    mask = ~torch.isfinite(value)
    first = mask.nonzero(as_tuple=False)[0].tolist()
    return (
        f"{name}: finite=False shape={tuple(value.shape)} "
        f"bad_count={int(mask.sum().item())} first_bad_index={first}"
    )


def plan_with_debug(policy, robot_state, static_obs_input, dyn_obs_input, target_dir, device):
    obs = TensorDict(
        {
            "agents": TensorDict(
                {
                    "observation": TensorDict(
                        {
                            "state": robot_state,
                            "lidar": static_obs_input,
                            "direction": target_dir,
                            "dynamic_obstacle": dyn_obs_input,
                        },
                        batch_size=[],
                        device=device,
                    )
                },
                batch_size=[],
                device=device,
            )
        },
        batch_size=[],
        device=device,
    )
    with set_exploration_type(ExplorationType.MEAN):
        output = policy(obs)
    velocity = output["agents", "action"][0][0].detach().cpu().numpy()[:2]
    debug = {
        "state": robot_state.detach().cpu(),
        "lidar": static_obs_input.detach().cpu(),
        "direction": target_dir.detach().cpu(),
        "dynamic_obstacle": dyn_obs_input.detach().cpu(),
        "alpha": output["alpha"].detach().cpu(),
        "beta": output["beta"].detach().cpu(),
        "action_normalized": output["agents", "action_normalized"].detach().cpu(),
        "action": output["agents", "action"].detach().cpu(),
    }
    return velocity, debug


def min_static_clearance(pos, obstacles):
    if not obstacles:
        return float("inf")
    return min(float(np.linalg.norm(pos - np.array([ox, oy])) - radius) for ox, oy, radius in obstacles)


def pairwise_collision_indices(robot_positions, active):
    collided = set()
    for i in range(len(robot_positions)):
        if not active[i]:
            continue
        for j in range(i + 1, len(robot_positions)):
            if not active[j]:
                continue
            dist = np.linalg.norm(robot_positions[i] - robot_positions[j])
            if dist <= 2.0 * ROBOT_RADIUS:
                collided.add(i)
                collided.add(j)
    return collided


def rollout(policy, device, seed, frames, debug_nonfinite=False, label=None):
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
    robot_xs = np.linspace(OBSTACLE_REGION_MIN + 3.0, OBSTACLE_REGION_MAX - 3.0, NUM_ROBOTS)
    robot_positions = [np.array([x, -18.0], dtype=float) for x in robot_xs]
    robot_velocities = [np.zeros(2, dtype=float) for _ in range(NUM_ROBOTS)]
    goals = [np.array([x, 18.0], dtype=float) for x in robot_xs]
    target_dirs = [goals[i] - robot_positions[i] for i in range(NUM_ROBOTS)]

    status = ["active"] * NUM_ROBOTS
    failure_frame = [None] * NUM_ROBOTS
    steps = [0] * NUM_ROBOTS
    path_len = [0.0] * NUM_ROBOTS
    min_clearance = [float("inf")] * NUM_ROBOTS
    dyn_sanitized = [0] * NUM_ROBOTS

    for frame in range(frames):
        active = [item == "active" for item in status]
        for i, is_active in enumerate(active):
            if not is_active:
                continue
            if not np.all(np.isfinite(robot_positions[i])) or not np.all(np.isfinite(robot_velocities[i])):
                status[i] = "nonfinite"
                failure_frame[i] = frame
                continue
            steps[i] = frame
            min_clearance[i] = min(min_clearance[i], min_static_clearance(robot_positions[i], obstacles))
            if np.linalg.norm(goals[i] - robot_positions[i]) < GOAL_REACHED_THRESHOLD:
                status[i] = "reached"
            elif min_clearance[i] <= ROBOT_RADIUS:
                status[i] = "static_collision"
                failure_frame[i] = frame

        active = [item == "active" for item in status]
        for i in pairwise_collision_indices(robot_positions, active):
            status[i] = "robot_collision"
            failure_frame[i] = frame

        if all(item != "active" for item in status):
            break

        for i in range(NUM_ROBOTS):
            if status[i] != "active":
                continue
            pos = robot_positions[i]
            vel = robot_velocities[i]
            goal = goals[i]
            target_dir = target_dirs[i]

            robot_state = get_robot_state(pos, goal, vel, target_dir, device=device)
            static_obs_input, _, _ = get_ray_cast(
                pos,
                obstacles,
                max_range=MAX_RAY_LENGTH,
                hres_deg=HRES_DEG,
                vfov_angles_deg=VFOV_ANGLES_DEG,
                start_angle_deg=np.degrees(np.arctan2(target_dir[1], target_dir[0])),
                device=device,
            )
            target_tensor = torch.tensor(
                np.append(target_dir[:2], 0.0), dtype=torch.float, device=device
            ).unsqueeze(0).unsqueeze(0)
            dyn_obs_input = get_dyn_obs_state(
                pos,
                vel,
                robot_positions,
                robot_velocities,
                target_tensor,
                device=device,
            )
            if not torch.isfinite(dyn_obs_input).all():
                dyn_sanitized[i] += 1
                if debug_nonfinite:
                    print(f"debug_dyn_sanitized label={label} seed={seed} robot={i} frame={frame}")
                    print("  " + tensor_summary("dynamic_obstacle_raw", dyn_obs_input.detach().cpu()))
                dyn_obs_input = torch.nan_to_num(dyn_obs_input, nan=0.0, posinf=0.0, neginf=0.0)
            velocity, debug = plan_with_debug(
                policy, robot_state, static_obs_input, dyn_obs_input, target_tensor, device
            )
            if not np.all(np.isfinite(velocity)):
                if debug_nonfinite:
                    print(f"debug_nonfinite label={label} seed={seed} robot={i} frame={frame}")
                    print(f"  pos={pos} vel={vel} goal={goal} target_dir={target_dir}")
                    for key in (
                        "state",
                        "lidar",
                        "direction",
                        "dynamic_obstacle",
                        "alpha",
                        "beta",
                        "action_normalized",
                        "action",
                    ):
                        print("  " + tensor_summary(key, debug[key]))
                status[i] = "nonfinite"
                failure_frame[i] = frame
                continue
            step = velocity * DT
            robot_positions[i] = robot_positions[i] + step
            robot_velocities[i] = velocity.copy()
            path_len[i] += float(np.linalg.norm(step))

    for i, item in enumerate(status):
        if item == "active":
            steps[i] = frames
            if not np.all(np.isfinite(robot_positions[i])) or not np.all(np.isfinite(robot_velocities[i])):
                status[i] = "nonfinite"
                failure_frame[i] = frames
                continue
            min_clearance[i] = min(min_clearance[i], min_static_clearance(robot_positions[i], obstacles))
            if np.linalg.norm(goals[i] - robot_positions[i]) < GOAL_REACHED_THRESHOLD:
                status[i] = "reached"
            elif min_clearance[i] <= ROBOT_RADIUS:
                status[i] = "static_collision"
                failure_frame[i] = frames
            else:
                status[i] = "timeout"
                failure_frame[i] = frames

    return [
        {
            "status": status[i],
            "steps": steps[i],
            "final_dist": float(np.linalg.norm(goals[i] - robot_positions[i])),
            "min_clearance": min_clearance[i],
            "path_len": path_len[i],
            "seed": seed,
            "robot": i,
            "frame": failure_frame[i],
            "dyn_sanitized": dyn_sanitized[i],
        }
        for i in range(NUM_ROBOTS)
    ]


def summarize(label, results, show_failures=False):
    flat = [item for seed_result in results for item in seed_result]
    n = len(flat)
    reached = sum(item["status"] == "reached" for item in flat)
    static_collision = sum(item["status"] == "static_collision" for item in flat)
    robot_collision = sum(item["status"] == "robot_collision" for item in flat)
    nonfinite = sum(item["status"] == "nonfinite" for item in flat)
    timeout = sum(item["status"] == "timeout" for item in flat)
    finite = [item for item in flat if np.isfinite(item["final_dist"]) and np.isfinite(item["path_len"])]
    final_dist = np.mean([item["final_dist"] for item in finite]) if finite else float("nan")
    min_clear = np.min([item["min_clearance"] for item in finite]) if finite else float("nan")
    avg_steps = np.mean([item["steps"] for item in flat])
    avg_path = np.mean([item["path_len"] for item in finite]) if finite else float("nan")
    dyn_sanitized = sum(item["dyn_sanitized"] for item in flat)
    print(
        f"{label:18s} reach={reached:4d}/{n:<4d} "
        f"static_col={static_collision:4d}/{n:<4d} robot_col={robot_collision:4d}/{n:<4d} "
        f"nonfinite={nonfinite:4d}/{n:<4d} timeout={timeout:4d}/{n:<4d} avg_steps={avg_steps:6.1f} "
        f"avg_final_dist={final_dist:7.3f} min_clearance={min_clear:7.3f} avg_path={avg_path:7.3f} "
        f"dyn_sanitized={dyn_sanitized}"
    )
    if show_failures:
        failures = [item for item in flat if item["status"] in {"nonfinite", "robot_collision"}]
        for item in failures[:20]:
            print(
                f"  {label:18s} failure status={item['status']} "
                f"seed={item['seed']} robot={item['robot']} frame={item['frame']} "
                f"final_dist={item['final_dist']:.3f} path={item['path_len']:.3f}"
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
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--show-failures", action="store_true")
    parser.add_argument("--debug-nonfinite", action="store_true")
    args = parser.parse_args()

    policies = args.policy or [
        ("author", os.path.abspath(os.path.join("ckpts", "navrl_checkpoint.pt"))),
    ]
    device = torch.device(args.device)
    print(
        f"mode=multi-robot seeds={args.seeds} frames={args.frames} "
        f"robots={NUM_ROBOTS} device={device}"
    )
    for label, checkpoint in policies:
        policy = init_policy(device, checkpoint)
        results = [
            rollout(policy, device, seed, args.frames, args.debug_nonfinite, label)
            for seed in range(args.seeds)
        ]
        summarize(label, results, args.show_failures)


if __name__ == "__main__":
    main()
