"""Integration test for PySide6 MainWindow lifecycle in mock mode."""

import pytest
from PySide6.QtWidgets import QApplication
from airpoint.config import AppConfig
from airpoint.ui.main_window import MainWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_window_init(qapp):
    config = AppConfig()
    window = MainWindow(config)
    # Enable mock mode so OS cursor isn't moved during testing
    window.cursor.mock_mode = True

    assert window.windowTitle() == "AirPoint - 3D Air Mouse"
    assert not window._is_tracking

    # Test mode toggle
    window._toggle_cursor_mode()
    assert window.config.cursor_mode.value == "absolute"

    window._toggle_cursor_mode()
    assert window.config.cursor_mode.value == "relative"

    # Test settings panel loaded values
    assert window.settings_panel.sens_slider.value() == int(config.motion.sensitivity * 10)

    # Test emergency stop
    window._on_emergency_stop()
    assert not window._is_tracking
