"""Landmark representations, palm reference extraction, and geometric utilities."""

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple


# MediaPipe Hand Landmark Indices
WRIST = 0
THUMB_CMC = 1
THUMB_MCP = 2
THUMB_IP = 3
THUMB_TIP = 4

INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8

MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_DIP = 11
MIDDLE_TIP = 12

RING_MCP = 13
RING_PIP = 14
RING_DIP = 15
RING_TIP = 16

PINKY_MCP = 17
PINKY_PIP = 18
PINKY_DIP = 19
PINKY_TIP = 20

PALM_LANDMARKS = [WRIST, INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP]


@dataclass
class Point3D:
    x: float
    y: float
    z: float = 0.0

    def distance_to(self, other: Point3D) -> float:
        return math.sqrt(
            (self.x - other.x) ** 2 +
            (self.y - other.y) ** 2 +
            (self.z - other.z) ** 2
        )

    def distance_2d(self, other: Point3D) -> float:
        return math.sqrt((self.x - other.x) ** 2 + (self.y - other.y) ** 2)


@dataclass
class HandLandmarkData:
    landmarks: List[Point3D]
    handedness: str = "Right"
    confidence: float = 1.0
    world_landmarks: Optional[List[Point3D]] = None
    timestamp_ms: float = 0.0

    def __post_init__(self):
        if len(self.landmarks) < 21:
            raise ValueError(f"HandLandmarkData expects 21 landmarks, got {len(self.landmarks)}")

    def get_palm_center(self) -> Point3D:
        """
        Calculate a stable palm reference point from multiple landmarks.
        Uses Wrist (0), Index MCP (5), Middle MCP (9), and Pinky MCP (17).
        This eliminates jitter from individual finger movement.
        """
        pts = [self.landmarks[i] for i in [WRIST, INDEX_MCP, MIDDLE_MCP, PINKY_MCP]]
        avg_x = sum(p.x for p in pts) / len(pts)
        avg_y = sum(p.y for p in pts) / len(pts)
        avg_z = sum(p.z for p in pts) / len(pts)
        return Point3D(x=avg_x, y=avg_y, z=avg_z)

    def get_hand_scale(self) -> float:
        """
        Returns a distance measure representing hand size in the camera frame.
        Uses distance between Wrist (0) and Middle MCP (9).
        Guaranteed > 0.001 to prevent division by zero.
        """
        wrist = self.landmarks[WRIST]
        middle_mcp = self.landmarks[MIDDLE_MCP]
        scale = wrist.distance_2d(middle_mcp)
        return max(scale, 0.001)

    def get_normalized_pinch_distance(self, tip_index: int = INDEX_TIP) -> float:
        """
        Calculates distance between thumb tip (4) and specified fingertip,
        normalized by hand scale so pinch detection is distance-invariant.
        """
        thumb_tip = self.landmarks[THUMB_TIP]
        finger_tip = self.landmarks[tip_index]
        raw_dist = thumb_tip.distance_2d(finger_tip)
        scale = self.get_hand_scale()
        return raw_dist / scale

    def is_fist(self) -> bool:
        """
        Returns True if all four fingers (index, middle, ring, pinky) are folded inward.
        A finger is folded if its tip is closer to the wrist than its PIP joint.
        """
        wrist = self.landmarks[WRIST]
        fingers = [
            (INDEX_TIP, INDEX_PIP),
            (MIDDLE_TIP, MIDDLE_PIP),
            (RING_TIP, RING_PIP),
            (PINKY_TIP, PINKY_PIP),
        ]
        folded_count = 0
        for tip_idx, pip_idx in fingers:
            tip_dist = self.landmarks[tip_idx].distance_2d(wrist)
            pip_dist = self.landmarks[pip_idx].distance_2d(wrist)
            if tip_dist < pip_dist * 0.95:
                folded_count += 1
        return folded_count >= 3

    def is_pinky_folded(self) -> bool:
        """
        Returns True if the pinky is folded while other fingers are extended.
        """
        wrist = self.landmarks[WRIST]
        pinky_tip = self.landmarks[PINKY_TIP]
        pinky_pip = self.landmarks[PINKY_PIP]
        pinky_folded = pinky_tip.distance_2d(wrist) < pinky_pip.distance_2d(wrist)

        # Check that index and middle are NOT folded
        index_open = self.landmarks[INDEX_TIP].distance_2d(wrist) > self.landmarks[INDEX_PIP].distance_2d(wrist)
        middle_open = self.landmarks[MIDDLE_TIP].distance_2d(wrist) > self.landmarks[MIDDLE_PIP].distance_2d(wrist)

        return pinky_folded and index_open and middle_open
