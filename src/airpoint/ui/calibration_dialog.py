"""Calibration dialog and wizard for Absolute pointing and Relative sensitivity."""

from __future__ import annotations
import time
from typing import Optional
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from airpoint.calibration import CalibrationManager
from airpoint.config import AppConfig
from airpoint.landmarks import Point3D


class CalibrationDialog(QDialog):
    """
    Step-by-step calibration assistant.
    """

    calibration_completed = Signal()

    def __init__(self, config: AppConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        self.cal_manager = CalibrationManager(config)

        self.setWindowTitle("AirPoint Calibration Assistant")
        self.setFixedSize(540, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #0C0F14;
                color: #E2E8F0;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel {
                color: #CBD5E1;
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #21262D;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
                color: #94A3B8;
            }
            QPushButton#actionBtn {
                background-color: #10B981;
                color: #0C0F14;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton#actionBtn:hover {
                background-color: #34D399;
            }
            QPushButton#secondaryBtn {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton#secondaryBtn:hover {
                background-color: #334155;
            }
            QProgressBar {
                border: 1px solid #21262D;
                border-radius: 4px;
                text-align: center;
                background-color: #161B22;
                color: #F8FAFC;
                height: 14px;
            }
            QProgressBar::chunk {
                background-color: #10B981;
                border-radius: 3px;
            }
        """)

        self._countdown = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title & instructions
        title = QLabel("Interactive Hand Calibration")
        title.setStyleSheet("font-size: 17px; font-weight: bold; color: #F8FAFC;")
        layout.addWidget(title)

        desc = QLabel(
            "Calibrate your webcam tracking zone for comfortable cursor reach. "
            "You can recenter your hand, tune relative sensitivity, or configure direct absolute bounds."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 1. Recenter Section
        recenter_group = QGroupBox("Fast Recenter")
        rec_layout = QVBoxLayout(recenter_group)
        rec_lbl = QLabel("Hold your hand in your most natural, resting position in front of the camera, then click Recenter.")
        rec_lbl.setWordWrap(True)
        rec_layout.addWidget(rec_lbl)

        self.recenter_btn = QPushButton("Recenter Hand Anchor")
        self.recenter_btn.setObjectName("actionBtn")
        self.recenter_btn.clicked.connect(self._on_recenter_clicked)
        rec_layout.addWidget(self.recenter_btn)
        layout.addWidget(recenter_group)

        # 2. Sensitivity Auto-Tuner
        sens_group = QGroupBox("Relative Sensitivity Auto-Tuner")
        sens_layout = QVBoxLayout(sens_group)
        self.sens_status_lbl = QLabel("Click 'Start Measurement' and wave your hand comfortably left/right and up/down for 3 seconds.")
        self.sens_status_lbl.setWordWrap(True)
        sens_layout.addWidget(self.sens_status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        sens_layout.addWidget(self.progress_bar)

        self.start_sens_btn = QPushButton("Start 3s Velocity Measurement")
        self.start_sens_btn.setObjectName("secondaryBtn")
        self.start_sens_btn.clicked.connect(self._on_start_measurement)
        sens_layout.addWidget(self.start_sens_btn)
        layout.addWidget(sens_group)

        # Bottom buttons
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        done_btn = QPushButton("Done / Close")
        done_btn.setObjectName("actionBtn")
        done_btn.clicked.connect(self.accept)
        btn_box.addWidget(done_btn)
        layout.addLayout(btn_box)

    def feed_hand_point(self, palm_center: Optional[Point3D]) -> None:
        """Called by main window when a frame is processed during calibration."""
        if palm_center is not None and self.cal_manager._is_calibrating:
            self.cal_manager.add_sample(palm_center, time.monotonic())

    def _on_recenter_clicked(self) -> None:
        # Recenter absolute camera bounding box around center (0.5, 0.5)
        self.cal_manager.recenter_around_point(Point3D(0.5, 0.5))
        self.recenter_btn.setText("✓ Anchor Re-centered!")
        QTimer.singleShot(1500, lambda: self.recenter_btn.setText("Recenter Hand Anchor"))
        self.calibration_completed.emit()

    def _on_start_measurement(self) -> None:
        self._countdown = 30  # 30 ticks * 100ms = 3.0s
        self.progress_bar.setValue(0)
        self.cal_manager.start_sampling()
        self.start_sens_btn.setEnabled(False)
        self.sens_status_lbl.setText("Wave your hand naturally across your desk area...")
        self._timer.start(100)

    def _on_timer_tick(self) -> None:
        self._countdown -= 1
        pct = int(((30 - self._countdown) / 30.0) * 100)
        self.progress_bar.setValue(pct)

        if self._countdown <= 0:
            self._timer.stop()
            self.cal_manager.stop_sampling()
            suggested = self.cal_manager.compute_relative_sensitivity()
            self.sens_status_lbl.setText(f"✓ Measurement complete! Suggested sensitivity set to: {suggested:.1f}x")
            self.start_sens_btn.setEnabled(True)
            self.start_sens_btn.setText("Measure Again")
            self.calibration_completed.emit()
