"""Windows cursor control using native Win32 APIs, with test mock mode and safety guarantees."""

from __future__ import annotations
import ctypes
from ctypes import wintypes
from typing import Tuple


# Win32 Mouse Event Flags
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000

SM_CXSCREEN = 0
SM_CYSCREEN = 1


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class CursorController:
    """
    Controls the physical Windows cursor and mouse buttons via User32.
    Includes a mock mode for deterministic automated testing.
    """

    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self._user32 = None

        # Virtual cursor state for mock mode and tracking
        self.mock_x: int = 960
        self.mock_y: int = 540
        self.is_left_down: bool = False
        self.is_right_down: bool = False

        # Event log for test assertions
        self.event_log: list = []

        if not self.mock_mode:
            try:
                # Ensure thread is attached to the interactive desktop if running in subprocess/service
                import win32service, win32con
                try:
                    desk = win32service.OpenDesktop('default', 0, False, win32con.GENERIC_ALL)
                    desk.SetThreadDesktop()
                except Exception:
                    pass
            except ImportError:
                pass

            try:
                self._user32 = ctypes.windll.user32
            except (AttributeError, OSError):
                # Non-Windows or ctypes unavailable: fallback to mock mode
                self.mock_mode = True

    def get_screen_size(self) -> Tuple[int, int]:
        """Returns primary display resolution (width, height)."""
        if self.mock_mode or not self._user32:
            return 1920, 1080
        try:
            w = self._user32.GetSystemMetrics(SM_CXSCREEN)
            h = self._user32.GetSystemMetrics(SM_CYSCREEN)
            return max(1, w), max(1, h)
        except Exception:
            return 1920, 1080

    def get_position(self) -> Tuple[int, int]:
        """Returns current cursor position (x, y)."""
        if self.mock_mode or not self._user32:
            return self.mock_x, self.mock_y
        try:
            pt = POINT()
            self._user32.GetCursorPos(ctypes.byref(pt))
            return pt.x, pt.y
        except Exception:
            return self.mock_x, self.mock_y

    def move_relative(self, dx: float, dy: float) -> None:
        """Move cursor by delta pixels relative to current position."""
        if abs(dx) < 0.01 and abs(dy) < 0.01:
            return

        cur_x, cur_y = self.get_position()
        w, h = self.get_screen_size()

        new_x = max(0, min(w - 1, int(round(cur_x + dx))))
        new_y = max(0, min(h - 1, int(round(cur_y + dy))))

        self.move_to(new_x, new_y)

    def move_to(self, x: int | float, y: int | float) -> None:
        """Move cursor to absolute coordinates clamped within screen bounds."""
        w, h = self.get_screen_size()
        clamped_x = max(0, min(w - 1, int(round(x))))
        clamped_y = max(0, min(h - 1, int(round(y))))

        self.mock_x = clamped_x
        self.mock_y = clamped_y

        if self.mock_mode or not self._user32:
            self.event_log.append(("move_to", clamped_x, clamped_y))
            return

        try:
            self._user32.SetCursorPos(clamped_x, clamped_y)
        except Exception as e:
            self.event_log.append(("error", str(e)))

    def left_down(self) -> None:
        if self.is_left_down:
            return
        self.is_left_down = True
        self.event_log.append("left_down")
        if not self.mock_mode and self._user32:
            self._user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

    def left_up(self) -> None:
        if not self.is_left_down:
            return
        self.is_left_down = False
        self.event_log.append("left_up")
        if not self.mock_mode and self._user32:
            self._user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def left_click(self) -> None:
        """Perform atomic left click (down then up)."""
        self.event_log.append("left_click")
        if self.mock_mode or not self._user32:
            return
        self._user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        self._user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def right_click(self) -> None:
        """Perform atomic right click (down then up)."""
        self.event_log.append("right_click")
        if self.mock_mode or not self._user32:
            return
        self._user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        self._user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)

    def release_all_buttons(self) -> None:
        """Emergency release: ensure no mouse buttons remain held down."""
        if self.is_left_down:
            self.left_up()
        if self.is_right_down:
            self.is_right_down = False
            self.event_log.append("right_up")
            if not self.mock_mode and self._user32:
                self._user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
