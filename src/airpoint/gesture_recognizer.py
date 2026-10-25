"""Gesture recognition: pinch left-click, right-click, dragging, and clutch detection."""

from __future__ import annotations
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from airpoint.config import AppConfig, ClutchGesture
from airpoint.landmarks import HandLandmarkData, INDEX_TIP, MIDDLE_TIP


class GestureAction(str, Enum):
    NONE = "none"
    LEFT_CLICK = "left_click"
    RIGHT_CLICK = "right_click"
    LEFT_DOWN = "left_down"
    LEFT_UP = "left_up"


@dataclass
class GestureResult:
    action: GestureAction = GestureAction.NONE
    is_left_pinched: bool = False
    is_right_pinched: bool = False
    is_clutched: bool = False
    is_dragging: bool = False
    pinch_distance: float = 1.0
    right_pinch_distance: float = 1.0


class GestureRecognizer:
    """
    Stateful detector for pinch clicks, drag-and-drop, and clutch gestures.
    Implements hysteresis and cooldown timers to prevent click bouncing.
    """

    def __init__(self, config: AppConfig):
        self.config = config

        self._left_pinched: bool = False
        self._right_pinched: bool = False
        self._pinch_start_time: float = 0.0
        self._is_dragging: bool = False
        self._last_left_click_time: float = 0.0
        self._last_right_click_time: float = 0.0
        self._is_clutched: bool = False

    def reset(self) -> None:
        """Reset gesture states (e.g. on tracking loss)."""
        self._left_pinched = False
        self._right_pinched = False
        self._is_dragging = False
        self._pinch_start_time = 0.0
        self._is_clutched = False

    def process(
        self,
        hand_data: Optional[HandLandmarkData],
        current_time: Optional[float] = None
    ) -> GestureResult:
        if current_time is None:
            current_time = time.monotonic()

        # If no hand or low confidence, reset and return
        if hand_data is None or hand_data.confidence < self.config.safety.min_confidence:
            was_dragging = self._is_dragging
            self.reset()
            if was_dragging:
                # Release held button on tracking loss
                return GestureResult(action=GestureAction.LEFT_UP)
            return GestureResult()

        # 1. Detect Clutch Gesture
        clutch_mode = self.config.gestures.clutch_gesture
        is_clutch_active = False

        if clutch_mode == ClutchGesture.CLOSED_FIST:
            is_clutch_active = hand_data.is_fist()
        elif clutch_mode == ClutchGesture.PINKY_FOLD:
            is_clutch_active = hand_data.is_pinky_folded()

        self._is_clutched = is_clutch_active

        # While clutched, suppress all click actions and release any ongoing drag
        if is_clutch_active:
            was_dragging = self._is_dragging
            self._left_pinched = False
            self._right_pinched = False
            self._is_dragging = False
            if was_dragging:
                return GestureResult(
                    action=GestureAction.LEFT_UP,
                    is_clutched=True
                )
            return GestureResult(is_clutched=True)

        # 2. Compute normalized pinch distances
        left_dist = hand_data.get_normalized_pinch_distance(INDEX_TIP)
        right_dist = hand_data.get_normalized_pinch_distance(MIDDLE_TIP)

        action = GestureAction.NONE
        cfg = self.config.gestures

        # 3. Process Left Click & Drag (Thumb + Index)
        if not self._left_pinched:
            # Check activation threshold
            if left_dist <= cfg.pinch_threshold:
                self._left_pinched = True
                self._pinch_start_time = current_time

                # Check cooldown to prevent accidental rapid repeat
                if (current_time - self._last_left_click_time) >= cfg.click_cooldown_sec:
                    action = GestureAction.LEFT_CLICK
                    self._last_left_click_time = current_time
        else:
            # Currently in pinched state
            # Check for drag hold transition
            if cfg.enable_drag and not self._is_dragging:
                if (current_time - self._pinch_start_time) >= cfg.drag_hold_sec:
                    self._is_dragging = True
                    action = GestureAction.LEFT_DOWN

            # Check hysteresis release threshold
            if left_dist >= cfg.pinch_release_threshold:
                self._left_pinched = False
                if self._is_dragging:
                    self._is_dragging = False
                    action = GestureAction.LEFT_UP

        # 4. Process Right Click (Thumb + Middle), only if not currently left-pinching
        if cfg.enable_right_click and not self._left_pinched and not self._is_dragging:
            if not self._right_pinched:
                if right_dist <= cfg.right_pinch_threshold:
                    self._right_pinched = True
                    if (current_time - self._last_right_click_time) >= cfg.click_cooldown_sec:
                        action = GestureAction.RIGHT_CLICK
                        self._last_right_click_time = current_time
            else:
                if right_dist >= cfg.right_release_threshold:
                    self._right_pinched = False

        return GestureResult(
            action=action,
            is_left_pinched=self._left_pinched,
            is_right_pinched=self._right_pinched,
            is_clutched=self._is_clutched,
            is_dragging=self._is_dragging,
            pinch_distance=left_dist,
            right_pinch_distance=right_dist
        )
