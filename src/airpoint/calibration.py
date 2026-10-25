"""Calibration helpers for Absolute and Relative cursor modes."""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple
from airpoint.config import AppConfig, CalibrationConfig
from airpoint.landmarks import Point3D


@dataclass
class CalibrationSample:
    palm_x: float
    palm_y: float
    timestamp: float


class CalibrationManager:
    """
    Manages interactive calibration routines for Absolute and Relative modes.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._samples: List[CalibrationSample] = []
        self._is_calibrating: bool = False

    def start_sampling(self) -> None:
        self._samples.clear()
        self._is_calibrating = True

    def add_sample(self, palm_center: Point3D, timestamp: float) -> None:
        if self._is_calibrating:
            self._samples.append(CalibrationSample(palm_center.x, palm_center.y, timestamp))

    def stop_sampling(self) -> None:
        self._is_calibrating = False

    def compute_absolute_bounds(self) -> Tuple[float, float, float, float]:
        """
        Calculates usable camera bounding box (min_x, min_y, max_x, max_y)
        from collected motion samples.
        """
        if len(self._samples) < 10:
            return 0.15, 0.15, 0.85, 0.85

        xs = [s.palm_x for s in self._samples]
        ys = [s.palm_y for s in self._samples]

        # Use 5th and 95th percentiles to reject outliers
        xs.sort()
        ys.sort()
        n = len(xs)
        p5_idx = int(0.05 * n)
        p95_idx = int(0.95 * n)

        x_min = max(0.02, min(0.4, xs[p5_idx]))
        x_max = min(0.98, max(0.6, xs[p95_idx]))
        y_min = max(0.02, min(0.4, ys[p5_idx]))
        y_max = min(0.98, max(0.6, ys[p95_idx]))

        self.config.calibration.abs_x_min = x_min
        self.config.calibration.abs_y_min = y_min
        self.config.calibration.abs_x_max = x_max
        self.config.calibration.abs_y_max = y_max

        return x_min, y_min, x_max, y_max

    def recenter_around_point(self, palm_center: Point3D) -> None:
        """
        Re-centers the absolute window around current hand position.
        """
        cal = self.config.calibration
        span_x = (cal.abs_x_max - cal.abs_x_min) / 2.0
        span_y = (cal.abs_y_max - cal.abs_y_min) / 2.0

        cal.abs_x_min = max(0.0, palm_center.x - span_x)
        cal.abs_x_max = min(1.0, palm_center.x + span_x)
        cal.abs_y_min = max(0.0, palm_center.y - span_y)
        cal.abs_y_max = min(1.0, palm_center.y + span_y)

    def compute_relative_sensitivity(self) -> float:
        """
        Computes suggested relative sensitivity from velocity samples.
        """
        if len(self._samples) < 15:
            return 2.2

        speeds = []
        for i in range(1, len(self._samples)):
            dt = self._samples[i].timestamp - self._samples[i - 1].timestamp
            if dt > 0.001:
                dx = self._samples[i].palm_x - self._samples[i - 1].palm_x
                dy = self._samples[i].palm_y - self._samples[i - 1].palm_y
                dist = (dx**2 + dy**2)**0.5
                speeds.append(dist / dt)

        if not speeds:
            return 2.2

        median_speed = sorted(speeds)[len(speeds) // 2]
        # Map median speed to a comfortable 1.5 - 3.5 sensitivity range
        if median_speed <= 0.01:
            return 2.2
        suggested = max(1.2, min(3.8, 0.45 / median_speed))
        self.config.motion.sensitivity = round(suggested, 2)
        return self.config.motion.sensitivity
