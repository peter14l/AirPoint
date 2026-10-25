"""Hand tracking wrapper around MediaPipe Tasks HandLandmarker."""

from __future__ import annotations
import os
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple
import cv2
import numpy as np

import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

from airpoint.config import AppConfig, DominantHand
from airpoint.landmarks import (
    HandLandmarkData,
    Point3D,
    INDEX_TIP,
    MIDDLE_TIP,
    THUMB_TIP,
    WRIST,
)

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"

# Hand skeleton line connections for visual overlay
HAND_CONNECTIONS = [
    # Palm base & MCP arch
    (0, 1), (0, 5), (0, 17),
    (5, 9), (9, 13), (13, 17),
    # Thumb
    (1, 2), (2, 3), (3, 4),
    # Index
    (5, 6), (6, 7), (7, 8),
    # Middle
    (9, 10), (10, 11), (11, 12),
    # Ring
    (13, 14), (14, 15), (15, 16),
    # Pinky
    (17, 18), (18, 19), (19, 20),
]


class HandTracker:
    """
    Manages local MediaPipe HandLandmarker inference and landmark extraction.
    """

    def __init__(self, config: AppConfig, model_path: Optional[str] = None):
        self.config = config
        self.model_path = self._resolve_model_path(model_path)
        self._landmarker: Optional[vision.HandLandmarker] = None
        self._init_landmarker()

    def _resolve_model_path(self, custom_path: Optional[str]) -> str:
        """Locate the model file or download it automatically if not present."""
        candidates = [
            custom_path,
            str(Path(__file__).parent.parent.parent / "models" / "hand_landmarker.task"),
            "models/hand_landmarker.task",
            "hand_landmarker.task",
        ]

        for p in candidates:
            if p and os.path.isfile(p):
                return os.path.abspath(p)

        # Download if missing
        dest_dir = Path(__file__).parent.parent.parent / "models"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / "hand_landmarker.task"

        try:
            urllib.request.urlretrieve(MODEL_URL, str(dest_file))
            return str(dest_file.resolve())
        except Exception as e:
            raise RuntimeError(f"Failed to find or download MediaPipe model: {e}")

    def _init_landmarker(self) -> None:
        base_options = python.BaseOptions(model_asset_path=self.model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=2,
            min_hand_detection_confidence=self.config.safety.min_confidence,
            min_tracking_confidence=self.config.safety.min_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)

    def process_frame(self, bgr_frame: np.ndarray) -> Optional[HandLandmarkData]:
        """
        Runs inference on BGR OpenCV frame and returns primary tracked hand data.
        """
        if self._landmarker is None or bgr_frame is None:
            return None

        # Convert OpenCV BGR to RGB mp.Image
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        result = self._landmarker.detect(mp_image)
        if not result.hand_landmarks:
            return None

        # Determine target hand based on DominantHand preference
        target_idx = 0
        preferred = self.config.dominant_hand

        if len(result.hand_landmarks) > 1 and preferred != DominantHand.ANY:
            for idx, handedness_cats in enumerate(result.handedness):
                if handedness_cats:
                    detected_label = handedness_cats[0].category_name
                    if detected_label == preferred.value:
                        target_idx = idx
                        break

        raw_landmarks = result.hand_landmarks[target_idx]
        pts = [Point3D(x=lm.x, y=lm.y, z=lm.z) for lm in raw_landmarks]

        world_pts = None
        if result.hand_world_landmarks and len(result.hand_world_landmarks) > target_idx:
            world_pts = [Point3D(x=lm.x, y=lm.y, z=lm.z) for lm in result.hand_world_landmarks[target_idx]]

        confidence = 1.0
        label = "Right"
        if result.handedness and len(result.handedness) > target_idx and result.handedness[target_idx]:
            cat = result.handedness[target_idx][0]
            label = cat.category_name
            confidence = cat.score

        return HandLandmarkData(
            landmarks=pts,
            handedness=label,
            confidence=confidence,
            world_landmarks=world_pts
        )

    def draw_landmarks(
        self,
        frame: np.ndarray,
        hand_data: Optional[HandLandmarkData],
        pinch_dist: float = 1.0,
        is_pinched: bool = False,
        is_clutched: bool = False
    ) -> np.ndarray:
        """
        Draws visual feedback (skeleton, landmarks, palm center, pinch indicator)
        directly onto the frame.
        """
        if hand_data is None or frame is None:
            return frame

        h, w = frame.shape[:2]
        pts_2d = [(int(p.x * w), int(p.y * h)) for p in hand_data.landmarks]

        # Draw skeleton connections
        # Muted cyan/teal for normal, amber/orange if clutched
        line_color = (80, 80, 220) if is_clutched else (180, 160, 60)
        for start_idx, end_idx in HAND_CONNECTIONS:
            cv2.line(frame, pts_2d[start_idx], pts_2d[end_idx], line_color, 2, cv2.LINE_AA)

        # Draw joints
        for idx, (px, py) in enumerate(pts_2d):
            # Thumb tip and index tip highlighted
            if idx in (THUMB_TIP, INDEX_TIP):
                dot_color = (0, 220, 255) if is_pinched else (120, 240, 120)
                cv2.circle(frame, (px, py), 6, dot_color, -1, cv2.LINE_AA)
            elif idx == MIDDLE_TIP:
                cv2.circle(frame, (px, py), 5, (240, 180, 80), -1, cv2.LINE_AA)
            else:
                cv2.circle(frame, (px, py), 4, (200, 200, 200), -1, cv2.LINE_AA)

        # Draw stable palm center (green ring)
        palm = hand_data.get_palm_center()
        cx, cy = int(palm.x * w), int(palm.y * h)
        cv2.circle(frame, (cx, cy), 9, (40, 220, 120), 2, cv2.LINE_AA)
        cv2.circle(frame, (cx, cy), 3, (40, 220, 120), -1, cv2.LINE_AA)

        # Draw pinch line between thumb tip and index tip
        tx, ty = pts_2d[THUMB_TIP]
        ix, iy = pts_2d[INDEX_TIP]
        pinch_line_color = (0, 220, 255) if is_pinched else (100, 120, 100)
        cv2.line(frame, (tx, ty), (ix, iy), pinch_line_color, 2 if is_pinched else 1, cv2.LINE_AA)

        # Draw clutch badge if active
        if is_clutched:
            cv2.putText(
                frame,
                "CLUTCH ACTIVE (Paused)",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (0, 180, 255),
                2,
                cv2.LINE_AA
            )

        return frame

    def close(self) -> None:
        if self._landmarker:
            try:
                self._landmarker.close()
            except Exception:
                pass
            self._landmarker = None
