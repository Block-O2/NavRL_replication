import argparse
import os
import random

import numpy as np
import torch
from tensordict.tensordict import TensorDict
from torchrl.data import CompositeSpec, UnboundedContinuousTensorSpec
from torchrl.envs.utils import ExplorationType, set_exploration_type

from ppo import PPO
from utils import get_ray_cast, get_robot_state, vec_to_new_frame


SEED = 0
MAP_MAX_RANGE = 4.0
HRES_DEG = 10.0
VFOV_ANGLES_DEG = [-10.0, 0.0, 10.0, 20.0]
GOAL_SPEED = 2.0


def init_policy(device, checkpoint):
    observation_spec = CompositeSpec(
        {
            "agents": CompositeSpec(
                {
                    "observation": CompositeSpec(
                        {
                            "state": UnboundedContinuousTensorSpec((8,), device=device),
                            "lidar": UnboundedContinuousTensorSpec((1, 36, 4), device=device),
                            "direction": UnboundedContinuousTensorSpec((1, 3), device=device),
                            "dynamic_obstacle": UnboundedContinuousTensorSpec((1, 5, 10), device=device),
                        }
                    ),
                }
            ).expand(1)
        },
        shape=[1],
        device=device,
    )
    action_spec = CompositeSpec(
        {
            "agents": CompositeSpec(
                {
                    "action": UnboundedContinuousTensorSpec((3,), device=device),
                }
            )
        }
    ).expand(1, 3).to(device)

    policy = PPO(observation_spec, action_spec, device)
    policy.load_state_dict(torch.load(checkpoint, map_location=device))
    policy.eval()
    return policy


def plan(policy, robot_state, static_obs_input, dyn_obs_input, target_dir, device):
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
    return output["agents", "action"][0][0].detach().cpu().numpy()[:2]


def make_dynamic_obstacle_state(robot_pos, target_dir, entries, device):
    dyn_state = torch.zeros((1, 1, 5, 10), dtype=torch.float, device=device)
    if not entries:
        return dyn_state

    target_dir_3d = torch.tensor(
        np.append(target_dir[:2], 0.0), dtype=torch.float, device=device
    ).unsqueeze(0)

    for i, entry in enumerate(entries[:5]):
        pos_xy, vel_xy, width, height = entry
        rel_pos = torch.tensor(
            [[pos_xy[0] - robot_pos[0], pos_xy[1] - robot_pos[1], 0.0]],
            dtype=torch.float,
            device=device,
        )
        rel_vel = torch.tensor(
            [[vel_xy[0], vel_xy[1], 0.0]], dtype=torch.float, device=device
        )
        rel_pos_g = vec_to_new_frame(rel_pos, target_dir_3d).squeeze(0)
        rel_vel_g = vec_to_new_frame(rel_vel, target_dir_3d).squeeze(0)
        dist = rel_pos.norm(dim=-1, keepdim=True).clamp_min(1e-6)
        dist_2d = rel_pos_g[..., :2].norm(dim=-1, keepdim=True)
        dist_z = torch.zeros((1, 1), dtype=torch.float, device=device)
        rel_pos_gn = rel_pos_g / dist

        # Match the deployment encoding: width is category-like, height is binary-ish.
        width_cat = torch.tensor([[width]], dtype=torch.float, device=device)
        height_cat = torch.tensor([[height]], dtype=torch.float, device=device)
        dyn_state[0, 0, i] = torch.cat(
            [rel_pos_gn, dist_2d, dist_z, rel_vel_g, width_cat, height_cat], dim=-1
        ).squeeze(0)
    return dyn_state


def has_obstacle(static_obs_input, dyn_obs_input):
    quarter_size = static_obs_input.shape[2] // 4
    first_clear = torch.all(static_obs_input[:, :, :quarter_size, 1:] < 0.2)
    last_clear = torch.all(static_obs_input[:, :, -quarter_size:, 1:] < 0.2)
    has_static = (not first_clear) or (not last_clear)
    has_dynamic = not torch.all(dyn_obs_input == 0.0)
    return bool(has_static or has_dynamic)


def run_case(policy, device, name, robot_pos, goal, robot_vel, obstacles, dyn_entries):
    target_dir = goal - robot_pos
    start_angle = np.degrees(np.arctan2(target_dir[1], target_dir[0]))
    robot_state = get_robot_state(robot_pos, goal, robot_vel, target_dir, device=device)
    static_obs_input, _, _ = get_ray_cast(
        robot_pos,
        obstacles,
        max_range=MAP_MAX_RANGE,
        hres_deg=HRES_DEG,
        vfov_angles_deg=VFOV_ANGLES_DEG,
        start_angle_deg=start_angle,
        device=device,
    )
    dyn_obs_input = make_dynamic_obstacle_state(
        robot_pos, target_dir, dyn_entries, device=device
    )
    target_dir_tensor = torch.tensor(
        np.append(target_dir[:2], 0.0), dtype=torch.float, device=device
    ).unsqueeze(0).unsqueeze(0)

    direct_velocity = target_dir / max(np.linalg.norm(target_dir), 1e-6) * GOAL_SPEED
    obstacle_in_range = has_obstacle(static_obs_input, dyn_obs_input)
    if obstacle_in_range:
        velocity = plan(policy, robot_state, static_obs_input, dyn_obs_input, target_dir_tensor, device)
        source = "RL"
    else:
        velocity = direct_velocity
        source = "DIRECT"

    goal_unit = direct_velocity / max(np.linalg.norm(direct_velocity), 1e-6)
    forward_speed = float(np.dot(velocity, goal_unit))
    lateral_speed = float(np.cross(goal_unit, velocity))
    min_lidar_distance = float(MAP_MAX_RANGE - static_obs_input.max().item())

    print(
        f"{name:22s} source={source:6s} "
        f"vel=({velocity[0]: .3f}, {velocity[1]: .3f}) "
        f"forward={forward_speed: .3f} lateral={lateral_speed: .3f} "
        f"min_lidar_dist={min_lidar_distance: .3f}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--checkpoint",
        default=os.path.join("ckpts", "navrl_checkpoint.pt"),
        help="Path to a NavRL policy checkpoint.",
    )
    parser.add_argument("--label", default=None, help="Label printed before results.")
    args = parser.parse_args()

    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint = os.path.abspath(os.path.expanduser(args.checkpoint))
    label = args.label or os.path.basename(checkpoint)
    print(f"label={label}")
    print(f"checkpoint={checkpoint}")
    print(f"device={device}")
    policy = init_policy(device, checkpoint)

    robot_pos = np.array([0.0, -18.0])
    goal = np.array([0.0, 18.0])
    robot_vel = np.array([0.0, 0.0])

    cases = [
        ("empty", [], []),
        ("front_static_close", [(0.0, -15.8, 0.7)], []),
        ("left_static_close", [(-1.1, -15.8, 0.7)], []),
        ("right_static_close", [(1.1, -15.8, 0.7)], []),
        ("front_dynamic_cross", [], [((0.0, -15.8), (1.0, 0.0), 2.0, 0.0)]),
        (
            "static_and_dynamic",
            [(0.0, -15.8, 0.7)],
            [((0.8, -16.2), (-1.0, 0.0), 2.0, 0.0)],
        ),
    ]

    for name, obstacles, dyn_entries in cases:
        run_case(policy, device, name, robot_pos, goal, robot_vel, obstacles, dyn_entries)


if __name__ == "__main__":
    main()
