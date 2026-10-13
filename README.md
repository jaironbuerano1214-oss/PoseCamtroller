# PoseCamtroller

Control your computer with body poses — map any detected body position to a keyboard shortcut and trigger it in real time via your webcam.

---

## Prerequisites

- **Python 3.11+** (3.15 fully supported and tested)
- A working webcam
- Windows 10/11

---

## Setup

```powershell
cd PoseCamtroller
pip install -r requirements.txt
```

> **Tip:** Use a virtual environment:
> ```powershell
> python -m venv .venv
> .venv\Scripts\Activate.ps1
> pip install -r requirements.txt
> ```

---

## Running

```powershell
python main.py
```

The app opens a window with two tabs: **Live View** and **Profiles**.

---

## Usage Guide

### 1. Create a Profile

1. Open the **Profiles** tab.
2. Click **+ New Profile** and enter a name (e.g. "Gaming").

### 2. Add a Pose

1. With a profile selected, click **+ Add Pose**.
2. The **Capture Pose** dialog opens with your live camera feed.
3. Enter a pose name, get into position, and click **Capture**.
4. A 3-2-1 countdown fires; hold your pose until it completes.
5. A snapshot is taken. Click **Save**.
6. The **Assign Keystroke** dialog opens — click **Record**, press your key combination, choose Tap or Hold mode, and click **OK**.

### 3. Tune Sensitivity

Each pose card has an individual **Threshold** slider (10–100%). The pose triggers its keystroke only when the live match score exceeds this threshold. Adjust it if the pose fires too easily or not at all.

The **Global sensitivity** slider on the Live View tab acts as a quick reference display (per-pose thresholds take precedence).

### 4. Start Detection

1. Switch to the **Live View** tab.
2. Click **▶ Start Detection**.
3. The match score bars on the right update in real time — green = above threshold (keystroke firing).
4. The app minimises to the system tray. Double-click the tray icon to reopen the window.

### 5. System Tray

| Action | Effect |
|---|---|
| Double-click icon | Open main window |
| Right-click → Pause Detection | Pause/resume without stopping |
| Right-click → Quit | Shut down and release all held keys |

### 6. Import / Export Profiles

- **Export…** saves the active profile to a `.json` file you can share or back up.
- **Import…** loads a `.json` profile file from disk.

---

## Key Modes

| Mode | Behaviour |
|---|---|
| **Tap** | Fires the keystroke once when the pose is first detected (500 ms cooldown) |
| **Hold** | Holds the keys down while the pose is active; releases when pose exits threshold |

---

## File Layout

```
PoseCamtroller/
  main.py               # entry point  (`python main.py`)
  requirements.txt
  app/
    camera_thread.py    # webcam + MediaPipe PoseLandmarker QThread
    skeleton_renderer.py# green skeleton overlay
    pose_matcher.py     # bone-vector cosine similarity
    pose_capture.py     # 3-2-1 countdown capture dialog
    key_recorder_dialog.py # pynput-based key combo recorder
    profile_store.py    # dataclasses + JSON persistence
    keystroke_engine.py # pynput tap / hold dispatcher
    main_window.py      # main UI (Live View + Profiles tabs)
    tray.py             # system tray icon + context menu
    widgets/
      pose_card.py      # per-pose editor card
      threshold_slider.py # QSlider + % label
  profiles/             # saved profile JSON files
  assets/
    icon.png            # app icon (optional)
    pose_landmarker_lite.task  # downloaded on first run
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Could not open webcam" | Check another app isn't using the camera; try a different camera index in `camera_thread.py` |
| Pose never triggers | Lower the threshold slider on that pose card |
| Pose triggers constantly | Raise the threshold slider |
| High CPU usage | MediaPipe Tasks-API lite model is already the lightest; close other heavy applications |
| `TypeError` / `AttributeError` on `ThreadPoolExecutor` (Python 3.15) | `main.py` pre-materialises `concurrent.futures` lazy loaders at startup — ensure you run via `python main.py`, not a partial import |
| Model not found on first run | The app auto-downloads `pose_landmarker_lite.task` to `assets/`; ensure network access on first launch |

---

## Python 3.15 Compatibility

Python 3.15 introduces lazy stdlib loaders. `mediapipe`'s internal `serial_dispatcher`
module accesses `concurrent.futures.ThreadPoolExecutor` at runtime inside a background
thread. If the module is still a lazy proxy at that point the call raises `TypeError`.

`main.py` fixes this by explicitly importing the concrete executor classes and pinning
them into the `concurrent.futures` namespace **before** any `QThread` or MediaPipe code
runs:

```python
import concurrent.futures
from concurrent.futures.thread import ThreadPoolExecutor as _TPE
from concurrent.futures.process import ProcessPoolExecutor as _PPE
concurrent.futures.ThreadPoolExecutor = _TPE
concurrent.futures.ProcessPoolExecutor = _PPE
```

`camera_thread.py` applies the same patch again inside `CameraThread.run()` as a
belt-and-suspenders measure for the MediaPipe `serial_dispatcher` module globals.
