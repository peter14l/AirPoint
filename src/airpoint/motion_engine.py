"""Motion processing engine for relative and absolute cursor control."""

from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Optional, Tuple
from airpoint.config import AppConfig, CursorMode
from airpoint.landmarks import HandLandmarkData, Point3D


@dataclass
class MotionOutput:
    mode: CursorMode
    dx: float = 0.0                 # Relative delta in screen pixels
    dy: float = 0.0
    abs_x: Optional[float] = None   # Absolute screen X coordinate
    abs_y: Optional[float] = None   # Absolute screen Y coordinate
    is_active: bool = False         # False if clutching, lost, or deadzoned
    confidence: float = 0.0


class MotionEngine:
    """
    Processes hand landmark observations into smooth, responsive cursor movements.
    Supports both Relative Mode (primary) and Absolute Mode.
    """

    def __init__(self, config: AppConfig, screen_width: int = 1920, screen_height: int = 1080):
        self.config = config
        self.screen_width = screen_width
        self.screen_height = screen_height

        # State tracking
        self._last_ref_pos: Optional[Point3D] = None
        self._smoothed_dx: float = 0.0
        self._smoothed_dy: float = 0.0
        self._smoothed_abs_x: Optional[float] = None
        self._smoothed_abs_y: Optional[float] = None

        self._is_clutched: bool = False
        self._is_tracking: bool = False

    def update_screen_size(self, width: int, height: int) -> None:
        self.screen_width = max(1, width)
        self.screen_height = max(1, height)

    def set_clutched(self, clutched: bool) -> None:
        """
        Clutch temporarily suspends cursor movement.
        When releasing clutch, reference must be rebased to prevent cursor jump.
        """
        if self._is_clutched != clutched:
            self._is_clutched = clutched
            if not clutched:
                # Rebase reference so next frame starts fresh
                self.reset_reference()

    @property
    def is_clutched(self) -> bool:
        return self._is_clutched

    def reset_reference(self) -> None:
        """Reset motion reference point and smoothing state."""
        self._last_ref_pos = None
        self._smoothed_dx = 0.0
        self._smoothed_dy = 0.0
        self._smoothed_abs_x = None
        self._smoothed_abs_y = None
        self._is_tracking = False

    def process(
        self,
        hand_data: Optional[HandLandmarkData],
        clutch_override: bool = False
    ) -> MotionOutput:
        """
        Main processing pipeline step.
        """
        is_clutch_active = self._is_clutched or clutch_override

        # 1. Validate presence and confidence
        if hand_data is None:
            self.reset_reference()
            return MotionOutput(mode=self.config.cursor_mode, is_active=False)

        confidence = hand_data.confidence
        if confidence < self.config.safety.min_confidence:
            self.reset_reference()
            return MotionOutput(
                mode=self.config.cursor_mode,
                is_active=False,
                confidence=confidence
            )

        # 2. Extract stable palm reference point
        palm_center = hand_data.get_palm_center()

        # Camera coordinate normalization:
        # Standard webcam is mirrored for intuitive interaction (physical right -> image right)
        # Palm coords in [0, 1]
        x_norm = 1.0 - palm_center.x  # Mirror X for intuitive control
        y_norm = palm_center.y

        if self.config.motion.invert_x:
            x_norm = 1.0 - x_norm
        if self.config.motion.invert_y:
            y_norm = 1.0 - y_norm

        curr_pos = Point3D(x=x_norm, y=y_norm, z=palm_center.z)

        # If clutch is active, keep tracking reference updated but do not output motion
        if is_clutch_active:
            self._last_ref_pos = curr_pos
            self._smoothed_dx = 0.0
            self._smoothed_dy = 0.0
            return MotionOutput(
                mode=self.config.cursor_mode,
                is_active=False,
                confidence=confidence
            )

        # Route by mode
        if self.config.cursor_mode == CursorMode.ABSOLUTE:
            return self._process_absolute(curr_pos, confidence)
        else:
            return self._process_relative(curr_pos, confidence)

    def _process_relative(self, curr_pos: Point3D, confidence: float) -> MotionOutput:
        """
        Process relative incremental movement.
        """
        # First frame after reacquisition or reset: establish reference without moving cursor
        if self._last_ref_pos is None:
            self._last_ref_pos = curr_pos
            self._smoothed_dx = 0.0
            self._smoothed_dy = 0.0
            self._is_tracking = True
            return MotionOutput(
                mode=CursorMode.RELATIVE,
                dx=0.0,
                dy=0.0,
                is_active=True,
                confidence=confidence
            )

        # 4. Calculate incremental displacement from last frame
        dx_norm = curr_pos.x - self._last_ref_pos.x
        dy_norm = curr_pos.y - self._last_ref_pos.y
        self._last_ref_pos = curr_pos

        # Convert to screen pixel space base delta
        base_dx = dx_norm * self.screen_width * self.config.motion.sensitivity
        base_dy = dy_norm * self.screen_height * self.config.motion.sensitivity

        # 6. Apply Dead-Zone filtering in normalized space
        delta_mag_norm = math.hypot(dx_norm, dy_norm)
        dead_zone = self.config.motion.dead_zone

        if delta_mag_norm <= dead_zone:
            # Stationary hand: zero motion and decay smoothed deltas rapidly
            self._smoothed_dx *= 0.3
            self._smoothed_dy *= 0.3
            if abs(self._smoothed_dx) < 0.1:
                self._smoothed_dx = 0.0
            if abs(self._smoothed_dy) < 0.1:
                self._smoothed_dy = 0.0
            return MotionOutput(
                mode=CursorMode.RELATIVE,
                dx=0.0,
                dy=0.0,
                is_active=True,
                confidence=confidence
            )

        # Continuous dead-zone ramp: subtract dead_zone to eliminate jump at boundary
        ramp_factor = (delta_mag_norm - dead_zone) / delta_mag_norm
        active_dx = base_dx * ramp_factor
        active_dy = base_dy * ramp_factor

        # 8. Non-linear acceleration based on speed
        # Fast hand movements cover wider screen distances, slow movements allow pixel precision
        speed = math.hypot(dx_norm, dy_norm)
        accel_exponent = self.config.motion.acceleration
        if accel_exponent > 1.0:
            # Baseline reference speed for 1.0x acceleration is 0.005 norm/frame
            speed_ratio = max(0.2, min(5.0, speed / 0.005))
            accel_mult = math.pow(speed_ratio, accel_exponent - 1.0)
            active_dx *= accel_mult
            active_dy *= accel_mult

        # 7. Smoothing (Low-pass filter / EMA)
        # alpha close to 1.0 = raw/instant, lower = heavier smoothing
        alpha = self.config.motion.smoothing
        self._smoothed_dx = alpha * active_dx + (1.0 - alpha) * self._smoothed_dx
        self._smoothed_dy = alpha * active_dy + (1.0 - alpha) * self._smoothed_dy

        # 9. Clamp extreme per-frame step to prevent cursor teleporting
        step_mag = math.hypot(self._smoothed_dx, self._smoothed_dy)
        max_step = self.config.motion.max_step_pixels
        final_dx = self._smoothed_dx
        final_dy = self._smoothed_dy

        if step_mag > max_step:
            clamp_scale = max_step / step_mag
            final_dx *= clamp_scale
            final_dy *= clamp_scale

        return MotionOutput(
            mode=CursorMode.RELATIVE,
            dx=final_dx,
            dy=final_dy,
            is_active=True,
            confidence=confidence
        )

    def _process_absolute(self, curr_pos: Point3D, confidence: float) -> MotionOutput:
        """
        Process absolute screen mapping with margin calibration and jitter filter.
        """
        calib = self.config.calibration
        x_span = max(0.01, calib.abs_x_max - calib.abs_x_min)
        y_span = max(0.01, calib.abs_y_max - calib.abs_y_min)

        # Map to [0, 1] within calibrated window
        norm_x = (curr_pos.x - calib.abs_x_min) / x_span
        norm_y = (curr_pos.y - calib.abs_y_min) / y_span

        # Edge margins to make corners reachable
        margin = calib.edge_margin
        norm_x = (norm_x - margin) / max(0.01, (1.0 - 2.0 * margin))
        norm_y = (norm_y - margin) / max(0.01, (1.0 - 2.0 * margin))

        # Clamp to [0, 1]
        clamped_x = max(0.0, min(1.0, norm_x))
        clamped_y = max(0.0, min(1.0, norm_y))

        target_x = clamped_x * (self.screen_width - 1)
        target_y = clamped_y * (self.screen_height - 1)

        # Smooth absolute coordinate
        alpha = self.config.motion.smoothing
        if self._smoothed_abs_x is None or self._smoothed_abs_y is None:
            self._smoothed_abs_x = target_x
            self._smoothed_abs_y = target_y
        else:
            self._smoothed_abs_x = alpha * target_x + (1.0 - alpha) * self._smoothed_abs_x
            self._smoothed_abs_y = alpha * target_y + (1.0 - alpha) * self._smoothed_abs_y

        return MotionOutput(
            mode=CursorMode.ABSOLUTE,
            abs_x=self._smoothed_abs_x,
            abs_y=self._smoothed_abs_y,
            is_active=True,
            confidence=confidence
        )
