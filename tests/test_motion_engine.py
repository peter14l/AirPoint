"""Automated tests for MotionEngine deterministic logic."""

import pytest
from airpoint.config import AppConfig, CursorMode
from airpoint.landmarks import HandLandmarkData, Point3D
from airpoint.motion_engine import MotionEngine


def make_synthetic_hand(palm_x: float, palm_y: float, confidence: float = 0.95) -> HandLandmarkData:
    """Generate a synthetic 21-point hand landmark model centered at (palm_x, palm_y)."""
    # 21 points with wrist at (palm_x, palm_y + 0.1) and fingertips extended
    pts = [Point3D(palm_x, palm_y) for _ in range(21)]
    # Set wrist (0), Index MCP (5), Middle MCP (9), Pinky MCP (17)
    pts[0] = Point3D(palm_x, palm_y + 0.08)
    pts[5] = Point3D(palm_x - 0.03, palm_y - 0.03)
    pts[9] = Point3D(palm_x, palm_y - 0.04)
    pts[17] = Point3D(palm_x + 0.03, palm_y - 0.02)
    return HandLandmarkData(landmarks=pts, confidence=confidence)


def test_reacquisition_first_frame_zero_displacement():
    config = AppConfig()
    engine = MotionEngine(config, 1920, 1080)

    # First frame after reset
    hand1 = make_synthetic_hand(0.5, 0.5)
    out1 = engine.process(hand1)
    assert out1.dx == 0.0
    assert out1.dy == 0.0


def test_rightward_input_moves_cursor_right():
    config = AppConfig()
    # Direct 1.0 smoothing for instant test verification
    config.motion.smoothing = 1.0
    config.motion.dead_zone = 0.001
    config.motion.acceleration = 1.0
    engine = MotionEngine(config, 1920, 1080)

    # Frame 1: hand at x=0.5
    engine.process(make_synthetic_hand(0.5, 0.5))

    # User moves hand to their physical right.
    # In mirrored webcam, physical right = raw camera image x decreases (or mirrored x increases).
    # Moving hand to right in camera space (raw x goes from 0.5 to 0.46, so mirrored goes 0.5 -> 0.54):
    out2 = engine.process(make_synthetic_hand(0.46, 0.5))
    assert out2.dx > 0.0


def test_leftward_input_moves_cursor_left():
    config = AppConfig()
    config.motion.smoothing = 1.0
    config.motion.dead_zone = 0.001
    config.motion.acceleration = 1.0
    engine = MotionEngine(config, 1920, 1080)

    engine.process(make_synthetic_hand(0.5, 0.5))

    # User moves hand to their physical left (raw camera x increases from 0.5 to 0.54)
    out2 = engine.process(make_synthetic_hand(0.54, 0.5))
    assert out2.dx < 0.0


def test_upward_and_downward_movement_mapping():
    config = AppConfig()
    config.motion.smoothing = 1.0
    config.motion.dead_zone = 0.001
    config.motion.acceleration = 1.0
    engine = MotionEngine(config, 1920, 1080)

    engine.process(make_synthetic_hand(0.5, 0.5))

    # Hand moves UP (raw image Y decreases from 0.5 to 0.46)
    out_up = engine.process(make_synthetic_hand(0.5, 0.46))
    assert out_up.dy < 0.0  # In screen space, dy < 0 is upward

    engine.reset_reference()
    engine.process(make_synthetic_hand(0.5, 0.5))

    # Hand moves DOWN (raw image Y increases from 0.5 to 0.54)
    out_down = engine.process(make_synthetic_hand(0.5, 0.54))
    assert out_down.dy > 0.0  # In screen space, dy > 0 is downward


def test_dead_zone_suppresses_small_fluctuations():
    config = AppConfig()
    config.motion.dead_zone = 0.005  # 5 units dead zone
    engine = MotionEngine(config, 1920, 1080)

    engine.process(make_synthetic_hand(0.5, 0.5))

    # Micro-tremor (0.001 change, well within 0.005 dead zone)
    out = engine.process(make_synthetic_hand(0.501, 0.501))
    assert out.dx == 0.0
    assert out.dy == 0.0


def test_clutch_suppresses_all_cursor_movement():
    config = AppConfig()
    engine = MotionEngine(config, 1920, 1080)

    engine.process(make_synthetic_hand(0.5, 0.5))
    engine.set_clutched(True)

    # Big hand movement while clutched
    out = engine.process(make_synthetic_hand(0.40, 0.40))
    assert out.dx == 0.0
    assert out.dy == 0.0
    assert not out.is_active

    # Releasing clutch should rebase without jump
    engine.set_clutched(False)
    out_after = engine.process(make_synthetic_hand(0.40, 0.40))
    assert out_after.dx == 0.0
    assert out_after.dy == 0.0


def test_cursor_movement_is_bounded():
    config = AppConfig()
    config.motion.max_step_pixels = 50.0  # max clamp
    config.motion.smoothing = 1.0
    engine = MotionEngine(config, 1920, 1080)

    engine.process(make_synthetic_hand(0.5, 0.5))

    # Massive glitch jump across entire camera frame
    out = engine.process(make_synthetic_hand(0.1, 0.1))
    step = (out.dx ** 2 + out.dy ** 2) ** 0.5
    assert step <= 50.01  # Clamped to max_step_pixels


def test_tracking_loss_resets_reference_safely():
    config = AppConfig()
    engine = MotionEngine(config, 1920, 1080)

    engine.process(make_synthetic_hand(0.5, 0.5))

    # Tracking lost
    out_lost = engine.process(None)
    assert not out_lost.is_active

    # Hand reappears at completely different position (0.2, 0.8)
    out_reappear = engine.process(make_synthetic_hand(0.2, 0.8))
    # Must NOT cause huge teleport jump
    assert out_reappear.dx == 0.0
    assert out_reappear.dy == 0.0
