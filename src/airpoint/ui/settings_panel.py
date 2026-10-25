"""Settings configuration panel with responsive controls and numeric badges."""

from __future__ import annotations
import winreg
from typing import Callable, Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from airpoint.config import AppConfig, ClutchGesture, CursorMode, DominantHand


class SettingsPanel(QWidget):
    """
    Control settings panel with live updates and persistence.
    """

    settings_changed = Signal()

    def __init__(self, config: AppConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.config = config

        self._init_ui()
        self.load_from_config()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(16)

        # 1. Motion Tuning Group
        motion_group = QGroupBox("Motion & Physics")
        motion_layout = QFormLayout(motion_group)
        motion_layout.setSpacing(10)

        # Sensitivity
        self.sens_slider, self.sens_val = self._create_slider(5, 50, 22, lambda v: f"{v / 10:.1f}x")
        self.sens_slider.valueChanged.connect(self._on_sens_change)
        motion_layout.addRow(self._make_slider_row("Sensitivity:", self.sens_slider, self.sens_val))

        # Smoothing
        self.smooth_slider, self.smooth_val = self._create_slider(10, 95, 55, lambda v: f"{v / 100:.2f}")
        self.smooth_slider.valueChanged.connect(self._on_smooth_change)
        motion_layout.addRow(self._make_slider_row("Smoothing (Responsiveness):", self.smooth_slider, self.smooth_val))

        # Dead Zone
        self.dead_slider, self.dead_val = self._create_slider(0, 15, 2, lambda v: f"{v / 1000:.3f}")
        self.dead_slider.valueChanged.connect(self._on_dead_change)
        motion_layout.addRow(self._make_slider_row("Dead Zone (Anti-Drift):", self.dead_slider, self.dead_val))

        # Acceleration
        self.accel_slider, self.accel_val = self._create_slider(10, 22, 14, lambda v: f"{v / 10:.1f}x")
        self.accel_slider.valueChanged.connect(self._on_accel_change)
        motion_layout.addRow(self._make_slider_row("Non-Linear Acceleration:", self.accel_slider, self.accel_val))

        # Inversion checkboxes
        self.invert_x_cb = QCheckBox("Invert X (Horizontal)")
        self.invert_x_cb.toggled.connect(self._on_invert_x_toggle)
        self.invert_y_cb = QCheckBox("Invert Y (Vertical)")
        self.invert_y_cb.toggled.connect(self._on_invert_y_toggle)
        inv_row = QHBoxLayout()
        inv_row.addWidget(self.invert_x_cb)
        inv_row.addWidget(self.invert_y_cb)
        motion_layout.addRow("Direction Invert:", inv_row)

        layout.addWidget(motion_group)

        # 2. Gestures Group
        gesture_group = QGroupBox("Gestures & Clicking")
        gesture_layout = QFormLayout(gesture_group)
        gesture_layout.setSpacing(10)

        # Pinch Threshold
        self.pinch_slider, self.pinch_val = self._create_slider(20, 100, 48, lambda v: f"{v / 1000:.3f}")
        self.pinch_slider.valueChanged.connect(self._on_pinch_change)
        gesture_layout.addRow(self._make_slider_row("Click Pinch Threshold:", self.pinch_slider, self.pinch_val))

        # Clutch Gesture
        self.clutch_combo = QComboBox()
        self.clutch_combo.addItems([g.value for g in ClutchGesture])
        self.clutch_combo.currentTextChanged.connect(self._on_clutch_change)
        gesture_layout.addRow("Clutch Gesture (Pause):", self.clutch_combo)

        # Right click and drag toggles
        self.right_click_cb = QCheckBox("Enable Right-Click (Thumb + Middle Pinch)")
        self.right_click_cb.toggled.connect(self._on_right_click_toggle)
        self.drag_cb = QCheckBox("Enable Drag-and-Drop (Hold Pinch > 350ms)")
        self.drag_cb.toggled.connect(self._on_drag_toggle)

        gesture_layout.addRow("", self.right_click_cb)
        gesture_layout.addRow("", self.drag_cb)

        layout.addWidget(gesture_group)

        # 3. System & Camera Group
        system_group = QGroupBox("Device & System")
        sys_layout = QFormLayout(system_group)
        sys_layout.setSpacing(10)

        # Dominant Hand
        self.hand_combo = QComboBox()
        self.hand_combo.addItems([h.value for h in DominantHand])
        self.hand_combo.currentTextChanged.connect(self._on_hand_change)
        sys_layout.addRow("Dominant Hand:", self.hand_combo)

        # Camera Backend (Concurrent browser sharing)
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("MSMF (Shared with Chrome/Meet/Edge)", "MSMF")
        self.backend_combo.addItem("DirectShow (Legacy Exclusive)", "DSHOW")
        self.backend_combo.currentIndexChanged.connect(self._on_backend_change)
        sys_layout.addRow("Camera Backend:", self.backend_combo)

        # Startup launch
        self.startup_cb = QCheckBox("Start AirPoint automatically at Windows login")
        self.startup_cb.toggled.connect(self._on_startup_toggle)
        sys_layout.addRow("", self.startup_cb)

        layout.addWidget(system_group)

        # Reset / Save buttons
        btn_row = QHBoxLayout()
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setObjectName("secondaryBtn")
        reset_btn.clicked.connect(self._on_reset_defaults)
        save_btn = QPushButton("Save Settings")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._on_save_settings)

        btn_row.addWidget(reset_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def _create_slider(self, min_v: int, max_v: int, def_v: int, label_fmt: Callable[[int], str]):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_v, max_v)
        slider.setValue(def_v)
        val_lbl = QLabel(label_fmt(def_v))
        val_lbl.setFixedWidth(55)
        slider.valueChanged.connect(lambda v: val_lbl.setText(label_fmt(v)))
        return slider, val_lbl

    def _make_slider_row(self, title: str, slider: QSlider, label: QLabel) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(slider, 1)
        row.addWidget(label)
        return row

    def load_from_config(self) -> None:
        self.sens_slider.setValue(int(self.config.motion.sensitivity * 10))
        self.smooth_slider.setValue(int(self.config.motion.smoothing * 100))
        self.dead_slider.setValue(int(self.config.motion.dead_zone * 1000))
        self.accel_slider.setValue(int(self.config.motion.acceleration * 10))
        self.invert_x_cb.setChecked(self.config.motion.invert_x)
        self.invert_y_cb.setChecked(self.config.motion.invert_y)

        self.pinch_slider.setValue(int(self.config.gestures.pinch_threshold * 1000))
        self.clutch_combo.setCurrentText(self.config.gestures.clutch_gesture.value)
        self.right_click_cb.setChecked(self.config.gestures.enable_right_click)
        self.drag_cb.setChecked(self.config.gestures.enable_drag)

        self.hand_combo.setCurrentText(self.config.dominant_hand.value)
        idx = 0 if self.config.camera.backend == "MSMF" else 1
        self.backend_combo.setCurrentIndex(idx)
        self.startup_cb.setChecked(self.config.launch_at_login)

    # Event handlers
    def _on_sens_change(self, v: int) -> None:
        self.config.motion.sensitivity = v / 10.0
        self.settings_changed.emit()

    def _on_smooth_change(self, v: int) -> None:
        self.config.motion.smoothing = v / 100.0
        self.settings_changed.emit()

    def _on_dead_change(self, v: int) -> None:
        self.config.motion.dead_zone = v / 1000.0
        self.settings_changed.emit()

    def _on_accel_change(self, v: int) -> None:
        self.config.motion.acceleration = v / 10.0
        self.settings_changed.emit()

    def _on_invert_x_toggle(self, checked: bool) -> None:
        self.config.motion.invert_x = checked
        self.settings_changed.emit()

    def _on_invert_y_toggle(self, checked: bool) -> None:
        self.config.motion.invert_y = checked
        self.settings_changed.emit()

    def _on_pinch_change(self, v: int) -> None:
        self.config.gestures.pinch_threshold = v / 1000.0
        self.config.gestures.pinch_release_threshold = (v / 1000.0) + 0.025
        self.settings_changed.emit()

    def _on_clutch_change(self, text: str) -> None:
        self.config.gestures.clutch_gesture = ClutchGesture(text)
        self.settings_changed.emit()

    def _on_right_click_toggle(self, checked: bool) -> None:
        self.config.gestures.enable_right_click = checked
        self.settings_changed.emit()

    def _on_drag_toggle(self, checked: bool) -> None:
        self.config.gestures.enable_drag = checked
        self.settings_changed.emit()

    def _on_hand_change(self, text: str) -> None:
        self.config.dominant_hand = DominantHand(text)
        self.settings_changed.emit()

    def _on_backend_change(self, index: int) -> None:
        self.config.camera.backend = self.backend_combo.itemData(index)
        self.settings_changed.emit()

    def _on_startup_toggle(self, checked: bool) -> None:
        self.config.launch_at_login = checked
        self._set_windows_startup(checked)

    def _set_windows_startup(self, enable: bool) -> None:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "AirPoint"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    import sys
                    python_exe = sys.executable
                    script_path = str(Path(__file__).parent.parent / "main.py")
                    cmd = f'"{python_exe}" "{script_path}"'
                    winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, app_name)
                    except FileNotFoundError:
                        pass
        except Exception:
            pass

    def _on_reset_defaults(self) -> None:
        self.config.motion.sensitivity = 2.2
        self.config.motion.smoothing = 0.55
        self.config.motion.dead_zone = 0.0018
        self.config.motion.acceleration = 1.35
        self.config.motion.invert_x = False
        self.config.motion.invert_y = False
        self.config.gestures.pinch_threshold = 0.048
        self.config.gestures.pinch_release_threshold = 0.075
        self.load_from_config()
        self.settings_changed.emit()

    def _on_save_settings(self) -> None:
        self.config.save()
