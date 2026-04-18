#!/usr/bin/env python3
"""Minimal ROS2 service stub for controlled NavRL dynamic-obstacle tests."""

import argparse

import rclpy
from geometry_msgs.msg import Vector3
from onboard_detector.srv import GetDynamicObstacles
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node


class DynamicObstacleStub(Node):
    def __init__(self, args):
        super().__init__("dynamic_obstacle_stub")
        self.args = args
        self.service = self.create_service(
            GetDynamicObstacles,
            "/onboard_detector/get_dynamic_obstacles",
            self.handle_request,
        )
        self.get_logger().info(
            "Serving one obstacle at "
            f"pos=({args.x}, {args.y}, {args.z}), "
            f"vel=({args.vx}, {args.vy}, {args.vz}), "
            f"size=({args.sx}, {args.sy}, {args.sz})"
        )

    def handle_request(self, request, response):
        del request
        response.position.append(Vector3(x=self.args.x, y=self.args.y, z=self.args.z))
        response.velocity.append(Vector3(x=self.args.vx, y=self.args.vy, z=self.args.vz))
        response.size.append(Vector3(x=self.args.sx, y=self.args.sy, z=self.args.sz))
        return response


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--x", type=float, default=2.0)
    parser.add_argument("--y", type=float, default=0.0)
    parser.add_argument("--z", type=float, default=1.0)
    parser.add_argument("--vx", type=float, default=0.0)
    parser.add_argument("--vy", type=float, default=0.0)
    parser.add_argument("--vz", type=float, default=0.0)
    parser.add_argument("--sx", type=float, default=0.6)
    parser.add_argument("--sy", type=float, default=0.6)
    parser.add_argument("--sz", type=float, default=1.0)
    return parser.parse_args()


def main():
    args = parse_args()
    rclpy.init()
    node = DynamicObstacleStub(args)
    try:
        rclpy.spin(node)
    except (ExternalShutdownException, KeyboardInterrupt):
        pass
    except Exception as exc:
        if "context is not valid" not in str(exc):
            raise
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
