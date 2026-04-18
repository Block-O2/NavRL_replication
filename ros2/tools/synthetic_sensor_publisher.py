#!/usr/bin/env python3
"""Publish minimal synthetic sensor inputs for NavRL ROS2 map/detector smoke tests."""

import argparse
import array
import math
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from sensor_msgs.msg import Image
from sensor_msgs_py import point_cloud2
from std_msgs.msg import Header
from vision_msgs.msg import Detection2D, Detection2DArray


class SyntheticSensorPublisher(Node):
    def __init__(self, args):
        super().__init__("synthetic_sensor_publisher")
        self.args = args
        self.map_depth_pub = self.create_publisher(Image, "/unitree_go2/front_cam/depth_image", 10)
        self.map_cloud_pub = self.create_publisher(type(self.make_cloud_msg(self.get_clock().now().to_msg())), "/unitree_go2/lidar/point_cloud", 10)
        self.map_pose_pub = self.create_publisher(PoseStamped, "/unitree_go2/pose", 10)

        self.detector_depth_pub = self.create_publisher(Image, "/camera/depth/image_rect_raw", 10)
        self.detector_color_pub = self.create_publisher(Image, "/camera/color/image_raw", 10)
        self.detector_pose_pub = self.create_publisher(PoseStamped, "/mavros/local_position/pose", 10)
        self.yolo_pub = self.create_publisher(Detection2DArray, "yolo_detector/detected_bounding_boxes", 10)

        self.depth_data = self.make_depth_data()
        self.color_data = bytes(args.width * args.height * 3)
        self.cloud_points = self.make_cloud_points()

    def make_depth_data(self):
        data = array.array("H", [self.args.depth_mm] * (self.args.width * self.args.height))
        patch_half = self.args.patch_size // 2
        cx = self.args.width // 2
        cy = self.args.height // 2
        for y in range(cy - patch_half, cy + patch_half):
            if y < 0 or y >= self.args.height:
                continue
            for x in range(cx - patch_half, cx + patch_half):
                if 0 <= x < self.args.width:
                    data[y * self.args.width + x] = self.args.patch_depth_mm
        return data.tobytes()

    def make_depth_msg(self, stamp):
        msg = Image()
        msg.header.stamp = stamp
        msg.header.frame_id = "map"
        msg.height = self.args.height
        msg.width = self.args.width
        msg.encoding = "16UC1"
        msg.is_bigendian = False
        msg.step = self.args.width * 2
        msg.data = self.depth_data
        return msg

    def make_color_msg(self, stamp):
        msg = Image()
        msg.header.stamp = stamp
        msg.header.frame_id = "map"
        msg.height = self.args.height
        msg.width = self.args.width
        msg.encoding = "rgb8"
        msg.is_bigendian = False
        msg.step = self.args.width * 3
        msg.data = self.color_data
        return msg

    def make_pose_msg(self, stamp):
        msg = PoseStamped()
        msg.header.stamp = stamp
        msg.header.frame_id = "map"
        msg.pose.position.x = 0.0
        msg.pose.position.y = 0.0
        msg.pose.position.z = 1.0
        msg.pose.orientation.w = 1.0
        return msg

    def make_cloud_points(self):
        points = []
        count = max(1, self.args.cloud_side)
        spacing = self.args.cloud_spacing
        base = -0.5 * spacing * (count - 1)
        for ix in range(count):
            for iz in range(count):
                points.append((self.args.cloud_x, base + ix * spacing, 0.5 + iz * spacing))
        return points

    def make_cloud_msg(self, stamp):
        header = Header()
        header.stamp = stamp
        header.frame_id = "map"
        return point_cloud2.create_cloud_xyz32(header, self.cloud_points if hasattr(self, "cloud_points") else [(2.0, 0.0, 1.0)])

    def publish_once(self):
        stamp = self.get_clock().now().to_msg()
        depth = self.make_depth_msg(stamp)
        color = self.make_color_msg(stamp)
        pose = self.make_pose_msg(stamp)
        cloud = self.make_cloud_msg(stamp)

        self.map_depth_pub.publish(depth)
        self.map_cloud_pub.publish(cloud)
        self.map_pose_pub.publish(pose)

        self.detector_depth_pub.publish(depth)
        self.detector_color_pub.publish(color)
        self.detector_pose_pub.publish(pose)

        detections = Detection2DArray()
        detections.header.stamp = stamp
        detections.header.frame_id = "map"
        if self.args.yolo_box:
            detections.detections.append(self.make_yolo_detection())
        self.yolo_pub.publish(detections)

    def make_yolo_detection(self):
        detection = Detection2D()
        box_size = self.args.yolo_box_size or self.args.patch_size
        box_width = self.args.yolo_box_width or box_size
        box_height = self.args.yolo_box_height or box_size
        x0 = max(0.0, self.args.width * 0.5 - box_width * 0.5 + self.args.yolo_box_x_offset)
        y0 = max(0.0, self.args.height * 0.5 - box_height * 0.5 + self.args.yolo_box_y_offset)
        detection.bbox.center.position.x = float(min(x0, self.args.width - 1))
        detection.bbox.center.position.y = float(min(y0, self.args.height - 1))
        detection.bbox.size_x = float(min(box_width, self.args.width))
        detection.bbox.size_y = float(min(box_height, self.args.height))
        return detection


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--rate", type=float, default=10.0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--depth-mm", type=int, default=5000)
    parser.add_argument("--patch-depth-mm", type=int, default=2000)
    parser.add_argument("--patch-size", type=int, default=80)
    parser.add_argument("--cloud-x", type=float, default=2.0)
    parser.add_argument("--cloud-side", type=int, default=5)
    parser.add_argument("--cloud-spacing", type=float, default=0.2)
    parser.add_argument("--yolo-box", action="store_true", help="Publish one synthetic YOLO box aligned with the depth patch.")
    parser.add_argument("--yolo-box-size", type=float, default=0.0, help="Synthetic YOLO box size in pixels; defaults to patch size.")
    parser.add_argument("--yolo-box-width", type=float, default=0.0, help="Synthetic YOLO box width in pixels; overrides --yolo-box-size.")
    parser.add_argument("--yolo-box-height", type=float, default=0.0, help="Synthetic YOLO box height in pixels; overrides --yolo-box-size.")
    parser.add_argument("--yolo-box-x-offset", type=float, default=0.0, help="Pixel offset from the image-centered patch.")
    parser.add_argument("--yolo-box-y-offset", type=float, default=0.0, help="Pixel offset from the image-centered patch.")
    return parser.parse_args()


def main():
    args = parse_args()
    rclpy.init()
    node = SyntheticSensorPublisher(args)
    period = 1.0 / max(args.rate, 1e-6)
    end = time.monotonic() + args.duration
    try:
        while time.monotonic() < end:
            node.publish_once()
            rclpy.spin_once(node, timeout_sec=0.0)
            time.sleep(period)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
