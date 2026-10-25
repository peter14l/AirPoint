# AirPoint: Webcam-Based 3D Air Mouse for Windows

AirPoint is a fully local Windows application that transforms your laptop's integrated webcam into a high-performance, real-time air mouse. By tracking natural hand movements and gestures in camera space, AirPoint lets you control your physical Windows cursor and execute mouse clicks without touching a trackpad, physical mouse, ring, or external sensors.

---

## 🌟 Key Features

* **Relative Air-Mouse Mode (Primary):**
  Uses incremental frame-to-frame displacement of a stable 4-point palm center. Moving your hand right moves the cursor right; moving left moves it left; upward and downward hand movements map intuitively to Windows cursor space.
* **Absolute Pointing Mode (Secondary):**
  Maps camera space directly to your screen coordinates with edge margin scaling and adaptive anti-jitter filtering.
* **Concurrent Camera Sharing (Windows Media Foundation):**
  Uses `cv2.CAP_MSMF` to route through the Windows Camera Frame Server (`FSvc`). **AirPoint works concurrently even when web browsers (Chrome, Edge) or video meetings (Meet, Teams, Zoom) are already using the webcam.**
* **Natural Gestures with Hysteresis & Cooldown:**
  * **Primary Left Click:** Thumb-to-index pinch transition with dual-threshold hysteresis.
  * **Drag & Drop:** Holding the pinch for > 350ms engages mouse button-down until released.
  * **Right Click:** Thumb-to-middle finger pinch.
  * **Clutch (Movement Pause):** Closed fist or Spacebar suspends cursor movement while keeping tracking alive, allowing you to reposition your hand comfortably without moving the cursor.
* **Anti-Drift & Non-Linear Ballistics:**
  Configurable dead zone completely eliminates cursor drift when your hand is resting or trembling. Smooth exponential velocity acceleration allows pixel-level precision at low speeds and swift screen-spanning sweeps on rapid flicks.
* **Safety First:**
  * **Emergency Stop (F8 / ESC / UI button):** Instantly halts cursor motion and releases any held mouse buttons.
  * **Tracking Watchdog:** If hand tracking is lost or confidence drops below threshold, all mouse buttons are immediately released to prevent stuck drag operations.
* **Modern Desktop GUI (PySide6):**
  Restrained dark appearance (`#0C0F14`), real-time FPS/latency telemetry, landmark preview overlay, and interactive calibration wizards.

---

## 📐 Architecture & Modular Design

```
airpoint/
├── README.md
├── requirements.txt
├── pyproject.toml
├── pytest.ini
├── models/
│   └── hand_landmarker.task      # Local Google MediaPipe Task model
├── src/
│   └── airpoint/
│       ├── __init__.py
│       ├── main.py               # CLI entrypoint and application bootstrap
│       ├── config.py             # Persistent configuration & schema validation
│       ├── camera.py             # OpenCV threaded capture with MSMF sharing
│       ├── hand_tracker.py       # MediaPipe Tasks HandLandmarker & skeleton visualizer
│       ├── landmarks.py          # Palm centroid, normalized pinch & geometric math
│       ├── motion_engine.py      # Relative/Absolute motion pipeline & ballistics
│       ├── cursor_controller.py  # Native Win32 user32 cursor dispatch & test mock
│       ├── gesture_recognizer.py # State machine for clicks, dragging, and clutch
│       ├── calibration.py        # Screen region bounds & sensitivity auto-tuner
│       ├── safety.py             # Watchdog, confidence gate & button safety
│       └── ui/
│           ├── __init__.py
│           ├── main_window.py    # Main window with QThread tracking worker
│           ├── preview_widget.py # Live video preview with landmark renderer
│           ├── settings_panel.py # Real-time sliders, backend and startup toggles
│           └── calibration_dialog.py # Guided calibration wizard
└── tests/
    ├── test_motion_engine.py     # Directional displacement, dead zone, clamping
    ├── test_gesture_recognizer.py# Pinch hysteresis, drag hold, right click
    ├── test_calibration.py       # Bounds calculation, recenter, validation
    ├── test_safety.py            # Watchdog timeout, emergency stop, shutdown
    └── test_ui.py                # PySide6 lifecycle and UI state assertions
```

---

## 🚀 Installation & Launch

### Prerequisites
* Windows 10 or 11 (64-bit).
* Python 3.11 or 3.12.
* Integrated laptop webcam or standard USB webcam.

### Installation
1. Clone or navigate to the repository directory:
   ```cmd
   cd D:\mouse
   ```
2. Install dependencies:
   ```cmd
   pip install -r requirements.txt
   ```
3. Install the AirPoint package in editable mode:
   ```cmd
   pip install -e .
   ```

### Running the Application
Launch via python module or console entrypoint:
```cmd
python -m airpoint.main
```

#### Command-Line Options:
* `--mode [relative|absolute]`: Start directly in relative air-mouse or absolute pointing mode.
* `--camera [0, 1, ...]`: Specify camera index.
* `--mock`: Run with virtual cursor simulation without driving the OS pointer (ideal for testing).

---

## 🎮 How to Use & Controls

| Action | Physical Hand Gesture | Fallback / Shortcut |
| :--- | :--- | :--- |
| **Move Cursor** | Move hand freely in front of webcam | — |
| **Left Click** | Pinch thumb and index fingertip together once | — |
| **Drag & Drop** | Hold thumb-index pinch for > 350ms | — |
| **Right Click** | Pinch thumb and middle fingertip together | — |
| **Clutch (Pause Motion)** | Form a closed fist | **Spacebar** |
| **Emergency Stop** | Click red Emergency Stop button | **F8** or **Escape** |
| **Switch Modes** | Click "Mode" button in toolbar | — |

---

## 🛠️ Tuning & Calibrating Sensitivity

1. **Dead Zone (Anti-Drift):**
   * If your cursor drifts or twitches when your hand is held still, increase **Dead Zone** slightly (default: `0.002`).
2. **Sensitivity:**
   * Adjust **Sensitivity** slider between `1.5x` and `3.5x` depending on your physical hand movement preference.
   * You can also open the **Calibration Wizard** and use the **3-second Velocity Measurement** to automatically calculate the recommended sensitivity.
3. **Pinch Threshold:**
   * If clicks trigger too early, lower the click pinch threshold.
   * If you have to press fingers together too forcefully, increase the threshold.
   * Note: AirPoint normalizes pinch distance against hand scale, so click sensitivity remains consistent regardless of how close your hand is to the camera.

---

## 📷 Simultaneous Camera Sharing (Websites & Video Calls)

AirPoint uses **Windows Media Foundation (`CAP_MSMF`)** by default.
* Windows 10/11 includes the **Windows Camera Frame Server** service (`FSvc`).
* When web browsers (Chrome, Edge) or meeting clients (Teams, Meet, Zoom) request the webcam, Media Foundation coordinates frame delivery so that **AirPoint and your browser can access the video feed at the same time**.
* If a legacy 3rd-party application claims exclusive DirectShow control, you can switch backends or select a virtual camera (e.g. **OBS Virtual Camera**) directly from the camera dropdown.

---

## 🧪 Automated Testing

Run the full pytest test suite (executes 19 deterministic tests without interfering with your physical desktop mouse):
```cmd
python -m pytest -v
```
All motion mathematics, direction mappings, dead-zone cutoffs, pinch hysteresis timers, calibration calculations, and button-release safety mechanisms are verified through automated unit tests.
