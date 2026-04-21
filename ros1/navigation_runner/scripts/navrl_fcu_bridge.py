#!/usr/bin/env python3
import math
import os
import time

import hydra
import numpy as np
import rospy
import torch
from geometry_msgs.msg import Point, PoseStamped, Vector3
from map_manager.srv import RayCast
from nav_msgs.msg import Odometry
from navigation_runner.srv import GetSafeAction
from onboard_detector.srv import GetDynamicObstacles
from std_msgs.msg import Bool, Float32MultiArray, MultiArrayDimension
from tensordict.tensordict import TensorDict
from torchrl.data import CompositeSpec, UnboundedContinuousTensorSpec
from torchrl.envs.utils import ExplorationType, set_exploration_type

from ppo import PPO
from utils import vec_to_new_frame


class NavRLFcuBridge:
    """Thin ROS1 adapter from the NavRL local policy to FCU mission_001."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.device = rospy.get_param("~device", str(cfg.device))
        self.lidar_hbeams = int(360 / self.cfg.sensor.lidar_hres)
        self.dyn_obs_num = int(self.cfg.algo.feature_extractor.dyn_obs_num)
        self.robot_size = rospy.get_param("~robot_size", 0.3)
        self.height_control = rospy.get_param("~height_control", False)
        self.hold_current_z = rospy.get_param("~hold_current_z", True)
        self.goal_reached_threshold = rospy.get_param("~goal_reached_threshold", 0.3)
        self.command_horizon = rospy.get_param("~command_horizon", 0.2)
        self.control_rate = rospy.get_param("~control_rate", 10.0)
        self.author_obstacle_gate = rospy.get_param("~author_obstacle_gate", True)
        self.use_safe_action = rospy.get_param("~use_safe_action", True)
        self.use_velocity_fields = rospy.get_param("~use_velocity_fields", False)
        self.dry_run = rospy.get_param("~dry_run", True)
        self.publish_hold_on_stop = rospy.get_param("~publish_hold_on_stop", True)
        self.max_horizontal_speed = rospy.get_param(
            "~max_horizontal_speed", float(self.cfg.algo.actor.action_limit)
        )
        self.max_vertical_speed = rospy.get_param("~max_vertical_speed", 0.3)
        self.odom_timeout = rospy.get_param("~odom_timeout", 1.0)

        self.odom_topic = rospy.get_param("~odom_topic", "/odom_global_001")
        self.goal_topic = rospy.get_param("~goal_topic", "/move_base_simple/goal")
        self.emergency_stop_topic = rospy.get_param(
            "~emergency_stop_topic", "/navrl_fcu_bridge/emergency_stop"
        )
        self.mission_topic = rospy.get_param("~mission_topic", "/fcu_mission/mission_001")
        self.dry_run_mission_topic = rospy.get_param(
            "~dry_run_mission_topic", "/navrl_fcu_bridge/dry_run_mission_001"
        )
        self.raycast_service = rospy.get_param("~raycast_service", "/occupancy_map/raycast")
        self.dynamic_obstacle_service = rospy.get_param(
            "~dynamic_obstacle_service", "/onboard_detector/get_dynamic_obstacles"
        )
        self.safe_action_service = rospy.get_param(
            "~safe_action_service", "/rl_navigation/get_safe_action"
        )

        self.raycast_vres = (
            (self.cfg.sensor.lidar_vfov[1] - self.cfg.sensor.lidar_vfov[0])
            / (self.cfg.sensor.lidar_vbeams - 1)
            * math.pi
            / 180.0
        )
        self.raycast_hres = self.cfg.sensor.lidar_hres * math.pi / 180.0

        self.odom = None
        self.odom_stamp = None
        self.goal = None
        self.target_dir = None
        self.safety_stop = False
        self.last_warn = {}

        checkpoint_file = rospy.get_param("~checkpoint_file", "navrl_checkpoint.pt")
        self.checkpoint_path = self.resolve_checkpoint(checkpoint_file)
        self.policy = self.init_model(self.checkpoint_path)
        self.policy.eval()

        self.odom_sub = rospy.Subscriber(self.odom_topic, Odometry, self.odom_callback, queue_size=10)
        self.goal_sub = rospy.Subscriber(self.goal_topic, PoseStamped, self.goal_callback, queue_size=10)
        self.stop_sub = rospy.Subscriber(
            self.emergency_stop_topic, Bool, self.emergency_stop_callback, queue_size=10
        )
        self.mission_pub = rospy.Publisher(self.mission_topic, Float32MultiArray, queue_size=10)
        self.dry_run_pub = rospy.Publisher(self.dry_run_mission_topic, Float32MultiArray, queue_size=10)

        rospy.loginfo("[navrl_fcu_bridge] checkpoint: %s", self.checkpoint_path)
        rospy.loginfo("[navrl_fcu_bridge] odom_topic: %s", self.odom_topic)
        rospy.loginfo("[navrl_fcu_bridge] goal_topic: %s", self.goal_topic)
        rospy.loginfo("[navrl_fcu_bridge] mission_topic: %s", self.mission_topic)
        rospy.loginfo("[navrl_fcu_bridge] dry_run_topic: %s", self.dry_run_mission_topic)
        rospy.loginfo("[navrl_fcu_bridge] dry_run: %s", self.dry_run)
        rospy.loginfo("[navrl_fcu_bridge] author_obstacle_gate: %s", self.author_obstacle_gate)
        rospy.loginfo("[navrl_fcu_bridge] use_safe_action: %s", self.use_safe_action)
        rospy.loginfo(
            "[navrl_fcu_bridge] FCU mission frame: NavRL/ROS FLU -> FCU mission FRU by y/yaw sign flip"
        )

        self.timer = rospy.Timer(rospy.Duration(1.0 / self.control_rate), self.control_callback)

    def resolve_checkpoint(self, checkpoint_file):
        if os.path.isabs(checkpoint_file):
            return checkpoint_file
        file_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ckpts")
        return os.path.join(file_dir, checkpoint_file)

    def init_model(self, checkpoint_path):
        observation_dim = 8
        num_dim_each_dyn_obs_state = 10
        observation_spec = CompositeSpec(
            {
                "agents": CompositeSpec(
                    {
                        "observation": CompositeSpec(
                            {
                                "state": UnboundedContinuousTensorSpec(
                                    (observation_dim,), device=self.device
                                ),
                                "lidar": UnboundedContinuousTensorSpec(
                                    (1, self.lidar_hbeams, self.cfg.sensor.lidar_vbeams),
                                    device=self.device,
                                ),
                                "direction": UnboundedContinuousTensorSpec(
                                    (1, 3), device=self.device
                                ),
                                "dynamic_obstacle": UnboundedContinuousTensorSpec(
                                    (
                                        1,
                                        self.dyn_obs_num,
                                        num_dim_each_dyn_obs_state,
                                    ),
                                    device=self.device,
                                ),
                            }
                        ),
                    }
                ).expand(1)
            },
            shape=[1],
            device=self.device,
        )

        action_dim = 3
        action_spec = CompositeSpec(
            {
                "agents": CompositeSpec(
                    {
                        "action": UnboundedContinuousTensorSpec(
                            (action_dim,), device=self.device
                        ),
                    }
                )
            }
        ).expand(1, action_dim).to(self.device)

        policy = PPO(self.cfg.algo, observation_spec, action_spec, self.device)
        policy.load_state_dict(torch.load(checkpoint_path, map_location=self.device))
        return policy

    def odom_callback(self, msg):
        self.odom = msg
        self.odom_stamp = rospy.Time.now()

    def goal_callback(self, msg):
        if self.odom is None:
            self.warn_throttle("goal_without_odom", "goal received before odom; ignoring")
            return
        goal = PoseStamped()
        goal.header = msg.header
        goal.pose = msg.pose
        if self.hold_current_z:
            goal.pose.position.z = self.odom.pose.pose.position.z
        self.goal = goal
        self.update_target_dir()
        rospy.loginfo(
            "[navrl_fcu_bridge] goal: x=%.3f y=%.3f z=%.3f",
            self.goal.pose.position.x,
            self.goal.pose.position.y,
            self.goal.pose.position.z,
        )

    def emergency_stop_callback(self, msg):
        self.safety_stop = bool(msg.data)
        rospy.logwarn("[navrl_fcu_bridge] emergency_stop=%s", self.safety_stop)

    def update_target_dir(self):
        if self.odom is None or self.goal is None:
            return
        self.target_dir = torch.tensor(
            [
                self.goal.pose.position.x - self.odom.pose.pose.position.x,
                self.goal.pose.position.y - self.odom.pose.pose.position.y,
                self.goal.pose.position.z - self.odom.pose.pose.position.z,
            ],
            dtype=torch.float,
            device=self.device,
        )

    def quaternion_to_rotation_matrix(self, quaternion):
        w = quaternion.w
        x = quaternion.x
        y = quaternion.y
        z = quaternion.z
        return np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
                [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
                [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
            ]
        )

    def yaw_from_quaternion(self, quaternion):
        w = quaternion.w
        x = quaternion.x
        y = quaternion.y
        z = quaternion.z
        siny_cosp = 2.0 * (w * z + x * y)
        cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
        return math.atan2(siny_cosp, cosy_cosp)

    def warn_throttle(self, key, message, period=2.0):
        now = time.time()
        if now - self.last_warn.get(key, 0.0) >= period:
            rospy.logwarn("[navrl_fcu_bridge] %s", message)
            self.last_warn[key] = now

    def get_raycast(self, pos, start_angle):
        fallback = torch.zeros(
            (1, 1, self.lidar_hbeams, self.cfg.sensor.lidar_vbeams),
            dtype=torch.float,
            device=self.device,
        )
        try:
            rospy.wait_for_service(self.raycast_service, timeout=0.01)
            raycast = rospy.ServiceProxy(self.raycast_service, RayCast)
            pos_msg = Point(x=float(pos[0]), y=float(pos[1]), z=float(pos[2]))
            response = raycast(
                pos_msg,
                float(start_angle),
                float(self.cfg.sensor.lidar_range),
                float(self.cfg.sensor.lidar_vfov[0]),
                float(self.cfg.sensor.lidar_vfov[1]),
                int(self.cfg.sensor.lidar_vbeams),
                float(self.cfg.sensor.lidar_hres),
            )
            num_points = int(len(response.points) / 3)
            raypoints = []
            for i in range(num_points):
                raypoints.append(
                    [
                        response.points[3 * i + 0],
                        response.points[3 * i + 1],
                        response.points[3 * i + 2],
                    ]
                )
            lidar_scan = torch.tensor(raypoints, device=self.device)
            lidar_scan = (
                (lidar_scan - pos)
                .norm(dim=-1)
                .clamp_max(self.cfg.sensor.lidar_range)
                .reshape(1, 1, self.lidar_hbeams, self.cfg.sensor.lidar_vbeams)
            )
            return self.cfg.sensor.lidar_range - lidar_scan, response.points
        except Exception as exc:
            self.warn_throttle("raycast", "raycast unavailable; using zero static obstacle input")
            return fallback, []

    def get_dynamic_obstacles(self, pos):
        dyn_pos = torch.zeros(self.dyn_obs_num, 3, dtype=torch.float, device=self.device)
        dyn_vel = torch.zeros(self.dyn_obs_num, 3, dtype=torch.float, device=self.device)
        dyn_size = torch.zeros(self.dyn_obs_num, 3, dtype=torch.float, device=self.device)
        try:
            rospy.wait_for_service(self.dynamic_obstacle_service, timeout=0.01)
            get_obstacle = rospy.ServiceProxy(self.dynamic_obstacle_service, GetDynamicObstacles)
            response = get_obstacle(Point(x=float(pos[0]), y=float(pos[1]), z=float(pos[2])), 4.0)
            for i in range(min(self.dyn_obs_num, len(response.position))):
                dyn_pos[i] = torch.tensor(
                    [response.position[i].x, response.position[i].y, response.position[i].z],
                    dtype=torch.float,
                    device=self.device,
                )
                dyn_vel[i] = torch.tensor(
                    [response.velocity[i].x, response.velocity[i].y, response.velocity[i].z],
                    dtype=torch.float,
                    device=self.device,
                )
                dyn_size[i] = torch.tensor(
                    [response.size[i].x, response.size[i].y, response.size[i].z],
                    dtype=torch.float,
                    device=self.device,
                )
        except Exception:
            self.warn_throttle("dynamic_obstacle", "dynamic obstacle service unavailable; using zeros")
        return dyn_pos, dyn_vel, dyn_size

    def build_observation(self, pos, vel_world):
        target_dir_2d = self.target_dir.clone()
        target_dir_2d[2] = 0.0
        if target_dir_2d.norm() < 1e-6:
            target_dir_2d = torch.tensor([1.0, 0.0, 0.0], device=self.device)

        goal = torch.tensor(
            [
                self.goal.pose.position.x,
                self.goal.pose.position.y,
                self.goal.pose.position.z,
            ],
            dtype=torch.float,
            device=self.device,
        )
        rpos = goal - pos
        distance = rpos.norm(dim=-1, keepdim=True)
        distance_2d = rpos[..., :2].norm(dim=-1, keepdim=True)
        distance_z = rpos[..., 2].unsqueeze(-1)
        rpos_clipped = rpos / distance.clamp(1e-6)
        rpos_clipped_g = vec_to_new_frame(rpos_clipped, target_dir_2d).squeeze(0).squeeze(0)
        vel_g = vec_to_new_frame(vel_world, target_dir_2d).squeeze(0).squeeze(0)
        drone_state = torch.cat([rpos_clipped_g, distance_2d, distance_z, vel_g], dim=-1).unsqueeze(0)

        start_angle = math.atan2(target_dir_2d[1].item(), target_dir_2d[0].item())
        lidar_scan, laser_points = self.get_raycast(pos, start_angle)

        dyn_pos, dyn_vel, dyn_size = self.get_dynamic_obstacles(pos)
        closest_dyn_obs_rpos = dyn_pos - pos
        closest_dyn_obs_rpos[dyn_size[:, 2] == 0] = 0.0
        closest_dyn_obs_rpos[:, 2][dyn_size[:, 2] > 1] = 0.0
        closest_dyn_obs_rpos_g = vec_to_new_frame(
            closest_dyn_obs_rpos.unsqueeze(0), target_dir_2d
        ).squeeze(0)
        closest_dyn_obs_distance = closest_dyn_obs_rpos.norm(dim=-1, keepdim=True)
        closest_dyn_obs_distance_2d = closest_dyn_obs_rpos_g[..., :2].norm(
            dim=-1, keepdim=True
        )
        closest_dyn_obs_distance_z = closest_dyn_obs_rpos_g[..., 2].unsqueeze(-1)
        closest_dyn_obs_rpos_gn = closest_dyn_obs_rpos_g / closest_dyn_obs_distance.clamp(1e-6)
        closest_dyn_obs_vel_g = vec_to_new_frame(dyn_vel.unsqueeze(0), target_dir_2d).squeeze(0)

        obs_res = 0.25
        closest_dyn_obs_width = torch.max(dyn_size[:, 0], dyn_size[:, 1])
        closest_dyn_obs_width += self.robot_size * 2.0
        closest_dyn_obs_width = torch.clamp(
            torch.ceil(closest_dyn_obs_width / obs_res) - 1,
            min=0,
            max=1.0 / obs_res - 1,
        )
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

        obs = TensorDict(
            {
                "agents": TensorDict(
                    {
                        "observation": TensorDict(
                            {
                                "state": drone_state,
                                "lidar": lidar_scan,
                                "direction": target_dir_2d,
                                "dynamic_obstacle": dyn_obs_states,
                            }
                        )
                    }
                )
            },
            device=self.device,
        )
        return obs, lidar_scan, dyn_obs_states, laser_points, (dyn_pos, dyn_vel, dyn_size)

    def check_obstacle(self, lidar_scan, dyn_obs_states):
        quarter_size = lidar_scan.shape[2] // 4
        first_quarter_clear = torch.all(lidar_scan[:, :, :quarter_size, 1:] < 0.2)
        last_quarter_clear = torch.all(lidar_scan[:, :, -quarter_size:, 1:] < 0.2)
        has_static = (not first_quarter_clear) or (not last_quarter_clear)
        has_dynamic = not torch.all(dyn_obs_states == 0.0)
        return bool(has_static or has_dynamic)

    def direct_goal_velocity(self, pos):
        goal = torch.tensor(
            [
                self.goal.pose.position.x,
                self.goal.pose.position.y,
                self.goal.pose.position.z,
            ],
            dtype=torch.float,
            device=self.device,
        )
        direction = goal - pos
        norm = direction.norm().clamp(1e-6)
        return (direction / norm * float(self.cfg.algo.actor.action_limit)).cpu().numpy()

    def get_policy_velocity(self, obs):
        with set_exploration_type(ExplorationType.MEAN):
            output = self.policy(obs)
        return output["agents", "action"].squeeze(0).squeeze(0).detach().cpu().numpy()

    def get_safe_action(self, pos, vel_world, selected_vel_world, laser_points, dyn_obstacles):
        if not self.use_safe_action:
            return selected_vel_world
        try:
            rospy.wait_for_service(self.safe_action_service, timeout=0.01)
            get_safe_action = rospy.ServiceProxy(self.safe_action_service, GetSafeAction)
            dyn_pos, dyn_vel, dyn_size = dyn_obstacles
            obs_pos_list = []
            obs_vel_list = []
            obs_size_list = []
            for i in range(self.dyn_obs_num):
                if dyn_size[i][0].item() != 0.0:
                    obs_pos_list.append(
                        Vector3(x=dyn_pos[i][0].item(), y=dyn_pos[i][1].item(), z=dyn_pos[i][2].item())
                    )
                    obs_vel_list.append(
                        Vector3(x=dyn_vel[i][0].item(), y=dyn_vel[i][1].item(), z=dyn_vel[i][2].item())
                    )
                    obs_size_list.append(
                        Vector3(
                            x=dyn_size[i][0].item(),
                            y=dyn_size[i][1].item(),
                            z=dyn_size[i][2].item(),
                        )
                    )
            response = get_safe_action(
                Point(x=pos[0].item(), y=pos[1].item(), z=pos[2].item()),
                Vector3(x=vel_world[0].item(), y=vel_world[1].item(), z=vel_world[2].item()),
                self.robot_size,
                obs_pos_list,
                obs_vel_list,
                obs_size_list,
                laser_points,
                float(self.cfg.sensor.lidar_range),
                float(max(self.raycast_vres, self.raycast_hres)),
                float(math.sqrt(3.0 * self.cfg.algo.actor.action_limit ** 2)),
                Vector3(
                    x=float(selected_vel_world[0]),
                    y=float(selected_vel_world[1]),
                    z=float(selected_vel_world[2]),
                ),
            )
            return np.array([response.safe_action.x, response.safe_action.y, response.safe_action.z])
        except Exception:
            self.warn_throttle("safe_action", "safe_action unavailable; using selected NavRL/direct action")
            return selected_vel_world

    def clamp_velocity(self, vel):
        clamped = np.array(vel, dtype=float)
        horizontal_norm = np.linalg.norm(clamped[:2])
        did_clamp = False
        if horizontal_norm > self.max_horizontal_speed > 0:
            clamped[:2] *= self.max_horizontal_speed / horizontal_norm
            did_clamp = True
        if abs(clamped[2]) > self.max_vertical_speed:
            clamped[2] = math.copysign(self.max_vertical_speed, clamped[2])
            did_clamp = True
        if not self.height_control:
            clamped[2] = 0.0
        return clamped, did_clamp

    def build_mission(self, vel_world):
        curr = self.odom.pose.pose.position
        goal_yaw = math.atan2(self.target_dir[1].item(), self.target_dir[0].item())
        target_x = curr.x + float(vel_world[0]) * self.command_horizon
        target_y = curr.y + float(vel_world[1]) * self.command_horizon
        target_z = curr.z + float(vel_world[2]) * self.command_horizon if self.height_control else curr.z

        msg = Float32MultiArray()
        msg.layout.dim.append(MultiArrayDimension(label="mission_001", size=11, stride=1))
        msg.data = [0.0] * 11
        # FCU mission target position is FRU and attitude is FRD. NavRL/ROS odom/goal
        # here are FLU, so y, vy, ay, yaw, and yaw_rate must flip sign at the boundary.
        msg.data[0] = -goal_yaw
        msg.data[1] = 0.0
        msg.data[2] = target_x
        msg.data[3] = -target_y
        msg.data[4] = target_z
        if self.use_velocity_fields:
            msg.data[5] = float(vel_world[0])
            msg.data[6] = -float(vel_world[1])
            msg.data[7] = float(vel_world[2])
        return msg

    def publish_mission(self, mission, reason):
        if self.dry_run:
            self.dry_run_pub.publish(mission)
        else:
            self.mission_pub.publish(mission)
        rospy.loginfo_throttle(
            1.0,
            "[navrl_fcu_bridge] %s dry_run=%s mission=[yaw %.2f, x %.2f, y %.2f, z %.2f, vx %.2f, vy %.2f, vz %.2f]",
            reason,
            self.dry_run,
            mission.data[0],
            mission.data[2],
            mission.data[3],
            mission.data[4],
            mission.data[5],
            mission.data[6],
            mission.data[7],
        )

    def publish_hold(self, reason):
        if self.odom is None or not self.publish_hold_on_stop:
            return
        zero_vel = np.zeros(3)
        if self.target_dir is None:
            self.target_dir = torch.tensor([1.0, 0.0, 0.0], dtype=torch.float, device=self.device)
        self.publish_mission(self.build_mission(zero_vel), reason)

    def control_callback(self, _event):
        if self.odom is None:
            self.warn_throttle("no_odom", "waiting for odom")
            return
        if self.odom_stamp is None or (rospy.Time.now() - self.odom_stamp).to_sec() > self.odom_timeout:
            self.publish_hold("odom timeout safety hold")
            return
        if self.goal is None:
            self.warn_throttle("no_goal", "waiting for goal")
            return

        self.update_target_dir()
        if self.safety_stop:
            self.publish_hold("emergency stop safety hold")
            return

        pos = torch.tensor(
            [
                self.odom.pose.pose.position.x,
                self.odom.pose.pose.position.y,
                self.odom.pose.pose.position.z,
            ],
            dtype=torch.float,
            device=self.device,
        )
        goal = torch.tensor(
            [
                self.goal.pose.position.x,
                self.goal.pose.position.y,
                self.goal.pose.position.z,
            ],
            dtype=torch.float,
            device=self.device,
        )
        distance = (goal - pos).norm().item()
        if distance <= self.goal_reached_threshold:
            self.publish_hold("goal reached safety hold")
            return

        rot = self.quaternion_to_rotation_matrix(self.odom.pose.pose.orientation)
        vel_body = np.array(
            [
                self.odom.twist.twist.linear.x,
                self.odom.twist.twist.linear.y,
                self.odom.twist.twist.linear.z,
            ]
        )
        vel_world = torch.tensor(rot @ vel_body, dtype=torch.float, device=self.device)

        obs, lidar_scan, dyn_obs_states, laser_points, dyn_obstacles = self.build_observation(pos, vel_world)
        policy_vel = self.get_policy_velocity(obs)
        has_obstacle = self.check_obstacle(lidar_scan, dyn_obs_states)
        if self.author_obstacle_gate and not has_obstacle:
            selected_vel = self.direct_goal_velocity(pos)
            source = "direct_goal_no_obstacle"
        else:
            selected_vel = policy_vel
            source = "navrl_policy"

        safe_vel = self.get_safe_action(pos, vel_world, selected_vel, laser_points, dyn_obstacles)
        final_vel, did_clamp = self.clamp_velocity(safe_vel)
        mission = self.build_mission(final_vel)
        self.publish_mission(mission, source + (" clamped" if did_clamp else ""))
        rospy.loginfo_throttle(
            1.0,
            "[navrl_fcu_bridge] odom=(%.2f %.2f %.2f) goal=(%.2f %.2f %.2f) dist=%.2f obstacle=%s policy=(%.2f %.2f %.2f) final=(%.2f %.2f %.2f)",
            self.odom.pose.pose.position.x,
            self.odom.pose.pose.position.y,
            self.odom.pose.pose.position.z,
            self.goal.pose.position.x,
            self.goal.pose.position.y,
            self.goal.pose.position.z,
            distance,
            has_obstacle,
            policy_vel[0],
            policy_vel[1],
            policy_vel[2],
            final_vel[0],
            final_vel[1],
            final_vel[2],
        )


FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts/cfg")


@hydra.main(config_path=FILE_PATH, config_name="train", version_base=None)
def main(cfg):
    rospy.init_node("navrl_fcu_bridge", anonymous=False)
    NavRLFcuBridge(cfg)
    rospy.spin()


if __name__ == "__main__":
    main()
