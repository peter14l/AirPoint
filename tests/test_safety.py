"""Automated tests for SafetyMonitor and CursorController guarantees."""

import pytest
from airpoint.config import AppConfig
from airpoint.cursor_controller import CursorController
from airpoint.motion_engine import MotionEngine
from airpoint.safety import SafetyMonitor


def test_safety_releases_buttons_on_tracking_loss():
    config = AppConfig()
    config.safety.tracking_loss_timeout_sec = 0.15  # 150ms timeout

    cursor = CursorController(mock_mode=True)
    engine = MotionEngine(config, 1920, 1080)
    safety = SafetyMonitor(config, cursor, engine)

    # Simulate mouse down (dragging)
    cursor.left_down()
    assert cursor.is_left_down

    # Update hand seen at t=1.0
    safety.update_hand_seen(1.0)

    # Check watchdog at t=1.05 (hand active)
    active = safety.check_watchdog(1.05)
    assert active
    assert cursor.is_left_down

    # Check watchdog at t=1.20 (50ms past timeout)
    active = safety.check_watchdog(1.20)
    assert not active
    # Must have released held button!
    assert not cursor.is_left_down
    assert "left_up" in cursor.event_log


def test_emergency_stop_halts_and_releases():
    config = AppConfig()
    cursor = CursorController(mock_mode=True)
    engine = MotionEngine(config, 1920, 1080)
    safety = SafetyMonitor(config, cursor, engine)

    cursor.left_down()
    safety.trigger_emergency_stop()

    assert safety.is_emergency_stopped
    assert not cursor.is_left_down
    assert not safety.check_watchdog(1.0)


def test_shutdown_guarantees_button_release():
    config = AppConfig()
    cursor = CursorController(mock_mode=True)
    engine = MotionEngine(config, 1920, 1080)
    safety = SafetyMonitor(config, cursor, engine)

    cursor.left_down()
    safety.shutdown()

    assert not cursor.is_left_down
