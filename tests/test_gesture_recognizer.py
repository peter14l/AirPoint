"""Automated tests for GestureRecognizer logic."""

import pytest
from airpoint.config import AppConfig, ClutchGesture
from airpoint.gesture_recognizer import GestureAction, GestureRecognizer
from airpoint.landmarks import (
    HandLandmarkData,
    Point3D,
    INDEX_TIP,
    MIDDLE_TIP,
    THUMB_TIP,
    WRIST,
    INDEX_PIP,
    MIDDLE_PIP,
    RING_PIP,
    PINKY_PIP,
    RING_TIP,
    PINKY_TIP,
    MIDDLE_MCP,
)


def make_hand_with_pinch(pinch_distance: float, right_pinch_distance: float = 0.2, confidence: float = 0.95) -> HandLandmarkData:
    """Create synthetic hand with controlled pinch distance."""
    pts = [Point3D(0.5, 0.5) for _ in range(21)]
    # Set wrist at (0.5, 0.7) and middle MCP at (0.5, 0.5) => hand_scale = 0.2
    pts[WRIST] = Point3D(0.5, 0.7)
    pts[MIDDLE_MCP] = Point3D(0.5, 0.5)

    # Hand scale is 0.2. To get desired normalized pinch_distance,
    # raw distance between THUMB_TIP and INDEX_TIP should be pinch_distance * 0.2
    pts[THUMB_TIP] = Point3D(0.5, 0.4)
    raw_left = pinch_distance * 0.2
    pts[INDEX_TIP] = Point3D(0.5 + raw_left, 0.4)

    raw_right = right_pinch_distance * 0.2
    pts[MIDDLE_TIP] = Point3D(0.5 + raw_right, 0.4)

    # Extended fingers (tips further from wrist than PIPs)
    pts[INDEX_PIP] = Point3D(0.52, 0.48)
    pts[MIDDLE_PIP] = Point3D(0.52, 0.48)
    pts[RING_PIP] = Point3D(0.52, 0.48)
    pts[PINKY_PIP] = Point3D(0.52, 0.48)
    pts[RING_TIP] = Point3D(0.55, 0.35)
    pts[PINKY_TIP] = Point3D(0.58, 0.35)

    return HandLandmarkData(landmarks=pts, confidence=confidence)


def test_pinch_produces_single_left_click():
    config = AppConfig()
    config.gestures.pinch_threshold = 0.05
    config.gestures.pinch_release_threshold = 0.08
    config.gestures.click_cooldown_sec = 0.2
    recognizer = GestureRecognizer(config)

    # 1. Hand open (dist = 0.15)
    res1 = recognizer.process(make_hand_with_pinch(0.15), current_time=1.0)
    assert res1.action == GestureAction.NONE
    assert not res1.is_left_pinched

    # 2. Hand pinches (dist = 0.03 <= 0.05)
    res2 = recognizer.process(make_hand_with_pinch(0.03), current_time=1.05)
    assert res2.action == GestureAction.LEFT_CLICK
    assert res2.is_left_pinched

    # 3. Hand remains pinched (held)
    res3 = recognizer.process(make_hand_with_pinch(0.03), current_time=1.10)
    # Must NOT produce another click while continuously held
    assert res3.action == GestureAction.NONE
    assert res3.is_left_pinched


def test_held_pinch_transitions_to_drag():
    config = AppConfig()
    config.gestures.pinch_threshold = 0.05
    config.gestures.drag_hold_sec = 0.3
    recognizer = GestureRecognizer(config)

    # Initial pinch at t=1.0
    recognizer.process(make_hand_with_pinch(0.03), current_time=1.0)

    # Held for 0.35s (exceeds 0.3s drag_hold_sec)
    res_drag = recognizer.process(make_hand_with_pinch(0.03), current_time=1.35)
    assert res_drag.action == GestureAction.LEFT_DOWN
    assert res_drag.is_dragging

    # Release pinch (dist = 0.10)
    res_release = recognizer.process(make_hand_with_pinch(0.10), current_time=1.40)
    assert res_release.action == GestureAction.LEFT_UP
    assert not res_release.is_dragging


def test_low_confidence_prevents_clicks():
    config = AppConfig()
    config.safety.min_confidence = 0.70
    recognizer = GestureRecognizer(config)

    # Pinch with low confidence (0.4 < 0.7)
    hand = make_hand_with_pinch(0.02, confidence=0.40)
    res = recognizer.process(hand, current_time=1.0)
    assert res.action == GestureAction.NONE
    assert not res.is_left_pinched


def test_right_click_gesture():
    config = AppConfig()
    config.gestures.right_pinch_threshold = 0.05
    config.gestures.right_release_threshold = 0.08
    recognizer = GestureRecognizer(config)

    # Left is open (0.15), Right is pinched (0.03)
    res = recognizer.process(make_hand_with_pinch(0.15, right_pinch_distance=0.03), current_time=1.0)
    assert res.action == GestureAction.RIGHT_CLICK
    assert res.is_right_pinched
