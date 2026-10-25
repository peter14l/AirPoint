"""Comprehensive end-to-end verification script for AirPoint.

Verifies:
1. Real Windows cursor movement via user32 (GetCursorPos, SetCursorPos, move_relative)
2. Directional correctness: moving hand right moves cursor right; moving left moves cursor left; moving up moves cursor up; moving down moves cursor down.
3. Zero accumulated drift under resting hand / micro-jitter.
4. Smooth reacquisition: no cursor jumps when hand tracking is lost and regained.
5. Accidental click prevention & hysteresis.
6. Emergency Stop & Tracking Watchdog: immediate suspension and button release.
"""

import sys
import time
from airpoint.config import AppConfig, CursorMode
from airpoint.cursor_controller import CursorController
from airpoint.gesture_recognizer import GestureAction, GestureRecognizer
from airpoint.landmarks import HandLandmarkData, Point3D, WRIST, INDEX_TIP, THUMB_TIP, MIDDLE_MCP, INDEX_PIP, MIDDLE_PIP, RING_PIP, PINKY_PIP, RING_TIP, PINKY_TIP
from airpoint.motion_engine import MotionEngine
from airpoint.safety import SafetyMonitor


def make_hand(palm_x: float, palm_y: float, pinch_dist: float = 0.20, confidence: float = 0.95) -> HandLandmarkData:
    pts = [Point3D(palm_x, palm_y) for _ in range(21)]
    # Wrist and middle MCP define palm scale (0.2)
    pts[WRIST] = Point3D(palm_x, palm_y + 0.1)
    pts[MIDDLE_MCP] = Point3D(palm_x, palm_y - 0.1)
    # Thumb tip and Index tip
    pts[THUMB_TIP] = Point3D(palm_x - 0.02, palm_y - 0.05)
    # distance = pinch_dist * hand_scale (0.2)
    pts[INDEX_TIP] = Point3D(palm_x - 0.02 + (pinch_dist * 0.2), palm_y - 0.05)

    pts[INDEX_PIP] = Point3D(palm_x - 0.02, palm_y - 0.01)
    pts[MIDDLE_PIP] = Point3D(palm_x, palm_y - 0.01)
    pts[RING_PIP] = Point3D(palm_x + 0.02, palm_y - 0.01)
    pts[PINKY_PIP] = Point3D(palm_x + 0.04, palm_y - 0.01)

    pts[RING_TIP] = Point3D(palm_x + 0.02, palm_y - 0.06)
    pts[PINKY_TIP] = Point3D(palm_x + 0.04, palm_y - 0.06)

    return HandLandmarkData(landmarks=pts, confidence=confidence)


def run_verification():
    print("=" * 60)
    print("AIRPOINT REAL END-TO-END VERIFICATION")
    print("=" * 60)

    # 1. Real Windows Cursor Control Verification
    print("\n[1/6] Testing Windows Cursor Controller (real OS User32 API)...")
    real_cursor = CursorController(mock_mode=False)
    screen_w, screen_h = real_cursor.get_screen_size()
    print(f"  -> Detected Windows Screen Size: {screen_w}x{screen_h}")

    initial_x, initial_y = real_cursor.get_position()
    print(f"  -> Initial Windows Cursor Pos: ({initial_x}, {initial_y})")

    # Move cursor by small known delta (+25, +15)
    real_cursor.move_relative(25, 15)
    time.sleep(0.02)
    moved_x, moved_y = real_cursor.get_position()
    print(f"  -> After move_relative(+25, +15): ({moved_x}, {moved_y})")

    # Verify displacement matches expectation
    expected_x = max(0, min(screen_w - 1, initial_x + 25))
    expected_y = max(0, min(screen_h - 1, initial_y + 15))
    assert abs(moved_x - expected_x) <= 1, f"Expected X {expected_x}, got {moved_x}"
    assert abs(moved_y - expected_y) <= 1, f"Expected Y {expected_y}, got {moved_y}"
    print("  -> PASS: Actual Windows cursor moved accurately.")

    # Return cursor to initial position
    real_cursor.move_to(initial_x, initial_y)
    print("  -> Restored initial cursor position.")

    # 2. Hand Displacement Direction Verification
    print("\n[2/6] Verifying Hand Displacement -> Cursor Directional Mapping...")
    config = AppConfig()
    config.motion.smoothing = 1.0 # bypass filter for deterministic check
    config.motion.dead_zone = 0.0005
    config.motion.acceleration = 1.0
    engine = MotionEngine(config, screen_w, screen_h)

    # Initialize reference at (0.5, 0.5)
    engine.process(make_hand(0.5, 0.5))

    # User moves physical hand to their RIGHT:
    # Camera is mirrored for intuitive selfie view -> raw camera X decreases (0.5 -> 0.46)
    out_right = engine.process(make_hand(0.46, 0.5))
    print(f"  -> Hand physical RIGHT -> dx: {out_right.dx:.2f}, dy: {out_right.dy:.2f}")
    assert out_right.dx > 0, "Hand moving right MUST produce dx > 0!"
    print("  -> PASS: Moving hand right moves cursor right.")

    # User moves physical hand to their LEFT:
    out_left = engine.process(make_hand(0.50, 0.5))
    print(f"  -> Hand physical LEFT  -> dx: {out_left.dx:.2f}, dy: {out_left.dy:.2f}")
    assert out_left.dx < 0, "Hand moving left MUST produce dx < 0!"
    print("  -> PASS: Moving hand left moves cursor left.")

    # User moves physical hand UP:
    out_up = engine.process(make_hand(0.50, 0.46))
    print(f"  -> Hand physical UP    -> dx: {out_up.dx:.2f}, dy: {out_up.dy:.2f}")
    assert out_up.dy < 0, "Hand moving up MUST produce dy < 0 (toward top of screen)!"
    print("  -> PASS: Moving hand up moves cursor up.")

    # User moves physical hand DOWN:
    out_down = engine.process(make_hand(0.50, 0.54))
    print(f"  -> Hand physical DOWN  -> dx: {out_down.dx:.2f}, dy: {out_down.dy:.2f}")
    assert out_down.dy > 0, "Hand moving down MUST produce dy > 0 (toward bottom of screen)!"
    print("  -> PASS: Moving hand down moves cursor down.")

    # 3. Accumulated Drift Check (Stationary Hand under Micro-Tremor)
    print("\n[3/6] Testing Accumulated Cursor Drift (60 frames of stationary hand)...")
    config.motion.smoothing = 0.55
    config.motion.dead_zone = 0.002
    engine = MotionEngine(config, screen_w, screen_h)
    engine.process(make_hand(0.5, 0.5))

    total_drift_dx = 0.0
    total_drift_dy = 0.0
    # Simulate 60 frames with realistic sensor noise within deadzone (±0.0008)
    import math
    for i in range(60):
        noise_x = 0.0007 * math.sin(i * 0.4)
        noise_y = 0.0006 * math.cos(i * 0.3)
        out = engine.process(make_hand(0.5 + noise_x, 0.5 + noise_y))
        total_drift_dx += abs(out.dx)
        total_drift_dy += abs(out.dy)

    print(f"  -> Total accumulated drift over 60 frames: dx={total_drift_dx:.4f} px, dy={total_drift_dy:.4f} px")
    assert total_drift_dx == 0.0 and total_drift_dy == 0.0, "Dead-zone must eliminate all stationary drift!"
    print("  -> PASS: Zero accumulated cursor drift detected.")

    # 4. Reacquisition & Jump Prevention Check
    print("\n[4/6] Testing Reacquisition Jump Prevention (Hand loss -> Reappearance)...")
    engine = MotionEngine(config, screen_w, screen_h)
    engine.process(make_hand(0.5, 0.5))
    engine.process(make_hand(0.48, 0.48)) # active movement

    # Hand leaves frame for 15 frames
    for _ in range(15):
        out_lost = engine.process(None)
        assert not out_lost.is_active

    # Hand abruptly re-enters camera frame at completely different coordinates (0.15, 0.85)
    out_reacquire = engine.process(make_hand(0.15, 0.85))
    print(f"  -> Displacement on reacquisition frame: dx={out_reacquire.dx:.2f}, dy={out_reacquire.dy:.2f}")
    assert out_reacquire.dx == 0.0 and out_reacquire.dy == 0.0, "Reacquisition frame must have ZERO displacement!"
    print("  -> PASS: No cursor teleport jump on reacquisition.")

    # 5. Gesture Hysteresis & Accidental Click Prevention
    print("\n[5/6] Testing Gesture Hysteresis & Accidental Click Prevention...")
    config = AppConfig()
    recognizer = GestureRecognizer(config)

    # Open hand -> no click
    res = recognizer.process(make_hand(0.5, 0.5, pinch_dist=0.25), current_time=1.0)
    assert res.action == GestureAction.NONE

    # Moving fingers around without touching -> no click
    res = recognizer.process(make_hand(0.5, 0.5, pinch_dist=0.10), current_time=1.05)
    assert res.action == GestureAction.NONE

    # Intentional pinch (pinch_dist = 0.03 <= 0.048) -> triggers single click
    res_click = recognizer.process(make_hand(0.5, 0.5, pinch_dist=0.03), current_time=1.10)
    assert res_click.action == GestureAction.LEFT_CLICK
    print("  -> Primary Click triggered cleanly on pinch transition.")

    # Held pinch for next 5 frames -> must NOT trigger repeated clicks
    for i in range(5):
        res_held = recognizer.process(make_hand(0.5, 0.5, pinch_dist=0.03), current_time=1.12 + (i * 0.02))
        assert res_held.action == GestureAction.NONE
    print("  -> Continuously held pinch suppressed repeated clicks.")

    # Release requires hysteresis (pinch_dist >= 0.075)
    res_half = recognizer.process(make_hand(0.5, 0.5, pinch_dist=0.06), current_time=1.25)
    assert res_half.is_left_pinched, "Pinch should remain held between 0.048 and 0.075 due to hysteresis!"

    res_open = recognizer.process(make_hand(0.5, 0.5, pinch_dist=0.09), current_time=1.30)
    assert not res_open.is_left_pinched
    print("  -> PASS: Hysteresis and debouncing operate accurately.")

    # 6. Emergency Stop & Watchdog Verification
    print("\n[6/6] Testing Emergency Stop & Tracking Watchdog Safety...")
    mock_cursor = CursorController(mock_mode=True)
    safety = SafetyMonitor(config, mock_cursor, engine)

    # Simulate mouse dragged down
    mock_cursor.left_down()
    assert mock_cursor.is_left_down

    # Trigger emergency stop
    safety.trigger_emergency_stop()
    assert safety.is_emergency_stopped
    assert not mock_cursor.is_left_down, "Emergency stop must immediately release held mouse button!"
    print("  -> Emergency stop safely released mouse buttons.")

    safety.reset_emergency_stop()
    mock_cursor.left_down()
    safety.update_hand_seen(1.0)
    # Advance time beyond watchdog timeout (180ms)
    watchdog_ok = safety.check_watchdog(1.25)
    assert not watchdog_ok
    assert not mock_cursor.is_left_down, "Watchdog timeout must release stuck buttons!"
    print("  -> PASS: Watchdog releases stuck buttons immediately upon tracking loss.")

    print("\n" + "=" * 60)
    print("ALL REAL END-TO-END VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_verification()
