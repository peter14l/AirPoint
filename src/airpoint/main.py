"""Entry point for the AirPoint Windows desktop application."""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from airpoint.config import AppConfig, CursorMode
from airpoint.ui.main_window import MainWindow


def parse_args():
    parser = argparse.ArgumentParser(description="AirPoint - Webcam-Based 3D Air Mouse for Windows")
    parser.add_argument(
        "--mode",
        choices=["relative", "absolute"],
        default=None,
        help="Initial cursor mode (default: relative)"
    )
    parser.add_argument(
        "--camera",
        type=int,
        default=None,
        help="Camera device index (default: 0)"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run in virtual mock mode without controlling real Windows cursor"
    )
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Automatically begin camera tracking upon launch"
    )
    return parser.parse_args()


def main():
    # Enable high-DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("AirPoint")
    app.setOrganizationName("AirPoint")

    args = parse_args()

    # Load persistent configuration
    config = AppConfig.load()

    if args.mode:
        config.cursor_mode = CursorMode(args.mode)
    if args.camera is not None:
        config.camera.device_index = args.camera

    window = MainWindow(config)
    if args.mock:
        window.cursor.mock_mode = True

    window.show()

    if args.autostart:
        window.start_tracking()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
