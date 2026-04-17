import argparse
import os
import random
import sys
from types import SimpleNamespace

import numpy as np
import torch
from tensordict.tensordict import TensorDict
from torchrl.data import CompositeSpec, UnboundedContinuousTensorSpec
from torchrl.envs.utils import ExplorationType, set_exploration_type


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROS2_SCRIPT_DIR = os.path.join(REPO_ROOT, "ros2", "navigation_runner", "scripts")
sys.path.insert(0, ROS2_SCRIPT_DIR)

from ppo import PPO  # noqa: E402
from utils import vec_to_new_frame, vec_to_world  # noqa: E402


OBSTACLE_REGION_MIN = -15.0
OBSTACLE_REGION_MAX = 15.0
MIN_RADIUS = 0.3
MAX_RADIUS = 0.5
MAX_RAY_LENGTH = 4.0
DT = 0.1
FRAMES = 300
GRID_DIV = 10
LIDAR_HRES = 10.0
LIDAR_HBEAMS = int(360 / LIDAR_HRES)
LIDAR_VBEAMS = 4
LIDAR_VFOV = [-10.0, 20.0]
VEL_LIMIT = 1.0
ROBOT_RADIUS = 0.3
DYN_OBS_NUM = 5
SAFE_TIME_HORIZON = 2.0
SAFE_TIME_STEP = 0.05
SAFE_DISTANCE = 0.3
SAFE_MAX_VELOCITY = float(np.sqrt(2.0 * VEL_LIMIT**2))
EPSILON = 1e-5


def make_cfg(device):
    return SimpleNamespace(
        device=device,
        sensor=SimpleNamespace(
            lidar_range=MAX_RAY_LENGTH,
            lidar_vfov=LIDAR_VFOV,
            lidar_vbeams=LIDAR_VBEAMS,
            lidar_hres=LIDAR_HRES,
        ),
        algo=SimpleNamespace(
            feature_extractor=SimpleNamespace(learning_rate=5e-4, dyn_obs_num=DYN_OBS_NUM),
            actor=SimpleNamespace(learning_rate=5e-4, clip_ratio=0.1, action_limit=1.0),
            critic=SimpleNamespace(learning_rate=5e-4, clip_ratio=0.1),
            entropy_loss_coefficient=1e-3,
            training_frame_num=32,
            training_epoch_num=4,
            num_minibatches=16,
        ),
    )


def parse_policy(value):
    if "=" not in value:
        raise argparse.ArgumentTypeError("policy must be label=/path/to/checkpoint.pt")
    label, checkpoint = value.split("=", 1)
    checkpoint = os.path.abspath(os.path.expanduser(checkpoint))
    if not label or not checkpoint:
        raise argparse.ArgumentTypeError("policy must be label=/path/to/checkpoint.pt")
    return label, checkpoint


def init_policy(device, checkpoint):
    cfg = make_cfg(device)
    observation_spec = CompositeSpec(
        {
            "agents": CompositeSpec(
                {
                    "observation": CompositeSpec(
                        {
                            "state": UnboundedContinuousTensorSpec((8,), device=device),
                            "lidar": UnboundedContinuousTensorSpec((1, LIDAR_HBEAMS, LIDAR_VBEAMS), device=device),
                            "direction": UnboundedContinuousTensorSpec((1, 3), device=device),
                            "dynamic_obstacle": UnboundedContinuousTensorSpec((1, DYN_OBS_NUM, 10), device=device),
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
    policy = PPO(cfg.algo, observation_spec, action_spec, device)
    policy.load_state_dict(torch.load(checkpoint, map_location=device))
    policy.eval()
    return policy


def generate_obstacles_grid(grid_div, region_min, region_max, min_radius, max_radius, min_clearance=1.0):
    if grid_div <= 0:
        return []
    cell_size = (region_max - region_min) / grid_div
    obstacles = []
    for i in range(grid_div):
        for j in range(grid_div):
            for _ in range(10):
                radius = random.uniform(min_radius, max_radius)
                margin = radius + 0.2
                x = np.random.uniform(region_min + i * cell_size + margin, region_min + (i + 1) * cell_size - margin)
                y = np.random.uniform(region_min + j * cell_size + margin, region_min + (j + 1) * cell_size - margin)
                if all(np.hypot(x - ox, y - oy) >= radius + old_radius + min_clearance for ox, oy, old_radius in obstacles):
                    obstacles.append((x, y, radius))
                    break
    return obstacles


def sample_free_point(obstacles, min_clearance=1.2):
    while True:
        point = np.random.uniform(OBSTACLE_REGION_MIN, OBSTACLE_REGION_MAX, size=2)
        if all(np.linalg.norm(point - np.array([ox, oy])) > radius + min_clearance for ox, oy, radius in obstacles):
            return point


def ray_cast_distance(robot_pos, angle, obstacles, max_range=MAX_RAY_LENGTH):
    direction = np.array([np.cos(angle), np.sin(angle)])
    min_dist = max_range
    for ox, oy, radius in obstacles:
        center = np.array([ox, oy]) - robot_pos[:2]
        proj = float(np.dot(center, direction))
        if proj < 0.0 or proj > max_range:
            continue
        closest = proj * direction
        dist_to_center = np.linalg.norm(center - closest)
        if dist_to_center <= radius:
            min_dist = min(min_dist, max(proj - radius, 0.0))
    return min_dist


def make_raypoints(pos, obstacles, start_angle):
    points = []
    for h in range(LIDAR_HBEAMS):
        angle = start_angle + np.deg2rad(h * LIDAR_HRES)
        hit_dist = ray_cast_distance(pos, angle, obstacles)
        for v in range(LIDAR_VBEAMS):
            dist = MAX_RAY_LENGTH if v == 0 else hit_dist
            points.append(
                [
                    pos[0] + dist * np.cos(angle),
                    pos[1] + dist * np.sin(angle),
                    pos[2],
                ]
            )
    return torch.tensor(points, dtype=torch.float)


def make_dynamic_obstacles(seed, dynamic_count, start, goal, dynamic_layout):
    if dynamic_count <= 0:
        return []
    rng = np.random.default_rng(seed + 1000)
    entries = []
    start_xy = start[:2]
    goal_xy = goal[:2]
    path = goal_xy - start_xy
    path_unit = path / max(np.linalg.norm(path), 1e-6)
    path_perp = np.array([-path_unit[1], path_unit[0]])

    if dynamic_layout == "side-crossing":
        offsets = np.linspace(-1.5, 1.5, dynamic_count)
        for offset in offsets:
            y = rng.uniform(-8.0, 8.0)
            direction = -1.0 if offset > 0 else 1.0
            entries.append(
                {
                    "pos": np.array([offset * 2.0, y, 0.0], dtype=float),
                    "vel": np.array([direction * rng.uniform(0.4, 0.9), 0.0, 0.0], dtype=float),
                    "size": np.array([0.6, 0.6, 0.6], dtype=float),
                }
            )
    elif dynamic_layout == "path-crossing":
        fractions = np.linspace(0.25, 0.75, dynamic_count)
        for i, frac in enumerate(fractions):
            side = -1.0 if i % 2 == 0 else 1.0
            center = start_xy + frac * path
            lateral = side * rng.uniform(2.2, 3.2)
            speed = rng.uniform(0.45, 0.9)
            entries.append(
                {
                    "pos": np.array([*(center + lateral * path_perp), 0.0], dtype=float),
                    "vel": np.array([*(-side * speed * path_perp), 0.0], dtype=float),
                    "size": np.array([0.8, 0.8, 0.8], dtype=float),
                }
            )
    elif dynamic_layout == "head-on":
        distances = np.linspace(4.0, 12.0, dynamic_count)
        for dist in distances:
            offset = rng.uniform(-0.6, 0.6)
            speed = rng.uniform(0.35, 0.75)
            center = start_xy + dist * path_unit + offset * path_perp
            entries.append(
                {
                    "pos": np.array([*center, 0.0], dtype=float),
                    "vel": np.array([*(-speed * path_unit), 0.0], dtype=float),
                    "size": np.array([0.7, 0.7, 0.7], dtype=float),
                }
            )
    else:
        raise ValueError(f"Unknown dynamic layout: {dynamic_layout}")
    return entries


def update_dynamic_obstacles(dynamic_obstacles):
    for obs in dynamic_obstacles:
        obs["pos"] = obs["pos"] + obs["vel"] * DT
        if obs["pos"][0] > 5.0 or obs["pos"][0] < -5.0:
            obs["vel"][0] *= -1.0


def closest_dynamic_state(pos, dynamic_obstacles, device):
    valid = []
    for obs in dynamic_obstacles:
        dist = np.linalg.norm(obs["pos"][:2] - pos[:2])
        if dist <= MAX_RAY_LENGTH:
            valid.append((dist, obs))
    valid.sort(key=lambda item: item[0])
    dyn_pos = torch.zeros(DYN_OBS_NUM, 3, dtype=torch.float, device=device)
    dyn_vel = torch.zeros(DYN_OBS_NUM, 3, dtype=torch.float, device=device)
    dyn_size = torch.zeros(DYN_OBS_NUM, 3, dtype=torch.float, device=device)
    for i, (_, obs) in enumerate(valid[:DYN_OBS_NUM]):
        dyn_pos[i] = torch.tensor(obs["pos"], dtype=torch.float, device=device)
        dyn_vel[i] = torch.tensor(obs["vel"], dtype=torch.float, device=device)
        dyn_size[i] = torch.tensor(obs["size"], dtype=torch.float, device=device)
    return dyn_pos, dyn_vel, dyn_size


def check_obstacle(lidar_scan, dyn_obs_states):
    quarter_size = lidar_scan.shape[2] // 4
    first_clear = torch.all(lidar_scan[:, :, :quarter_size, 1:] < 0.2)
    last_clear = torch.all(lidar_scan[:, :, -quarter_size:, 1:] < 0.2)
    has_static = (not first_clear) or (not last_clear)
    has_dynamic = not torch.all(dyn_obs_states == 0.0)
    return bool(has_static or has_dynamic)


def build_ros2_observation(pos, vel, goal, target_dir, obstacles, dynamic_obstacles, device):
    pos_t = torch.tensor(pos, dtype=torch.float, device=device)
    vel_t = torch.tensor(vel, dtype=torch.float, device=device)
    goal_t = torch.tensor(goal, dtype=torch.float, device=device)
    target_dir_t = torch.tensor(target_dir, dtype=torch.float, device=device)
    target_dir_t[2] = 0.0

    rpos = goal_t - pos_t
    distance = rpos.norm(dim=-1, keepdim=True)
    distance_2d = rpos[..., :2].norm(dim=-1, keepdim=True)
    distance_z = rpos[..., 2].unsqueeze(-1)
    rpos_clipped = rpos / distance.clamp(1e-6)
    rpos_clipped_g = vec_to_new_frame(rpos_clipped, target_dir_t).squeeze(0).squeeze(0)
    vel_g = vec_to_new_frame(vel_t, target_dir_t).squeeze(0).squeeze(0)
    drone_state = torch.cat([rpos_clipped_g, distance_2d, distance_z, vel_g], dim=-1).unsqueeze(0)

    raypoints = make_raypoints(pos, obstacles, np.arctan2(target_dir[1], target_dir[0])).to(device)
    lidar_scan = (raypoints - pos_t).norm(dim=-1).clamp_max(MAX_RAY_LENGTH).reshape(1, 1, LIDAR_HBEAMS, LIDAR_VBEAMS)
    lidar_scan = MAX_RAY_LENGTH - lidar_scan

    dyn_pos, dyn_vel, dyn_size = closest_dynamic_state(pos, dynamic_obstacles, device)
    closest_dyn_obs_rpos = dyn_pos - pos_t
    closest_dyn_obs_rpos[dyn_size[:, 2] == 0] = 0.0
    closest_dyn_obs_rpos[:, 2][dyn_size[:, 2] > 1] = 0.0
    closest_dyn_obs_rpos_g = vec_to_new_frame(closest_dyn_obs_rpos.unsqueeze(0), target_dir_t).squeeze(0)
    closest_dyn_obs_distance = closest_dyn_obs_rpos.norm(dim=-1, keepdim=True)
    closest_dyn_obs_distance_2d = closest_dyn_obs_rpos_g[..., :2].norm(dim=-1, keepdim=True)
    closest_dyn_obs_distance_z = closest_dyn_obs_rpos_g[..., 2].unsqueeze(-1)
    closest_dyn_obs_rpos_gn = closest_dyn_obs_rpos_g / closest_dyn_obs_distance.clamp(1e-6)
    closest_dyn_obs_vel_g = vec_to_new_frame(dyn_vel.unsqueeze(0), target_dir_t).squeeze(0)

    obs_res = 0.25
    closest_dyn_obs_width = torch.max(dyn_size[:, 0], dyn_size[:, 1])
    closest_dyn_obs_width += ROBOT_RADIUS * 2.0
    closest_dyn_obs_width = torch.clamp(torch.ceil(closest_dyn_obs_width / obs_res) - 1, min=0, max=1.0 / obs_res - 1)
    closest_dyn_obs_width[dyn_size[:, 2] == 0] = 0.0
    closest_dyn_obs_height = dyn_size[:, 2]
    closest_dyn_obs_height[(closest_dyn_obs_height <= 1) & (closest_dyn_obs_height != 0)] = 1.0
    closest_dyn_obs_height[closest_dyn_obs_height > 1] = 0.0
    dyn_obs_states = torch.cat(
        [
            closest_dyn_obs_rpos_gn,
            closest_dyn_obs_distance_2d,
            closest_dyn_obs_distance_z,
            closest_dyn_obs_vel_g,
            closest_dyn_obs_width.unsqueeze(1),
            closest_dyn_obs_height.unsqueeze(1),
        ],
        dim=-1,
    ).unsqueeze(0).unsqueeze(0)
    dyn_obs_states = torch.nan_to_num(dyn_obs_states, nan=0.0, posinf=0.0, neginf=0.0)

    obs = TensorDict(
        {
            "agents": TensorDict(
                {
                    "observation": TensorDict(
                        {
                            "state": drone_state,
                            "lidar": lidar_scan,
                            "direction": target_dir_t,
                            "dynamic_obstacle": dyn_obs_states,
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
    return obs, lidar_scan, dyn_obs_states


def get_action(policy, pos, vel, goal, target_dir, obstacles, dynamic_obstacles, device):
    obs, lidar_scan, dyn_obs_states = build_ros2_observation(pos, vel, goal, target_dir, obstacles, dynamic_obstacles, device)
    pos_t = torch.tensor(pos, dtype=torch.float, device=device)
    goal_t = torch.tensor(goal, dtype=torch.float, device=device)
    if check_obstacle(lidar_scan, dyn_obs_states):
        with set_exploration_type(ExplorationType.MEAN):
            output = policy(obs)
        vel_local_normalized = output["agents", "action_normalized"]
        vel_local_world = 2.0 * vel_local_normalized * VEL_LIMIT - VEL_LIMIT
        vel_world = vec_to_world(vel_local_world, output["agents", "observation", "direction"])
        source = "rl"
    else:
        vel_world = (goal_t - pos_t) / torch.norm(goal_t - pos_t).clamp(1e-6) * VEL_LIMIT
        source = "direct"
    return vel_world.squeeze(0).squeeze(0).detach().cpu().numpy(), source


def sqr(value):
    return value * value


def norm_sq(value):
    return float(np.dot(value, value))


def normalize(value):
    norm = float(np.linalg.norm(value))
    if norm <= EPSILON:
        return np.zeros_like(value)
    return value / norm


def get_orca_plane(agent_pos, preferred_vel, agent_radius, obs_pos, obs_vel, obs_radius, use_circle):
    inv_time_horizon = 1.0 / SAFE_TIME_HORIZON
    relative_position = obs_pos - agent_pos
    relative_velocity = preferred_vel - obs_vel
    dist_sq = norm_sq(relative_position)
    combined_radius = agent_radius + obs_radius
    combined_radius_sq = sqr(combined_radius)
    in_vo = False

    if dist_sq > combined_radius_sq:
        rel_pos_norm = max(float(np.linalg.norm(relative_position)), EPSILON)
        rel_vel_norm = max(float(np.linalg.norm(relative_velocity)), EPSILON)
        w = relative_velocity - inv_time_horizon * relative_position
        w_length_sq = norm_sq(w)
        dot_product = float(np.dot(w, relative_position))
        angle_vo = np.arcsin(np.clip(combined_radius / rel_pos_norm, -1.0, 1.0))
        dist_to_obs = float(np.linalg.norm(relative_velocity * SAFE_TIME_HORIZON - relative_position))
        angle_vel = np.arccos(np.clip(float(np.dot(relative_position, relative_velocity)) / (rel_pos_norm * rel_vel_norm), -1.0, 1.0))

        if use_circle and dot_product < 0.0 and sqr(dot_product) > combined_radius_sq * w_length_sq:
            if dist_to_obs < combined_radius:
                in_vo = True
            w_length = max(float(np.sqrt(w_length_sq)), EPSILON)
            unit_w = w / w_length
            normal = unit_w
            u = (combined_radius * inv_time_horizon - w_length) * unit_w
        else:
            if angle_vel < angle_vo:
                in_vo = True
            a = dist_sq
            b = float(np.dot(relative_position, relative_velocity))
            cross_value = np.cross(relative_position, relative_velocity)
            c = norm_sq(relative_velocity) - norm_sq(cross_value) / max(dist_sq - combined_radius_sq, EPSILON)
            discriminant = max(sqr(b) - a * c, 0.0)
            t = (b + np.sqrt(discriminant)) / max(a, EPSILON)
            w = relative_velocity - t * relative_position
            w_length = max(float(np.linalg.norm(w)), EPSILON)
            unit_w = w / w_length
            normal = unit_w
            u = (combined_radius * t - w_length) * unit_w
    else:
        inv_time_step = 1.0 / SAFE_TIME_STEP
        w = relative_velocity - inv_time_step * relative_position
        w_length = max(float(np.linalg.norm(w)), EPSILON)
        unit_w = w / w_length
        normal = unit_w
        u = (combined_radius * inv_time_step - w_length) * unit_w
        in_vo = True

    return {"point": preferred_vel + u, "normal": normal}, in_vo


def linear_program1(planes, plane_no, line, radius, opt_velocity, direction_opt, result):
    dot_product = float(np.dot(line["point"], line["direction"]))
    discriminant = sqr(dot_product) + sqr(radius) - norm_sq(line["point"])
    if discriminant < 0.0:
        return False, result
    sqrt_discriminant = np.sqrt(discriminant)
    t_left = -dot_product - sqrt_discriminant
    t_right = -dot_product + sqrt_discriminant
    for i in range(plane_no):
        numerator = float(np.dot(planes[i]["point"] - line["point"], planes[i]["normal"]))
        denominator = float(np.dot(line["direction"], planes[i]["normal"]))
        if sqr(denominator) <= EPSILON:
            if numerator > 0.0:
                return False, result
            continue
        t = numerator / denominator
        if denominator >= 0.0:
            t_left = max(t_left, t)
        else:
            t_right = min(t_right, t)
        if t_left > t_right:
            return False, result
    if direction_opt:
        if float(np.dot(opt_velocity, line["direction"])) > 0.0:
            result = line["point"] + t_right * line["direction"]
        else:
            result = line["point"] + t_left * line["direction"]
    else:
        t = float(np.dot(line["direction"], opt_velocity - line["point"]))
        if t < t_left:
            result = line["point"] + t_left * line["direction"]
        elif t > t_right:
            result = line["point"] + t_right * line["direction"]
        else:
            result = line["point"] + t * line["direction"]
    return True, result


def linear_program2(planes, plane_no, radius, opt_velocity, direction_opt, result):
    plane_dist = float(np.dot(planes[plane_no]["point"], planes[plane_no]["normal"]))
    plane_dist_sq = sqr(plane_dist)
    radius_sq = sqr(radius)
    if plane_dist_sq > radius_sq:
        return False, result
    plane_radius_sq = radius_sq - plane_dist_sq
    plane_center = plane_dist * planes[plane_no]["normal"]
    if direction_opt:
        plane_opt_velocity = opt_velocity - float(np.dot(opt_velocity, planes[plane_no]["normal"])) * planes[plane_no]["normal"]
        plane_opt_velocity_length_sq = norm_sq(plane_opt_velocity)
        if plane_opt_velocity_length_sq <= EPSILON:
            result = plane_center
        else:
            result = plane_center + np.sqrt(plane_radius_sq / plane_opt_velocity_length_sq) * plane_opt_velocity
    else:
        result = opt_velocity + float(np.dot(planes[plane_no]["point"] - opt_velocity, planes[plane_no]["normal"])) * planes[plane_no]["normal"]
        if norm_sq(result) > radius_sq:
            plane_result = result - plane_center
            plane_result_length_sq = max(norm_sq(plane_result), EPSILON)
            result = plane_center + np.sqrt(plane_radius_sq / plane_result_length_sq) * plane_result

    for i in range(plane_no):
        if float(np.dot(planes[i]["normal"], planes[i]["point"] - result)) > 0.0:
            cross_product = np.cross(planes[i]["normal"], planes[plane_no]["normal"])
            if norm_sq(cross_product) <= EPSILON:
                return False, result
            line = {}
            line["direction"] = normalize(cross_product)
            line_normal = np.cross(line["direction"], planes[plane_no]["normal"])
            denom = max(abs(float(np.dot(line_normal, planes[i]["normal"]))), EPSILON)
            signed_denom = float(np.dot(line_normal, planes[i]["normal"]))
            signed_denom = denom if signed_denom >= 0 else -denom
            line["point"] = planes[plane_no]["point"] + (
                float(np.dot(planes[i]["point"] - planes[plane_no]["point"], planes[i]["normal"])) / signed_denom
            ) * line_normal
            ok, result = linear_program1(planes, i, line, radius, opt_velocity, direction_opt, result)
            if not ok:
                return False, result
    return True, result


def linear_program3(planes, radius, opt_velocity, direction_opt):
    if direction_opt:
        result = opt_velocity * radius
    elif norm_sq(opt_velocity) > sqr(radius):
        result = normalize(opt_velocity) * radius
    else:
        result = opt_velocity.copy()

    for i in range(len(planes)):
        if float(np.dot(planes[i]["normal"], planes[i]["point"] - result)) > 0.0:
            temp_result = result.copy()
            ok, result = linear_program2(planes, i, radius, opt_velocity, direction_opt, result)
            if not ok:
                result = temp_result
                return i, result
    return len(planes), result


def linear_program4(planes, begin_plane, radius, result):
    distance = 0.0
    for i in range(begin_plane, len(planes)):
        if float(np.dot(planes[i]["normal"], planes[i]["point"] - result)) > distance:
            proj_planes = []
            for j in range(i):
                cross_product = np.cross(planes[j]["normal"], planes[i]["normal"])
                if norm_sq(cross_product) <= EPSILON:
                    if float(np.dot(planes[i]["normal"], planes[j]["normal"])) > 0.0:
                        continue
                    point = 0.5 * (planes[i]["point"] + planes[j]["point"])
                else:
                    line_normal = np.cross(cross_product, planes[i]["normal"])
                    denom = float(np.dot(line_normal, planes[j]["normal"]))
                    if abs(denom) <= EPSILON:
                        continue
                    point = planes[i]["point"] + (
                        float(np.dot(planes[j]["point"] - planes[i]["point"], planes[j]["normal"])) / denom
                    ) * line_normal
                normal = normalize(planes[j]["normal"] - planes[i]["normal"])
                proj_planes.append({"point": point, "normal": normal})
            temp_result = result.copy()
            plane_fail, result = linear_program3(proj_planes, radius, planes[i]["normal"], True)
            if plane_fail < len(proj_planes):
                result = temp_result
            distance = float(np.dot(planes[i]["normal"], planes[i]["point"] - result))
    return result


def approximate_safe_action(pos, preferred_vel, obstacles, dynamic_obstacles):
    agent_pos = pos.astype(float)
    preferred_vel = preferred_vel.astype(float)
    planes = []
    need_solve = False

    for obs in dynamic_obstacles:
        obs_pos = obs["pos"].astype(float)
        obs_vel = obs["vel"].astype(float)
        obs_radius = np.sqrt(sqr(obs["size"][0]) + sqr(obs["size"][1])) / 2.0
        plane, in_vo = get_orca_plane(
            agent_pos,
            preferred_vel,
            ROBOT_RADIUS + SAFE_DISTANCE,
            obs_pos,
            obs_vel,
            obs_radius,
            True,
        )
        planes.append(plane)
        need_solve = need_solve or in_vo

    for ox, oy, radius in obstacles:
        obs_pos = np.array([ox, oy, agent_pos[2]], dtype=float)
        if np.linalg.norm(obs_pos[:2] - agent_pos[:2]) > MAX_RAY_LENGTH + radius:
            continue
        plane, in_vo = get_orca_plane(
            agent_pos,
            preferred_vel,
            0.0,
            obs_pos,
            np.zeros(3, dtype=float),
            radius * 1.5,
            True,
        )
        planes.append(plane)
        need_solve = need_solve or in_vo

    if not need_solve:
        return preferred_vel, False

    plane_fail, safe_vel = linear_program3(planes, SAFE_MAX_VELOCITY, preferred_vel, False)
    if plane_fail < len(planes):
        safe_vel = linear_program4(planes, plane_fail, SAFE_MAX_VELOCITY, safe_vel)
    return safe_vel, bool(np.linalg.norm(safe_vel - preferred_vel) > 1e-5)


def min_static_clearance(pos, obstacles):
    if not obstacles:
        return float("inf")
    return min(float(np.linalg.norm(pos[:2] - np.array([ox, oy])) - radius) for ox, oy, radius in obstacles)


def min_dynamic_clearance(pos, dynamic_obstacles):
    if not dynamic_obstacles:
        return float("inf")
    return min(float(np.linalg.norm(pos[:2] - obs["pos"][:2]) - ROBOT_RADIUS) for obs in dynamic_obstacles)


def rollout(policy, device, seed, frames, static_grid_div, dynamic_count, dynamic_layout, route, use_safe_action):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    obstacles = generate_obstacles_grid(static_grid_div, OBSTACLE_REGION_MIN, OBSTACLE_REGION_MAX, MIN_RADIUS, MAX_RADIUS)
    if route == "corridor":
        start = np.array([0.0, -12.0], dtype=float)
        goal_xy = np.array([0.0, 12.0], dtype=float)
    else:
        start = sample_free_point(obstacles)
        goal_xy = sample_free_point(obstacles)
        while np.linalg.norm(goal_xy - start) < 12.0:
            goal_xy = sample_free_point(obstacles)
    pos = np.array([start[0], start[1], 0.0], dtype=float)
    goal = np.array([goal_xy[0], goal_xy[1], 0.0], dtype=float)
    vel = np.zeros(3, dtype=float)
    target_dir = goal - pos
    dynamic_obstacles = make_dynamic_obstacles(seed, dynamic_count, pos, goal, dynamic_layout)
    path_len = 0.0
    rl_steps = 0
    direct_steps = 0
    safe_steps = 0
    safe_delta = 0.0
    min_static = float("inf")
    min_dynamic = float("inf")

    for frame in range(frames):
        distance = np.linalg.norm(goal - pos)
        min_static = min(min_static, min_static_clearance(pos, obstacles))
        min_dynamic = min(min_dynamic, min_dynamic_clearance(pos, dynamic_obstacles))
        if distance <= 1.0:
            return {
                "status": "reached",
                "steps": frame,
                "final_dist": distance,
                "path_len": path_len,
                "min_static": min_static,
                "min_dynamic": min_dynamic,
                "rl_steps": rl_steps,
                "direct_steps": direct_steps,
                "safe_steps": safe_steps,
                "safe_delta": safe_delta,
            }
        if min_static <= ROBOT_RADIUS:
            return {
                "status": "static_collision",
                "steps": frame,
                "final_dist": distance,
                "path_len": path_len,
                "min_static": min_static,
                "min_dynamic": min_dynamic,
                "rl_steps": rl_steps,
                "direct_steps": direct_steps,
                "safe_steps": safe_steps,
                "safe_delta": safe_delta,
            }
        if min_dynamic <= ROBOT_RADIUS:
            return {
                "status": "dynamic_collision",
                "steps": frame,
                "final_dist": distance,
                "path_len": path_len,
                "min_static": min_static,
                "min_dynamic": min_dynamic,
                "rl_steps": rl_steps,
                "direct_steps": direct_steps,
                "safe_steps": safe_steps,
                "safe_delta": safe_delta,
            }

        action, source = get_action(policy, pos, vel, goal, target_dir, obstacles, dynamic_obstacles, device)
        if source == "rl":
            rl_steps += 1
        else:
            direct_steps += 1

        if use_safe_action:
            safe_action, adjusted = approximate_safe_action(pos, action, obstacles, dynamic_obstacles)
            if adjusted:
                safe_steps += 1
                safe_delta += float(np.linalg.norm(safe_action - action))
            action = safe_action

        if distance <= 3.0 and distance > 1.0:
            norm = np.linalg.norm(action)
            if norm > 0:
                action = action / norm
        elif distance <= 1.0:
            action *= 0.0

        step = action * DT
        pos = pos + step
        vel = action.copy()
        path_len += float(np.linalg.norm(step))
        update_dynamic_obstacles(dynamic_obstacles)

    return {
        "status": "timeout",
        "steps": frames,
        "final_dist": float(np.linalg.norm(goal - pos)),
        "path_len": path_len,
        "min_static": min_static,
        "min_dynamic": min_dynamic,
        "rl_steps": rl_steps,
        "direct_steps": direct_steps,
        "safe_steps": safe_steps,
        "safe_delta": safe_delta,
    }


def summarize(label, results):
    n = len(results)
    reached = sum(item["status"] == "reached" for item in results)
    static_col = sum(item["status"] == "static_collision" for item in results)
    dynamic_col = sum(item["status"] == "dynamic_collision" for item in results)
    timeout = sum(item["status"] == "timeout" for item in results)
    avg_steps = np.mean([item["steps"] for item in results])
    avg_final_dist = np.mean([item["final_dist"] for item in results])
    avg_path = np.mean([item["path_len"] for item in results])
    finite_static = [item["min_static"] for item in results if np.isfinite(item["min_static"])]
    min_static = np.min(finite_static) if finite_static else float("inf")
    min_dynamic = np.min([item["min_dynamic"] for item in results])
    rl_ratio = sum(item["rl_steps"] for item in results) / max(
        1, sum(item["rl_steps"] + item["direct_steps"] for item in results)
    )
    safe_ratio = sum(item["safe_steps"] for item in results) / max(
        1, sum(item["rl_steps"] + item["direct_steps"] for item in results)
    )
    avg_safe_delta = sum(item["safe_delta"] for item in results) / max(1, sum(item["safe_steps"] for item in results))
    print(
        f"{label:18s} reach={reached:3d}/{n:<3d} static_col={static_col:3d}/{n:<3d} "
        f"dynamic_col={dynamic_col:3d}/{n:<3d} timeout={timeout:3d}/{n:<3d} "
        f"avg_steps={avg_steps:6.1f} avg_final_dist={avg_final_dist:7.3f} "
        f"min_static={min_static:7.3f} min_dynamic={min_dynamic:7.3f} "
        f"avg_path={avg_path:7.3f} rl_ratio={rl_ratio:5.2f} "
        f"safe_ratio={safe_ratio:5.2f} safe_delta={avg_safe_delta:7.3f}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", action="append", type=parse_policy)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--frames", type=int, default=FRAMES)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--static-grid-div", type=int, default=GRID_DIV)
    parser.add_argument("--dynamic-count", type=int, default=3)
    parser.add_argument("--dynamic-layout", choices=["side-crossing", "path-crossing", "head-on"], default="side-crossing")
    parser.add_argument("--route", choices=["random", "corridor"], default="random")
    parser.add_argument("--safe-action", action="store_true")
    args = parser.parse_args()

    policies = args.policy or [("author", os.path.abspath(os.path.join("ckpts", "navrl_checkpoint.pt")))]
    device = torch.device(args.device)
    print(
        f"mode=ros2-style-offline seeds={args.seeds} frames={args.frames} "
        f"vel_limit={VEL_LIMIT} static_grid_div={args.static_grid_div} "
        f"dynamic_count={args.dynamic_count} dynamic_layout={args.dynamic_layout} "
        f"route={args.route} safe_action={args.safe_action} device={device}"
    )
    for label, checkpoint in policies:
        policy = init_policy(device, checkpoint)
        results = [
            rollout(
                policy,
                device,
                seed,
                args.frames,
                args.static_grid_div,
                args.dynamic_count,
                args.dynamic_layout,
                args.route,
                args.safe_action,
            )
            for seed in range(args.seeds)
        ]
        summarize(label, results)


if __name__ == "__main__":
    main()
