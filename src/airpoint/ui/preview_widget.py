"""Webcam preview widget with landmark overlays and status badges."""

from __future__ import annotations
import numpy as np
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class CameraPreviewWidget(QWidget):
    """
    Renders the live video feed with hand landmarks and interactive telemetry.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(480, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._image_label = QLabel(self)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background-color: #0A0D12; border-radius: 8px;")
        layout.addWidget(self._image_label)

        self._is_active: bool = False
        self._show_placeholder("Camera inactive. Click 'Start Tracking' to begin.")

    def set_active(self, active: bool) -> None:
        self._is_active = active
        if not active:
            self._show_placeholder("Tracking Paused\nClick 'Start Tracking' or press Space to resume.")

    def show_error(self, message: str) -> None:
        self._show_placeholder(f"Camera Error:\n{message}", error=True)

    def _show_placeholder(self, text: str, error: bool = False) -> None:
        pixmap = QPixmap(640, 480)
        pixmap.fill(QColor("#0A0D12"))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = QColor("#EF4444") if error else QColor("#64748B")
        painter.setPen(color)
        font = QFont("Segoe UI", 12)
        painter.setFont(font)

        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()

        self._image_label.setPixmap(
            pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def update_frame(self, bgr_frame: np.ndarray) -> None:
        """Receive BGR frame, convert to QImage and paint to label."""
        if bgr_frame is None or not self._is_active:
            return

        h, w, ch = bgr_frame.shape
        bytes_per_line = ch * w

        # Convert BGR to RGB for QImage
        rgb_frame = np.ascontiguousarray(bgr_frame[:, :, ::-1])
        qimg = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)

        target_size = self.size()
        pixmap = QPixmap.fromImage(qimg).scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(pixmap)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._is_active:
            self._show_placeholder("Camera inactive. Click 'Start Tracking' to begin.")
