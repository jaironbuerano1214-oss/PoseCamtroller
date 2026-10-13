# PoseKeys

Control your computer with body poses, voice commands, finger counts, pose sequences, screen zones, and ArUco marker tracking — all mapped to configurable keystrokes via your webcam.

---
## Download HERE
[HERE](https://drive.google.com/drive/folders/13BpJfauFnMG1hfv1cYj4v2MhL82YcPj4?usp=sharing)
## Download HERE 

---

## Prerequisites

- **Python 3.11+** (3.15 fully supported and tested)
- A working webcam
- Windows 10/11
- (Optional) Microphone for voice commands
- (Optional) Printed ArUco markers for marker tracking

---

## Setup

```powershell
cd posekeys
pip install -r requirements.txt
```

> **Tip:** Use a virtual environment:
> ```powershell
> python -m venv .venv
> .venv\Scripts\Activate.ps1
> pip install -r requirements.txt
> ```

The first time you start detection, the app will auto-download missing model files to `assets/`:
- `pose_landmarker_lite.task` — body pose model (~5 MB)
- `hand_landmarker.task` — hand landmark model (~9 MB)
- `vosk-model-small-en-us/` — offline speech recognition model (~50 MB, only when using Voice rules)

---

## Running

```powershell
python main.py
```

The app opens a window with two tabs: **Live View** and **Profiles**.

---

## Features

| Feature | Description |
|---|---|
| **Body Poses** | Match full-body poses by bone-vector cosine similarity; per-pose threshold slider |
| **Screen Zones** | Define rectangular regions — trigger when a body landmark enters the zone |
| **Finger Count** | Count raised fingers on left/right/either hand; assign a keystroke per count |
| **Pose Sequences** | Cheat-code style — fire a keystroke when a specific ordered sequence of poses is hit within a time window |
| **Voice Commands** | Spoken phrase triggers a keystroke; substring or exact-match; offline with Vosk |
| **ArUco Markers** | Track printed ArUco 4×4 markers as virtual landmarks; use as zone anchors |

---

## Usage Guide

### 1. Create a Profile

1. Open the **Profiles** tab.
2. Click **+ New Profile** and enter a name (e.g. "Gaming").

---

### 2. Add a Pose

1. With a profile selected, click **+ Add Pose**.
2. The **Capture Pose** dialog opens with your live camera feed.
3. Enter a pose name, get into position, and click **Capture**.
4. A 3-2-1 countdown fires — hold your pose until it completes.
5. Click **Save**, then assign a keystroke in the **Key Recorder** dialog.

Each pose card shows a **Threshold** slider (10–100%). The pose fires only when the live similarity score exceeds this threshold.

---

### 3. Add a Zone Rule

1. In the **Zones** sub-tab, click **+ Add Zone**.
2. The **Zone Editor** dialog opens — drag a rectangle over the camera preview.
3. Use the preset buttons (**Left Hand**, **Right Hand**, **Head**, **Hips**, **Marker #0–#3**) to snap landmarks to watch, or leave empty to watch all landmarks.
4. Assign a keystroke. The zone highlights green when triggered.

---

### 4. Add a Finger Rule

1. In the **Fingers** sub-tab, click **+ Add Finger Rule**.
2. Set the target finger count (0–5), select the hand (**Left**, **Right**, or **Either**), and assign a keystroke.

---

### 5. Add a Sequence Rule

1. In the **Sequences** sub-tab, click **+ Add Sequence**.
2. Drag poses into the desired order in the builder.
3. Set the time window (seconds) within which all poses must occur in order.
4. Assign a keystroke. The card shows a live progress bar as you step through the sequence.

---

### 6. Add a Voice Rule

1. In the **Voice** sub-tab, click **+ Add Voice Rule**.
2. Type the phrase to listen for, choose **Contains** or **Exact** match, and set a cooldown.
3. Use the **🎤 Record** button in the dialog to verify the phrase is recognised.
4. Assign a keystroke.

> The Vosk offline model (~50 MB) is downloaded on first Voice detection start.

---

### 7. Start Detection

1. Switch to the **Live View** tab.
2. Click **▶ Start Detection**.
3. Match score bars update in real time — green = above threshold (keystroke firing).
4. The app minimises to the system tray. Double-click the tray icon to reopen.

---

### 8. System Tray

| Action | Effect |
|---|---|
| Double-click icon | Open main window |
| Right-click → Pause Detection | Pause/resume without stopping |
| Right-click → Quit | Shut down and release all held keys |

---

### 9. Import / Export Profiles

- **Export…** saves the active profile to a `.json` file you can share or back up.
- **Import…** loads a `.json` profile file from disk.

---

## Key Modes

| Mode | Behaviour |
|---|---|
| **Tap** | Fires the keystroke once when first detected (500 ms cooldown) |
| **Hold** | Holds the keys down while active; releases when the condition exits threshold |

---

## ArUco Marker Tracking

Print any of the 4×4 ArUco markers (IDs 0–15) from [ArUco Marker Generator](https://chev.me/arucogen/) and hold or mount them in your camera view.

The tracker detects up to 16 markers simultaneously and maps each marker centre to a synthetic landmark index `100 + marker_id`. These virtual landmarks can be used as **Zone** anchors by selecting the **Marker #0–#3** preset buttons in the Zone Editor.

---

## File Layout

```
posekeys/
  main.py                   # entry point  (`python main.py`)
  requirements.txt
  config.json               # persisted camera index + last profile
  app/
    camera_thread.py        # webcam + MediaPipe PoseLandmarker QThread
    skeleton_renderer.py    # green skeleton overlay
    pose_matcher.py         # bone-vector cosine similarity, per-pose smoothing
    pose_capture.py         # 3-2-1 countdown capture dialog
    key_recorder_dialog.py  # pynput-based key combo recorder
    zone_editor_dialog.py   # draw-on-camera zone editor with marker overlay
    finger_rule_dialog.py   # finger count rule dialog
    sequence_rule_dialog.py # pose sequence builder dialog
    voice_rule_dialog.py    # voice rule dialog with live record
    profile_store.py        # all dataclasses + JSON persistence
    keystroke_engine.py     # pynput tap / hold dispatcher
    zone_engine.py          # zone hit detection
    finger_detector.py      # MediaPipe HandLandmarker finger counting
    sequence_engine.py      # cheat-code pose sequence engine
    marker_tracker.py       # ArUco 4×4 detection on raw BGR frames
    voice_engine.py         # Vosk offline speech recognition QThread
    main_window.py          # full UI: Live View + Profiles tabs, detection loop
    tray.py                 # system tray icon + context menu
    widgets/
      pose_card.py          # per-pose editor card
      threshold_slider.py   # QSlider + % label
  profiles/                 # saved profile JSON files
  assets/
    icon.png
    pose_landmarker_lite.task   # auto-downloaded on first run
    hand_landmarker.task        # auto-downloaded on first run
    vosk-model-small-en-us/     # auto-downloaded on first voice detection start
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Could not open webcam" | Check another app isn't using the camera; try a different camera index |
| Pose never triggers | Lower the threshold slider on that pose card |
| Pose triggers constantly | Raise the threshold slider |
| Voice never fires | Speak clearly; check the microphone is the system default; ensure Vosk model downloaded |
| Finger count unreliable | Ensure good lighting; keep the hand fully visible in frame |
| ArUco marker not detected | Use a printed marker (not a screen); ensure adequate contrast and at least 80px marker size |
| High CPU usage | The lite models are already the lightest available; close other heavy applications |
| `TypeError` on `ThreadPoolExecutor` (Python 3.15) | Ensure you run via `python main.py` — the bootstrap pre-materialises lazy loaders before QThreads start |
| Model not found on first run | The app auto-downloads models to `assets/`; ensure network access on first launch |

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
