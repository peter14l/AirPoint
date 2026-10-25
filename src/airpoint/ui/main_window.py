"""Main application window for AirPoint."""

from __future__ import annotations
import time
from typing import Optional
import numpy as np

from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from airpoint.camera import CameraManager
from airpoint.config import AppConfig, CursorMode
from airpoint.cursor_controller import CursorController
from airpoint.gesture_recognizer import GestureAction, GestureRecognizer, GestureResult
from airpoint.hand_tracker import HandTracker
from airpoint.landmarks import HandLandmarkData, Point3D
from airpoint.motion_engine import MotionEngine, MotionOutput
from airpoint.safety import SafetyMonitor
from airpoint.ui.calibration_dialog import CalibrationDialog
from airpoint.ui.preview_widget import CameraPreviewWidget
from airpoint.ui.settings_panel import SettingsPanel


class TrackingWorker(QThread):
    """
    Dedicated background worker thread for camera capture, landmark detection,
    motion processing, gesture recognition, and OS cursor output.
    Ensures cursor control is never interrupted by GUI repaints.
    """

    frame_processed = Signal(object, object, object, float, float) # frame, hand_data, gesture_res, fps, latency_ms
    error_occurred = Signal(str)
    emergency_stopped = Signal()

    def __init__(self, config: AppConfig, cursor: CursorController, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config
        self.cursor = cursor
        self._running = False

        self.camera_manager: Optional[CameraManager] = None
        self.hand_tracker: Optional[HandTracker] = None
        self.motion_engine: Optional[MotionEngine] = None
        self.gesture_recognizer: Optional[GestureRecognizer] = None
        self.safety_monitor: Optional[SafetyMonitor] = None

        self._clutch_hotkey_active: bool = False

    def set_clutch_hotkey(self, active: bool) -> None:
        self._clutch_hotkey_active = active

    def stop_worker(self) -> None:
        self._running = False
        if self.safety_monitor:
            self.safety_monitor.shutdown()
        if self.camera_manager:
            self.camera_manager.stop()
        if self.hand_tracker:
            self.hand_tracker.close()

    def run(self) -> None:
        try:
            # Initialize core processing subsystems
            w, h = self.cursor.get_screen_size()
            self.motion_engine = MotionEngine(self.config, screen_width=w, screen_height=h)
            self.gesture_recognizer = GestureRecognizer(self.config)
            self.safety_monitor = SafetyMonitor(self.config, self.cursor, self.motion_engine)
            self.camera_manager = CameraManager(self.config.camera)
            self.hand_tracker = HandTracker(self.config)

            if not self.camera_manager.start():
                self.error_occurred.emit(self.camera_manager.last_error)
                return

            self._running = True

            while self._running:
                loop_start = time.monotonic()

                # 1. Fetch freshest camera frame
                frame, timestamp = self.camera_manager.get_latest_frame()
                if frame is None:
                    time.sleep(0.005)
                    continue

                # 2. Run local MediaPipe Hand Landmark inference
                hand_data = self.hand_tracker.process_frame(frame)

                now = time.monotonic()
                is_hand_valid = hand_data is not None and hand_data.confidence >= self.config.safety.min_confidence

                if is_hand_valid:
                    self.safety_monitor.update_hand_seen(now)
                else:
                    self.safety_monitor.check_watchdog(now)

                # 3. Gesture Recognition
                gesture_res = self.gesture_recognizer.process(
                    hand_data if is_hand_valid else None,
                    current_time=now
                )

                # Combined clutch state (gesture or keyboard shortcut)
                is_clutched = gesture_res.is_clutched or self._clutch_hotkey_active
                self.motion_engine.set_clutched(is_clutched)

                # 4. Motion Engine Processing
                motion_out = self.motion_engine.process(
                    hand_data if is_hand_valid else None,
                    clutch_override=is_clutched
                )

                # 5. OS Cursor Dispatch (only when tracking is healthy and not clutched)
                if (
                    not self.safety_monitor.is_emergency_stopped
                    and not is_clutched
                    and is_hand_valid
                ):
                    # Handle Relative Mode
                    if motion_out.mode == CursorMode.RELATIVE and motion_out.is_active:
                        self.cursor.move_relative(motion_out.dx, motion_out.dy)
                    # Handle Absolute Mode
                    elif motion_out.mode == CursorMode.ABSOLUTE and motion_out.abs_x is not None:
                        self.cursor.move_to(motion_out.abs_x, motion_out.abs_y)

                    # Handle Click & Drag gestures
                    if gesture_res.action == GestureAction.LEFT_CLICK:
                        self.cursor.left_click()
                    elif gesture_res.action == GestureAction.RIGHT_CLICK:
                        self.cursor.right_click()
                    elif gesture_res.action == GestureAction.LEFT_DOWN:
                        self.cursor.left_down()
                    elif gesture_res.action == GestureAction.LEFT_UP:
                        self.cursor.left_up()

                # 6. Draw visual overlays on frame for preview
                annotated_frame = self.hand_tracker.draw_landmarks(
                    frame,
                    hand_data if is_hand_valid else None,
                    pinch_dist=gesture_res.pinch_distance,
                    is_pinched=gesture_res.is_left_pinched,
                    is_clutched=is_clutched,
                )

                latency_ms = (time.monotonic() - loop_start) * 1000.0
                fps = self.camera_manager.fps

                self.frame_processed.emit(
                    annotated_frame,
                    hand_data,
                    gesture_res,
                    fps,
                    latency_ms
                )

                # Small sleep to prevent busy spin if camera FPS is lower than inference speed
                time.sleep(0.002)

        except Exception as e:
            self.error_occurred.emit(f"Tracking thread error: {e}")
        finally:
            if self.safety_monitor:
                self.safety_monitor.shutdown()
            if self.camera_manager:
                self.camera_manager.stop()
            if self.hand_tracker:
                self.hand_tracker.close()


class MainWindow(QMainWindow):
    """
    Main AirPoint desktop interface.
    """

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.cursor = CursorController(mock_mode=False)

        self.setWindowTitle("AirPoint - 3D Air Mouse")
        self.resize(1140, 720)
        self.setMinimumSize(960, 600)

        self.worker: Optional[TrackingWorker] = None
        self._is_tracking: bool = False
        self._is_keyboard_clutch: bool = False

        self._apply_dark_theme()
        self._init_ui()
        self._setup_shortcuts()

    def _apply_dark_theme(self) -> None:
        """Restrained, modern dark theme adhering to project design guidelines."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #0C0F14;
                color: #E2E8F0;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            }
            QWidget {
                color: #E2E8F0;
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            }
            QTabWidget::pane {
                border: 1px solid #21262D;
                background-color: #12161F;
                border-radius: 8px;
            }
            QTabBar::tab {
                background: #161B22;
                color: #94A3B8;
                padding: 10px 22px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 4px;
                font-weight: 600;
                font-size: 13px;
            }
            QTabBar::tab:selected {
                background: #12161F;
                color: #10B981;
                border-bottom: 2px solid #10B981;
            }
            QGroupBox {
                border: 1px solid #21262D;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 14px;
                background-color: #161B22;
                font-weight: 600;
                color: #94A3B8;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                color: #E2E8F0;
            }
            QPushButton#primaryToggleBtn {
                background-color: #10B981;
                color: #0C0F14;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton#primaryToggleBtn:hover {
                background-color: #34D399;
            }
            QPushButton#stopBtn {
                background-color: #EF4444;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                padding: 12px 20px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton#stopBtn:hover {
                background-color: #F87171;
            }
            QPushButton#actionBtn {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton#actionBtn:hover {
                background-color: #334155;
            }
            QComboBox {
                background-color: #1C2333;
                border: 1px solid #30363D;
                border-radius: 6px;
                padding: 6px 12px;
                color: #F8FAFC;
                font-size: 13px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #21262D;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #10B981;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #F8FAFC;
                border: 1px solid #10B981;
                width: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }
            QCheckBox {
                color: #E2E8F0;
                font-size: 13px;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #30363D;
                background: #161B22;
            }
            QCheckBox::indicator:checked {
                background: #10B981;
                border-color: #10B981;
            }
            QStatusBar {
                background-color: #0A0D12;
                border-top: 1px solid #21262D;
                color: #64748B;
                font-size: 12px;
            }
        """)

    def _init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(14)

        # 1. Top Header Bar
        header = QHBoxLayout()
        header.setSpacing(12)

        title_col = QVBoxLayout()
        app_title = QLabel("AirPoint")
        app_title.setStyleSheet("font-size: 22px; font-weight: 800; color: #F8FAFC; letter-spacing: 0.5px;")
        sub_title = QLabel("Webcam-Based 3D Air Mouse")
        sub_title.setStyleSheet("font-size: 12px; color: #64748B;")
        title_col.addWidget(app_title)
        title_col.addWidget(sub_title)
        header.addLayout(title_col)

        header.addStretch()

        # Telemetry Badges
        self.fps_badge = QLabel("FPS: --")
        self.fps_badge.setStyleSheet("background: #161B22; border: 1px solid #21262D; border-radius: 6px; padding: 6px 12px; color: #94A3B8; font-weight: 600;")
        self.latency_badge = QLabel("Latency: -- ms")
        self.latency_badge.setStyleSheet("background: #161B22; border: 1px solid #21262D; border-radius: 6px; padding: 6px 12px; color: #94A3B8; font-weight: 600;")

        self.status_badge = QLabel("● IDLE")
        self.status_badge.setStyleSheet("background: #1C2333; border: 1px solid #30363D; border-radius: 6px; padding: 6px 14px; color: #64748B; font-weight: bold;")

        header.addWidget(self.fps_badge)
        header.addWidget(self.latency_badge)
        header.addWidget(self.status_badge)

        # Emergency Stop Button
        self.emergency_btn = QPushButton("Emergency Stop (F8)")
        self.emergency_btn.setObjectName("stopBtn")
        self.emergency_btn.clicked.connect(self._on_emergency_stop)
        header.addWidget(self.emergency_btn)

        root_layout.addLayout(header)

        # 2. Main Content Split (Left: Camera Preview, Right: Tabbed Controls)
        content_split = QHBoxLayout()
        content_split.setSpacing(16)

        # Left Column: Video Preview & Quick Controls
        left_col = QVBoxLayout()
        left_col.setSpacing(12)

        self.preview_widget = CameraPreviewWidget(self)
        left_col.addWidget(self.preview_widget, 1)

        # Quick Control Bar under preview
        quick_bar = QHBoxLayout()
        self.toggle_track_btn = QPushButton("▶ Start Tracking")
        self.toggle_track_btn.setObjectName("primaryToggleBtn")
        self.toggle_track_btn.clicked.connect(self._toggle_tracking)

        self.mode_toggle_btn = QPushButton("Mode: Relative Air-Mouse")
        self.mode_toggle_btn.setObjectName("actionBtn")
        self.mode_toggle_btn.clicked.connect(self._toggle_cursor_mode)

        self.camera_combo = QComboBox()
        self._populate_cameras()
        self.camera_combo.currentIndexChanged.connect(self._on_camera_selected)

        quick_bar.addWidget(self.toggle_track_btn, 2)
        quick_bar.addWidget(self.mode_toggle_btn, 1)
        quick_bar.addWidget(self.camera_combo, 1)
        left_col.addLayout(quick_bar)

        # Gesture status readout row
        gesture_bar = QHBoxLayout()
        gesture_bar.setSpacing(10)

        self.left_click_ind = QLabel("Left Click: Ready")
        self.left_click_ind.setStyleSheet("background: #161B22; border-radius: 6px; padding: 6px; color: #94A3B8; font-size: 12px; text-align: center;")
        self.right_click_ind = QLabel("Right Click: Ready")
        self.right_click_ind.setStyleSheet("background: #161B22; border-radius: 6px; padding: 6px; color: #94A3B8; font-size: 12px;")
        self.clutch_ind = QLabel("Clutch: Inactive")
        self.clutch_ind.setStyleSheet("background: #161B22; border-radius: 6px; padding: 6px; color: #94A3B8; font-size: 12px;")

        gesture_bar.addWidget(self.left_click_ind)
        gesture_bar.addWidget(self.right_click_ind)
        gesture_bar.addWidget(self.clutch_ind)
        left_col.addLayout(gesture_bar)

        content_split.addLayout(left_col, 3)

        # Right Column: Tabbed Settings & Calibration
        right_col = QVBoxLayout()
        self.tabs = QTabWidget()

        # Tab 1: Dashboard Overview & Quick Guide
        dash_widget = QWidget()
        dash_layout = QVBoxLayout(dash_widget)
        dash_layout.setSpacing(12)

        guide_box = QGroupBox("Quick Control Guide")
        guide_layout = QVBoxLayout(guide_box)
        guide_layout.setSpacing(8)

        guide_items = [
            ("Cursor Movement", "Move hand freely in camera view. Real-time displacement moves cursor smoothly."),
            ("Left Click", "Pinch thumb and index fingertip together once. Release to click."),
            ("Drag & Drop", "Hold pinch for > 350ms to grab and drag items. Release to drop."),
            ("Right Click", "Pinch thumb and middle fingertip together."),
            ("Clutch (Pause)", "Close fist or press SPACEBAR to suspend cursor while repositioning hand."),
            ("Shared Camera", "MSMF enabled: works concurrently while web browser/Meet is running!"),
            ("Emergency Stop", "Press F8 or red Stop button at any time to freeze cursor safely."),
        ]
        for title, detail in guide_items:
            row = QHBoxLayout()
            t_lbl = QLabel(f"• <b>{title}:</b>")
            t_lbl.setFixedWidth(130)
            t_lbl.setStyleSheet("color: #10B981;")
            d_lbl = QLabel(detail)
            d_lbl.setWordWrap(True)
            d_lbl.setStyleSheet("color: #CBD5E1; font-size: 12px;")
            row.addWidget(t_lbl)
            row.addWidget(d_lbl, 1)
            guide_layout.addLayout(row)

        dash_layout.addWidget(guide_box)

        # Calibration button on dashboard
        calib_quick_btn = QPushButton("Open Guided Calibration Wizard")
        calib_quick_btn.setObjectName("actionBtn")
        calib_quick_btn.clicked.connect(self._open_calibration)
        dash_layout.addWidget(calib_quick_btn)
        dash_layout.addStretch()

        self.tabs.addTab(dash_widget, "Dashboard")

        # Tab 2: Settings Panel
        self.settings_panel = SettingsPanel(self.config, self)
        self.settings_panel.settings_changed.connect(self._on_settings_modified)
        self.tabs.addTab(self.settings_panel, "Settings")

        right_col.addWidget(self.tabs)
        content_split.addLayout(right_col, 2)

        root_layout.addLayout(content_split, 1)

        # Status Bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("AirPoint ready. Select camera and click 'Start Tracking'. Spacebar = Clutch toggle | F8 = Emergency Stop.")

    def _setup_shortcuts(self) -> None:
        """Global key shortcuts within application window."""
        # F8 Emergency Stop
        self.f8_shortcut = QShortcut(QKeySequence("F8"), self)
        self.f8_shortcut.activated.connect(self._on_emergency_stop)

        # Spacebar Clutch toggle
        self.space_shortcut = QShortcut(QKeySequence("Space"), self)
        self.space_shortcut.activated.connect(self._toggle_keyboard_clutch)

        # Escape key pause
        self.esc_shortcut = QShortcut(QKeySequence("Escape"), self)
        self.esc_shortcut.activated.connect(self._on_emergency_stop)

    def _populate_cameras(self) -> None:
        cameras = CameraManager.list_available_cameras(max_tested=3)
        self.camera_combo.clear()
        for idx, label in cameras:
            self.camera_combo.addItem(label, idx)

    def _toggle_tracking(self) -> None:
        if self._is_tracking:
            self.stop_tracking()
        else:
            self.start_tracking()

    def start_tracking(self) -> None:
        if self._is_tracking:
            return

        self._is_tracking = True
        self.toggle_track_btn.setText("⏸ Stop Tracking")
        self.toggle_track_btn.setStyleSheet("background-color: #F59E0B; color: #0C0F14;")
        self.preview_widget.set_active(True)
        self.status_badge.setText("● TRACKING")
        self.status_badge.setStyleSheet("background: #064E3B; border: 1px solid #059669; border-radius: 6px; padding: 6px 14px; color: #34D399; font-weight: bold;")

        self.worker = TrackingWorker(self.config, self.cursor, self)
        self.worker.frame_processed.connect(self._on_frame_processed)
        self.worker.error_occurred.connect(self._on_tracking_error)
        self.worker.start()

        self.statusBar.showMessage("Tracking active. Hand movement drives Windows cursor. Space = Clutch.")

    def stop_tracking(self) -> None:
        if not self._is_tracking:
            return

        self._is_tracking = False
        self.toggle_track_btn.setText("▶ Start Tracking")
        self.toggle_track_btn.setStyleSheet("")
        self.status_badge.setText("● PAUSED")
        self.status_badge.setStyleSheet("background: #1C2333; border: 1px solid #30363D; border-radius: 6px; padding: 6px 14px; color: #94A3B8; font-weight: bold;")

        if self.worker:
            self.worker.stop_worker()
            self.worker.wait(1500)
            self.worker = None

        self.preview_widget.set_active(False)
        self.fps_badge.setText("FPS: --")
        self.latency_badge.setText("Latency: -- ms")
        self.statusBar.showMessage("Tracking stopped.")

    def _on_emergency_stop(self) -> None:
        """Emergency Stop handler."""
        self.cursor.release_all_buttons()
        if self._is_tracking:
            self.stop_tracking()
        self.status_badge.setText("● EMERGENCY STOP")
        self.status_badge.setStyleSheet("background: #7F1D1D; border: 1px solid #DC2626; border-radius: 6px; padding: 6px 14px; color: #FCA5A5; font-weight: bold;")
        self.statusBar.showMessage("EMERGENCY STOP TRIGGERED. All mouse actions halted and buttons released.")

    def _toggle_keyboard_clutch(self) -> None:
        self._is_keyboard_clutch = not self._is_keyboard_clutch
        if self.worker:
            self.worker.set_clutch_hotkey(self._is_keyboard_clutch)

        if self._is_keyboard_clutch:
            self.clutch_ind.setText("Clutch: ACTIVE (Space)")
            self.clutch_ind.setStyleSheet("background: #78350F; border-radius: 6px; padding: 6px; color: #FCD34D; font-size: 12px; font-weight: bold;")
        else:
            self.clutch_ind.setText("Clutch: Inactive")
            self.clutch_ind.setStyleSheet("background: #161B22; border-radius: 6px; padding: 6px; color: #94A3B8; font-size: 12px;")

    def _toggle_cursor_mode(self) -> None:
        if self.config.cursor_mode == CursorMode.RELATIVE:
            self.config.cursor_mode = CursorMode.ABSOLUTE
            self.mode_toggle_btn.setText("Mode: Absolute Pointing")
        else:
            self.config.cursor_mode = CursorMode.RELATIVE
            self.mode_toggle_btn.setText("Mode: Relative Air-Mouse")
        self.statusBar.showMessage(f"Cursor mode switched to {self.config.cursor_mode.value.upper()}.")

    def _on_camera_selected(self, index: int) -> None:
        dev_idx = self.camera_combo.itemData(index)
        if dev_idx is not None and dev_idx != self.config.camera.device_index:
            self.config.camera.device_index = dev_idx
            if self._is_tracking:
                # Restart tracking with new camera
                self.stop_tracking()
                self.start_tracking()

    def _on_settings_modified(self) -> None:
        self.statusBar.showMessage("Settings updated.")

    def _open_calibration(self) -> None:
        dialog = CalibrationDialog(self.config, self)
        dialog.exec()

    @Slot(object, object, object, float, float)
    def _on_frame_processed(
        self,
        frame: np.ndarray,
        hand_data: Optional[HandLandmarkData],
        gesture_res: GestureResult,
        fps: float,
        latency_ms: float
    ) -> None:
        # Update video preview
        self.preview_widget.update_frame(frame)

        # Update telemetry
        self.fps_badge.setText(f"FPS: {fps:.1f}")
        self.latency_badge.setText(f"Latency: {latency_ms:.1f} ms")

        # Update gesture indicators
        if gesture_res.is_dragging:
            self.left_click_ind.setText("Left Click: ✊ DRAGGING")
            self.left_click_ind.setStyleSheet("background: #1E3A8A; color: #93C5FD; border-radius: 6px; padding: 6px; font-weight: bold;")
        elif gesture_res.is_left_pinched:
            self.left_click_ind.setText(f"Left Click: PINCHED ({gesture_res.pinch_distance:.2f})")
            self.left_click_ind.setStyleSheet("background: #064E3B; color: #6EE7B7; border-radius: 6px; padding: 6px; font-weight: bold;")
        else:
            self.left_click_ind.setText("Left Click: Ready")
            self.left_click_ind.setStyleSheet("background: #161B22; border-radius: 6px; padding: 6px; color: #94A3B8;")

        if gesture_res.is_right_pinched:
            self.right_click_ind.setText("Right Click: PINCHED")
            self.right_click_ind.setStyleSheet("background: #78350F; color: #FCD34D; border-radius: 6px; padding: 6px; font-weight: bold;")
        else:
            self.right_click_ind.setText("Right Click: Ready")
            self.right_click_ind.setStyleSheet("background: #161B22; border-radius: 6px; padding: 6px; color: #94A3B8;")

        if gesture_res.is_clutched or self._is_keyboard_clutch:
            self.clutch_ind.setText("Clutch: ACTIVE (Paused)")
            self.clutch_ind.setStyleSheet("background: #78350F; border-radius: 6px; padding: 6px; color: #FCD34D; font-size: 12px; font-weight: bold;")
        else:
            self.clutch_ind.setText("Clutch: Inactive")
            self.clutch_ind.setStyleSheet("background: #161B22; border-radius: 6px; padding: 6px; color: #94A3B8; font-size: 12px;")

    @Slot(str)
    def _on_tracking_error(self, err_msg: str) -> None:
        self.stop_tracking()
        self.preview_widget.show_error(err_msg)
        QMessageBox.warning(self, "AirPoint Tracking Alert", err_msg)

    def closeEvent(self, event) -> None:
        """Safe exit: release camera and held buttons."""
        self.stop_tracking()
        self.cursor.release_all_buttons()
        self.config.save()
        event.accept()
