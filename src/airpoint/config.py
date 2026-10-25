"""Configuration management for AirPoint."""

from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict


class CursorMode(str, Enum):
    RELATIVE = "relative"
    ABSOLUTE = "absolute"


class DominantHand(str, Enum):
    RIGHT = "Right"
    LEFT = "Left"
    ANY = "Any"


class ClutchGesture(str, Enum):
    CLOSED_FIST = "Closed Fist"
    PINKY_FOLD = "Pinky Fold"
    KEYBOARD_ONLY = "Keyboard Only"


@dataclass
class MotionConfig:
    sensitivity: float = 2.2           # Multiplier for incremental motion (Relative) or gain (Absolute)
    smoothing: float = 0.55            # EMA alpha: 0.1 (heavy smoothing) - 0.9 (raw)
    dead_zone: float = 0.0018          # Movement below this normalized distance is zeroed
    acceleration: float = 1.35         # Non-linear speed exponent: 1.0 = linear, >1.0 = faster cursor on fast flick
    max_step_pixels: float = 85.0      # Safety clamp to prevent sudden cursor jumps
    invert_x: bool = False             # Invert X axis (mirrored webcam already compensates physical right)
    invert_y: bool = False             # Invert Y axis


@dataclass
class GestureConfig:
    pinch_threshold: float = 0.048          # Normalized distance (thumb tip to index tip) for click trigger
    pinch_release_threshold: float = 0.075  # Hysteresis release distance
    right_pinch_threshold: float = 0.052    # Normalized distance (thumb tip to middle tip)
    right_release_threshold: float = 0.078
    click_cooldown_sec: float = 0.22        # Minimum interval between clicks
    drag_hold_sec: float = 0.35             # Hold pinch longer than this to engage drag-and-drop
    enable_drag: bool = True
    enable_right_click: bool = True
    clutch_gesture: ClutchGesture = ClutchGesture.CLOSED_FIST


@dataclass
class CameraConfig:
    device_index: int = 0
    width: int = 640
    height: int = 480
    target_fps: int = 30
    backend: str = "MSMF"              # MSMF (Windows Media Foundation) supports camera sharing with browsers


@dataclass
class CalibrationConfig:
    # Normalized camera space bounds for Absolute mode
    abs_x_min: float = 0.15
    abs_y_min: float = 0.15
    abs_x_max: float = 0.85
    abs_y_max: float = 0.85
    edge_margin: float = 0.05


@dataclass
class SafetyConfig:
    min_confidence: float = 0.55       # Minimum tracking confidence
    tracking_loss_timeout_sec: float = 0.18 # Release buttons if hand lost for this long
    emergency_shortcut: str = "F8"


@dataclass
class AppConfig:
    cursor_mode: CursorMode = CursorMode.RELATIVE
    dominant_hand: DominantHand = DominantHand.RIGHT
    motion: MotionConfig = field(default_factory=MotionConfig)
    gestures: GestureConfig = field(default_factory=GestureConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    launch_at_login: bool = False

    def validate(self) -> None:
        """Validate config parameters to keep values within safe bounds."""
        self.motion.sensitivity = max(0.1, min(10.0, float(self.motion.sensitivity)))
        self.motion.smoothing = max(0.05, min(0.99, float(self.motion.smoothing)))
        self.motion.dead_zone = max(0.0, min(0.05, float(self.motion.dead_zone)))
        self.motion.acceleration = max(1.0, min(2.5, float(self.motion.acceleration)))
        self.motion.max_step_pixels = max(10.0, min(500.0, float(self.motion.max_step_pixels)))

        self.gestures.pinch_threshold = max(0.01, min(0.15, float(self.gestures.pinch_threshold)))
        self.gestures.pinch_release_threshold = max(
            self.gestures.pinch_threshold + 0.01, min(0.25, float(self.gestures.pinch_release_threshold))
        )
        self.gestures.click_cooldown_sec = max(0.05, min(1.0, float(self.gestures.click_cooldown_sec)))
        self.safety.min_confidence = max(0.2, min(0.95, float(self.safety.min_confidence)))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AppConfig:
        config = cls()
        if not data:
            return config

        if "cursor_mode" in data:
            config.cursor_mode = CursorMode(data["cursor_mode"])
        if "dominant_hand" in data:
            config.dominant_hand = DominantHand(data["dominant_hand"])
        if "launch_at_login" in data:
            config.launch_at_login = bool(data["launch_at_login"])

        if "motion" in data and isinstance(data["motion"], dict):
            for k, v in data["motion"].items():
                if hasattr(config.motion, k):
                    setattr(config.motion, k, v)

        if "gestures" in data and isinstance(data["gestures"], dict):
            for k, v in data["gestures"].items():
                if k == "clutch_gesture":
                    setattr(config.gestures, k, ClutchGesture(v))
                elif hasattr(config.gestures, k):
                    setattr(config.gestures, k, v)

        if "camera" in data and isinstance(data["camera"], dict):
            for k, v in data["camera"].items():
                if hasattr(config.camera, k):
                    setattr(config.camera, k, v)

        if "calibration" in data and isinstance(data["calibration"], dict):
            for k, v in data["calibration"].items():
                if hasattr(config.calibration, k):
                    setattr(config.calibration, k, v)

        if "safety" in data and isinstance(data["safety"], dict):
            for k, v in data["safety"].items():
                if hasattr(config.safety, k):
                    setattr(config.safety, k, v)

        config.validate()
        return config

    def save(self, path: Path | str | None = None) -> None:
        if path is None:
            config_dir = Path.home() / ".airpoint"
            config_dir.mkdir(parents=True, exist_ok=True)
            path = config_dir / "config.json"
        else:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path | str | None = None) -> AppConfig:
        if path is None:
            path = Path.home() / ".airpoint" / "config.json"
        else:
            path = Path(path)

        if not path.exists():
            default_config = cls()
            default_config.validate()
            return default_config

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except Exception:
            return cls()
