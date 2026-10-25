"""Camera capture manager with Windows Media Foundation concurrent sharing support."""

from __future__ import annotations
import threading
import time
from typing import List, Optional, Tuple
import cv2
import numpy as np
from airpoint.config import CameraConfig


class CameraManager:
    """
    Manages webcam capture in a dedicated background thread.
    Uses Windows Media Foundation (MSMF) by default to enable concurrent camera
    sharing with web browsers (e.g. Chrome, Edge) and conference tools via
    the Windows Camera Frame Server.
    """

    def __init__(self, config: CameraConfig):
        self.config = config
        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._lock = threading.Lock()

        # Latest frame storage (zero latency drop-policy)
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_timestamp: float = 0.0
        self._frame_count: int = 0
        self._fps: float = 0.0
        self._last_fps_calc_time: float = 0.0

        # Status and error messages
        self.is_connected: bool = False
        self.last_error: str = ""

    @staticmethod
    def list_available_cameras(max_tested: int = 4) -> List[Tuple[int, str]]:
        """
        Scan for available camera devices.
        Returns list of (index, label) tuples.
        """
        available = []
        for idx in range(max_tested):
            # Try MSMF first, fallback to DSHOW
            cap = cv2.VideoCapture(idx, cv2.CAP_MSMF)
            if not cap.isOpened():
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if cap.isOpened():
                available.append((idx, f"Camera {idx} (Integrated / USB)"))
                cap.release()
        if not available:
            # Always provide Camera 0 as a default option
            available.append((0, "Camera 0 (Default)"))
        return available

    def start(self) -> bool:
        """Open the camera and start the background capture thread."""
        if self._running:
            return True

        self.last_error = ""
        backend_flag = cv2.CAP_MSMF if self.config.backend.upper() == "MSMF" else cv2.CAP_DSHOW

        try:
            # Try preferred backend (MSMF enables Windows Frame Server multi-client capture)
            self._cap = cv2.VideoCapture(self.config.device_index, backend_flag)
            if not self._cap.isOpened() and backend_flag == cv2.CAP_MSMF:
                # Fallback to DSHOW or default if MSMF fails
                self._cap = cv2.VideoCapture(self.config.device_index, cv2.CAP_DSHOW)
            if not self._cap.isOpened():
                self._cap = cv2.VideoCapture(self.config.device_index)

            if not self._cap or not self._cap.isOpened():
                self.is_connected = False
                self.last_error = (
                    f"Cannot open camera index {self.config.device_index}. "
                    "If another app has exclusive lock, ensure Windows Camera Frame Server is enabled or choose another camera."
                )
                return False

            # Configure resolution and FPS
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
            self._cap.set(cv2.CAP_PROP_FPS, self.config.target_fps)

            self.is_connected = True
            self._running = True
            self._last_fps_calc_time = time.monotonic()
            self._frame_count = 0

            self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="AirPoint-Camera")
            self._thread.start()
            return True

        except Exception as e:
            self.is_connected = False
            self.last_error = f"Camera initialization failed: {e}"
            return False

    def _capture_loop(self) -> None:
        """Capture frames in background thread with a 1-item latest-frame policy."""
        while self._running and self._cap and self._cap.isOpened():
            ret, frame = self._cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            now = time.monotonic()
            with self._lock:
                self._latest_frame = frame
                self._frame_timestamp = now
                self._frame_count += 1

                # Calculate real-time FPS
                dt = now - self._last_fps_calc_time
                if dt >= 1.0:
                    self._fps = self._frame_count / dt
                    self._frame_count = 0
                    self._last_fps_calc_time = now

        self.is_connected = False

    def get_latest_frame(self) -> Tuple[Optional[np.ndarray], float]:
        """
        Thread-safe retrieval of the freshest camera frame.
        Returns (frame, timestamp).
        """
        with self._lock:
            if self._latest_frame is None:
                return None, 0.0
            return self._latest_frame.copy(), self._frame_timestamp

    @property
    def fps(self) -> float:
        return self._fps

    def stop(self) -> None:
        """Stop capture and release device cleanly."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
            self._thread = None

        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        with self._lock:
            self._latest_frame = None

        self.is_connected = False
