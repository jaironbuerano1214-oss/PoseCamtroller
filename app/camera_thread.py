"""CameraThread — background QThread that reads webcam frames and runs MediaPipe PoseLandmarker.

Uses the MediaPipe Tasks API (mediapipe >= 0.10.30).
The pose_landmarker_lite.task model is downloaded automatically on first run to
  <app-dir>/assets/pose_landmarker_lite.task
"""
from __future__ import annotations

import concurrent.futures  # noqa: F401 — pre-load for Python 3.15 mediapipe compat
import os
import sys
import threading
import time
import urllib.request

import cv2
import mediapipe as mp

# ── Python 3.15 lazy-import workaround for mediapipe.tasks.python.core.serial_dispatcher ──
# In Python 3.15, stdlib modules can be lazily imported. When serial_dispatcher.py is
# executed, its module-level `concurrent` binding may be a lazy proxy that hasn't been
# materialised yet.  Patching the module's globals with the real object fixes it.
def _patch_mediapipe_serial_dispatcher() -> None:
    try:
        import importlib
        sd_mod_name = "mediapipe.tasks.python.core.serial_dispatcher"
        if sd_mod_name in sys.modules:
            mod = sys.modules[sd_mod_name]
            import concurrent as _conc
            import concurrent.futures as _cf
            mod.concurrent = _conc  # replace any lazy proxy
        else:
            # Force the import (and its re-exported concurrent ref) before first use
            import concurrent as _conc
            import concurrent.futures as _cf  # noqa: F401
    except Exception:
        pass  # best-effort; if this fails the original error will surface anyway

_patch_mediapipe_serial_dispatcher()
from PySide6.QtCore import Signal, QThread
from PySide6.QtGui import QImage

from app.skeleton_renderer import SkeletonRenderer

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/"
    "float16/1/pose_landmarker_lite.task"
)
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
_MODEL_PATH = os.path.join(_ASSETS_DIR, "pose_landmarker_lite.task")


def _ensure_model() -> str:
    """Download the model file if not already cached. Returns local path."""
    os.makedirs(_ASSETS_DIR, exist_ok=True)
    if not os.path.exists(_MODEL_PATH):
        print(f"[PoseKeys] Downloading model to {_MODEL_PATH} …")
        urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
        print("[PoseKeys] Model downloaded.")
    return _MODEL_PATH


class CameraThread(QThread):
    frame_ready = Signal(QImage)
    raw_frame_ready = Signal(object)  # numpy BGR ndarray — for marker detection
    landmarks_ready = Signal(object)  # list of NormalizedLandmark-like objects
    error = Signal(str)

    def __init__(self, camera_index: int = 0, parent=None):
        super().__init__(parent)
        self._camera_index = camera_index
        self._running = False
        self._renderer = SkeletonRenderer()
        self._latest_landmarks = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def run(self):
        # Download model if needed
        try:
            model_path = _ensure_model()
        except Exception as e:
            self.error.emit(f"Failed to download pose model: {e}")
            return

        VisionRunningMode = mp.tasks.vision.RunningMode
        PoseLandmarker = mp.tasks.vision.PoseLandmarker
        PoseLandmarkerOptions = mp.tasks.vision.PoseLandmarkerOptions
        BaseOptions = mp.tasks.BaseOptions

        # Python 3.15 lazy-import fix: patch serial_dispatcher's module globals so that
        # `concurrent.futures` resolves to the real module, not a lazy proxy.
        import concurrent.futures as _cf
        _ = _cf.ThreadPoolExecutor  # materialise inside this thread
        _sd_key = "mediapipe.tasks.python.core.serial_dispatcher"
        if _sd_key in sys.modules:
            _sd_mod = sys.modules[_sd_key]
            import concurrent as _conc
            _sd_mod.concurrent = _conc

        def _on_result(result, output_image, timestamp_ms):
            if result.pose_landmarks:
                with self._lock:
                    self._latest_landmarks = result.pose_landmarks[0]  # first person
                self.landmarks_ready.emit(list(result.pose_landmarks[0]))

        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=VisionRunningMode.LIVE_STREAM,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_pose_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            result_callback=_on_result,
        )

        cap = cv2.VideoCapture(self._camera_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            self.error.emit("Could not open webcam. Check that a camera is connected.")
            return

        self._running = True
        with PoseLandmarker.create_from_options(options) as landmarker:
            try:
                while self._running:
                    ret, frame = cap.read()
                    if not ret:
                        continue

                    timestamp_ms = int(time.time() * 1000)
                    mp_image = mp.Image(
                        image_format=mp.ImageFormat.SRGB,
                        data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                    )
                    landmarker.detect_async(mp_image, timestamp_ms)

                    # Emit a copy of the raw BGR frame for marker detection.
                    # Must copy: the frame buffer is reused by cap.read() on the
                    # next iteration, so a queued signal would see corrupted data.
                    self.raw_frame_ready.emit(frame.copy())

                    # Draw skeleton and emit display frame
                    with self._lock:
                        lm = self._latest_landmarks
                    qimg = self._renderer.draw(frame, lm)
                    self.frame_ready.emit(qimg)
            finally:
                cap.release()

    def stop(self):
        self._running = False
        self.wait()
