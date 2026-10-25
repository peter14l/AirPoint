"""Automated tests for calibration logic and configuration validation."""

import pytest
from airpoint.calibration import CalibrationManager
from airpoint.config import AppConfig
from airpoint.landmarks import Point3D


def test_absolute_bounds_calculation():
    config = AppConfig()
    manager = CalibrationManager(config)
    manager.start_sampling()

    # Feed samples covering [0.2, 0.8] in X and [0.2, 0.7] in Y
    for i in range(50):
        t = i * 0.03
        norm_val = i / 50.0
        x = 0.2 + 0.6 * norm_val
        y = 0.2 + 0.5 * norm_val
        manager.add_sample(Point3D(x, y), t)

    manager.stop_sampling()
    x_min, y_min, x_max, y_max = manager.compute_absolute_bounds()

    assert x_min < x_max
    assert y_min < y_max
    assert config.calibration.abs_x_min == x_min
    assert config.calibration.abs_x_max == x_max


def test_recenter_around_point():
    config = AppConfig()
    config.calibration.abs_x_min = 0.1
    config.calibration.abs_x_max = 0.7  # span = 0.6, half_span = 0.3
    config.calibration.abs_y_min = 0.1
    config.calibration.abs_y_max = 0.5  # span = 0.4, half_span = 0.2

    manager = CalibrationManager(config)
    manager.recenter_around_point(Point3D(0.5, 0.5))

    assert pytest.approx(config.calibration.abs_x_min, 0.01) == 0.2
    assert pytest.approx(config.calibration.abs_x_max, 0.01) == 0.8
    assert pytest.approx(config.calibration.abs_y_min, 0.01) == 0.3
    assert pytest.approx(config.calibration.abs_y_max, 0.01) == 0.7


def test_config_validation():
    config = AppConfig()
    # Provide extreme / invalid values
    config.motion.sensitivity = 999.0
    config.motion.smoothing = -5.0
    config.gestures.pinch_threshold = 0.99
    config.safety.min_confidence = 0.01

    config.validate()

    assert config.motion.sensitivity <= 10.0
    assert config.motion.smoothing >= 0.05
    assert config.gestures.pinch_threshold <= 0.15
    assert config.safety.min_confidence >= 0.2
