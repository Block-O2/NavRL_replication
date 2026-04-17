import argparse
import csv
import os
import random

import numpy as np
import torch

from policy_ros2_style_compare import (
    DT,
    ROBOT_RADIUS,
    approximate_safe_action,
    get_action,
    init_policy,
    make_dynamic_obstacles,
    min_dynamic_clearance,
    min_static_clearance,
    update_dynamic_obstacles,
)


DEFAULT_POLICIES = [
    ("author", "quick-demos/ckpts/navrl_checkpoint.pt"),
    (
        "own1500",
        "isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_1500.pt",
    ),
    (
        "ownfinal",
        "isaac-training/runs/navrl_1024_50m_20260417_policy_retry1/ckpts/checkpoint_final.pt",
    ),
]


def parse_policy(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError("policy must be label=/path/to/checkpoint.pt")
    label, checkpoint = value.split("=", 1)
    return label, checkpoint


def resolve_path(root_dir, path):
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.join(root_dir, path)


def nearest_dynamic(pos, dynamic_obstacles):
    if not dynamic_obstacles:
        return float("inf"), -1
    distances = [np.linalg.norm(pos[:2] - obs["pos"][:2]) - ROBOT_RADIUS for obs in dynamic_obstacles]
    idx = int(np.argmin(distances))
    return float(distances[idx]), idx


def run_trace(label, policy, device, seed, frames, use_safe_action):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    obstacles = []
    pos = np.array([0.0, -12.0, 0.0], dtype=float)
    goal = np.array([0.0, 12.0, 0.0], dtype=float)
    vel = np.zeros(3, dtype=float)
    target_dir = goal - pos
    dynamic_obstacles = make_dynamic_obstacles(seed, 5, pos, goal, "path-crossing")
    rows = []
    status = "timeout"
    path_len = 0.0

    for frame in range(frames):
        distance = float(np.linalg.norm(goal - pos))
        dyn_clearance, dyn_idx = nearest_dynamic(pos, dynamic_obstacles)
        static_clearance = min_static_clearance(pos, obstacles)

        if distance <= 1.0:
            status = "reached"
            break
        if static_clearance <= ROBOT_RADIUS:
            status = "static_collision"
            break
        if dyn_clearance <= ROBOT_RADIUS:
            status = "dynamic_collision"
            break

        action, source = get_action(policy, pos, vel, goal, target_dir, obstacles, dynamic_obstacles, device)
        raw_action = action.copy()
        safe_delta = 0.0
        safe_adjusted = False
        if use_safe_action:
            safe_action, safe_adjusted = approximate_safe_action(pos, action, obstacles, dynamic_obstacles)
            safe_delta = float(np.linalg.norm(safe_action - action))
            action = safe_action

        if distance <= 3.0 and distance > 1.0:
            norm = np.linalg.norm(action)
            if norm > 0:
                action = action / norm
        elif distance <= 1.0:
            action *= 0.0

        nearest_obs = dynamic_obstacles[dyn_idx] if dyn_idx >= 0 else None
        rows.append(
            {
                "policy": label,
                "frame": frame,
                "status": "active",
                "pos_x": pos[0],
                "pos_y": pos[1],
                "vel_x": vel[0],
                "vel_y": vel[1],
                "dist_goal": distance,
                "nearest_dyn_clearance": dyn_clearance,
                "nearest_dyn_idx": dyn_idx,
                "nearest_dyn_x": nearest_obs["pos"][0] if nearest_obs is not None else np.nan,
                "nearest_dyn_y": nearest_obs["pos"][1] if nearest_obs is not None else np.nan,
                "nearest_dyn_vx": nearest_obs["vel"][0] if nearest_obs is not None else np.nan,
                "nearest_dyn_vy": nearest_obs["vel"][1] if nearest_obs is not None else np.nan,
                "source": source,
                "raw_action_x": raw_action[0],
                "raw_action_y": raw_action[1],
                "action_x": action[0],
                "action_y": action[1],
                "speed": float(np.linalg.norm(action[:2])),
                "safe_adjusted": int(safe_adjusted),
                "safe_delta": safe_delta,
            }
        )

        step = action * DT
        pos = pos + step
        vel = action.copy()
        path_len += float(np.linalg.norm(step))
        update_dynamic_obstacles(dynamic_obstacles)

    final_clearance = min_dynamic_clearance(pos, dynamic_obstacles)
    final_row = {
        "policy": label,
        "frame": len(rows),
        "status": status,
        "pos_x": pos[0],
        "pos_y": pos[1],
        "vel_x": vel[0],
        "vel_y": vel[1],
        "dist_goal": float(np.linalg.norm(goal - pos)),
        "nearest_dyn_clearance": final_clearance,
        "nearest_dyn_idx": -1,
        "nearest_dyn_x": np.nan,
        "nearest_dyn_y": np.nan,
        "nearest_dyn_vx": np.nan,
        "nearest_dyn_vy": np.nan,
        "source": "final",
        "raw_action_x": np.nan,
        "raw_action_y": np.nan,
        "action_x": np.nan,
        "action_y": np.nan,
        "speed": np.nan,
        "safe_adjusted": 0,
        "safe_delta": 0.0,
        "path_len": path_len,
    }
    for row in rows:
        row["path_len"] = path_len
    rows.append(final_row)
    return rows, status, path_len, float(np.linalg.norm(goal - pos)), final_clearance


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", action="append", type=parse_policy)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--safe-action", action="store_true")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    policies = args.policy or DEFAULT_POLICIES
    device = torch.device(args.device)

    output = args.output
    if output is None:
        output_dir = os.path.join(root_dir, "quick-demos", "eval_outputs")
        os.makedirs(output_dir, exist_ok=True)
        suffix = "safe" if args.safe_action else "nosafe"
        output = os.path.join(output_dir, f"path_crossing_trace_seed{args.seed}_{suffix}.csv")

    all_rows = []
    print(
        f"mode=path-crossing-trace seed={args.seed} frames={args.frames} "
        f"safe_action={args.safe_action} output={output}"
    )
    for label, checkpoint in policies:
        checkpoint = resolve_path(root_dir, checkpoint)
        policy = init_policy(device, checkpoint)
        rows, status, path_len, final_dist, final_clearance = run_trace(
            label, policy, device, args.seed, args.frames, args.safe_action
        )
        all_rows.extend(rows)
        print(
            f"{label:10s} status={status:17s} path_len={path_len:7.3f} "
            f"final_dist={final_dist:7.3f} final_dyn_clearance={final_clearance:7.3f}"
        )

    fieldnames = [
        "policy",
        "frame",
        "status",
        "pos_x",
        "pos_y",
        "vel_x",
        "vel_y",
        "dist_goal",
        "nearest_dyn_clearance",
        "nearest_dyn_idx",
        "nearest_dyn_x",
        "nearest_dyn_y",
        "nearest_dyn_vx",
        "nearest_dyn_vy",
        "source",
        "raw_action_x",
        "raw_action_y",
        "action_x",
        "action_y",
        "speed",
        "safe_adjusted",
        "safe_delta",
        "path_len",
    ]
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)


if __name__ == "__main__":
    main()
