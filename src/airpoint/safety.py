"""Safety monitor, watchdog for tracking loss, and emergency stop."""

from __future__ import annotations
import time
from typing import Optional
from airpoint.config import AppConfig
from airpoint.cursor_controller import CursorController
from airpoint.motion_engine import MotionEngine


class SafetyMonitor:
    """
    Watches tracking status, releases stuck mouse buttons on tracking loss,
    and handles emergency stops.
    """

    def __init__(self, config: AppConfig, cursor: CursorController, motion_engine: MotionEngine):
        self.config = config
        self.cursor = cursor
        self.motion_engine = motion_engine

        self._last_valid_time: float = 0.0
        self._emergency_stopped: bool = False
        self._tracking_lost: bool = True

    @property
    def is_emergency_stopped(self) -> bool:
        return self._emergency_stopped

    def trigger_emergency_stop(self) -> None:
        """Immediately halts all cursor actions and releases buttons."""
        self._emergency_stopped = True
        self.cursor.release_all_buttons()
        self.motion_engine.reset_reference()

    def reset_emergency_stop(self) -> None:
        self._emergency_stopped = False
        self.motion_engine.reset_reference()

    def update_hand_seen(self, current_time: Optional[float] = None) -> None:
        if current_time is None:
            current_time = time.monotonic()
        self._last_valid_time = current_time
        self._tracking_lost = False

    def check_watchdog(self, current_time: Optional[float] = None) -> bool:
        """
        Check for tracking timeout. If tracking is lost, releases buttons
        and resets motion engine reference to prevent jumps.
        Returns True if tracking is currently valid, False if timed out.
        """
        if self._emergency_stopped:
            self.cursor.release_all_buttons()
            return False

        if current_time is None:
            current_time = time.monotonic()

        timeout = self.config.safety.tracking_loss_timeout_sec
        time_since_hand = current_time - self._last_valid_time

        if time_since_hand > timeout:
            if not self._tracking_lost:
                self._tracking_lost = True
                self.cursor.release_all_buttons()
                self.motion_engine.reset_reference()
            return False

        return True

    def shutdown(self) -> None:
        """Clean shutdown safety guarantee."""
        self.cursor.release_all_buttons()
        self.motion_engine.reset_reference()
