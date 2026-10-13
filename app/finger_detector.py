"""FingerDetector — runs MediaPipe HandLandmarker in LIVE_STREAM mode alongside the
camera thread and counts extended fingers per hand each frame.

Emits  finger_counts  Signal(dict) with keys "left" and "right", values 0-5.
Connects to the same CameraThread frame signal so no second camera is opened.

Finger extension logic (standard tip-over-pip check):
  - Thumb:  tip.x farther from wrist than mcp (left/right-aware)
  - Others: tip.y < pip.y  (tip above pip in normalised coords)
"""
from __future__ import annotations

import concurrent.futures          # noqa: F401 — pre-load for Python 3.15
from concurrent.futures.thread import ThreadPoolExecutor as _TPE
from concurrent.futures.process import ProcessPoolExecutor as _PPE
concurrent.futures.ThreadPoolExecutor = _TPE
concurrent.futures.ProcessPoolExecutor = _PPE

import os
import sys
import threading
import time
import urllib.request

import mediapipe as mp
from PySide6.QtCore import QObject, Signal

_HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/"
    "float16/1/hand_landmarker.task"
)
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
_HAND_MODEL_PATH = os.path.join(_ASSETS_DIR, "hand_landmarker.task")

# MediaPipe hand landmark indices
_WRIST = 0
_THUMB_CMC, _THUMB_MCP, _THUMB_IP, _THUMB_TIP = 1, 2, 3, 4
_INDEX_MCP, _INDEX_PIP, _INDEX_DIP, _INDEX_TIP = 5, 6, 7, 8
_MIDDLE_MCP, _MIDDLE_PIP, _MIDDLE_DIP, _MIDDLE_TIP = 9, 10, 11, 12
_RING_MCP, _RING_PIP, _RING_DIP, _RING_TIP = 13, 14, 15, 16
_PINKY_MCP, _PINKY_PIP, _PINKY_DIP, _PINKY_TIP = 17, 18, 19, 20

_FINGER_PAIRS = [
    (_INDEX_TIP,  _INDEX_PIP),
    (_MIDDLE_TIP, _MIDDLE_PIP),
    (_RING_TIP,   _RING_PIP),
    (_PINKY_TIP,  _PINKY_PIP),
]


def _ensure_hand_model() -> str:
    os.makedirs(_ASSETS_DIR, exist_ok=True)
    if not os.path.exists(_HAND_MODEL_PATH):
        print(f"[PoseKeys] Downloading hand model to {_HAND_MODEL_PATH} …")
        urllib.request.urlretrieve(_HAND_MODEL_URL, _HAND_MODEL_PATH)
        print("[PoseKeys] Hand model downloaded.")
    return _HAND_MODEL_PATH


def _count_fingers(hand_landmarks, handedness: str) -> int:
    """Count extended fingers (0-5) for one hand.

    handedness: "Left" or "Right" as reported by MediaPipe (mirror of actual hand).
    """
    lm = hand_landmarks
    count = 0

    # Thumb — compare tip.x vs ip.x relative to wrist side
    # MediaPipe uses camera-mirror coords: "Right" hand appears on left side of image.
    wrist_x = lm[_WRIST].x
    tip_x   = lm[_THUMB_TIP].x
    ip_x    = lm[_THUMB_IP].x
    if handedness == "Right":
        # right hand in mirror: thumb tip should be to the LEFT of ip to be extended
        if tip_x < ip_x:
            count += 1
    else:
        if tip_x > ip_x:
            count += 1

    # Four fingers: tip above pip (lower y = higher in frame)
    for tip_idx, pip_idx in _FINGER_PAIRS:
        if lm[tip_idx].y < lm[pip_idx].y:
            count += 1

    return count


class FingerDetector(QObject):
    """Attach to an existing CameraThread and detect finger counts each frame.

    Usage:
        detector = FingerDetector(parent=self)
        detector.attach(camera_thread)
        detector.finger_counts.connect(my_slot)   # slot receives dict
    """
    finger_counts = Signal(dict)  # {"left": 0-5, "right": 0-5}
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._landmarker = None
        self._lock = threading.Lock()
        self._latest: dict = {"left": 0, "right": 0}
        self._camera_thread = None
        self._frame_count = 0    # only process every Nth frame to reduce CPU

    # ------------------------------------------------------------------
    def attach(self, camera_thread) -> None:
        """Connect to a running CameraThread's raw frame signal."""
        self._camera_thread = camera_thread
        try:
            model_path = _ensure_hand_model()
        except Exception as e:
            self.error.emit(f"Could not download hand model: {e}")
            return
        self._init_landmarker(model_path)
        camera_thread.frame_ready.connect(self._on_frame)

    def detach(self) -> None:
        if self._camera_thread:
            try:
                self._camera_thread.frame_ready.disconnect(self._on_frame)
            except Exception:
                pass
            self._camera_thread = None
        if self._landmarker:
            try:
                self._landmarker.close()
            except Exception:
                pass
            self._landmarker = None

    # ------------------------------------------------------------------
    def _init_landmarker(self, model_path: str) -> None:
        HandLandmarker = mp.tasks.vision.HandLandmarker
        HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
        VisionRunningMode = mp.tasks.vision.RunningMode
        BaseOptions = mp.tasks.BaseOptions

        def _on_result(result, output_image, timestamp_ms):
            counts = {"left": 0, "right": 0}
            for i, classification in enumerate(result.handedness):
                if not classification or i >= len(result.hand_landmarks):
                    continue
                label = classification[0].display_name   # "Left" or "Right"
                n = _count_fingers(result.hand_landmarks[i], label)
                key = label.lower()
                if key in counts:
                    counts[key] = n
            with self._lock:
                self._latest = counts
            self.finger_counts.emit(dict(counts))

        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=model_path),
            running_mode=VisionRunningMode.LIVE_STREAM,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            result_callback=_on_result,
        )
        self._landmarker = HandLandmarker.create_from_options(options)

    def _on_frame(self, qimage) -> None:
        """Receives QImage from CameraThread — feed to hand landmarker every 2nd frame."""
        self._frame_count += 1
        if self._frame_count % 2 != 0:
            return
        if not self._landmarker:
            return
        # Convert QImage → mediapipe Image
        import cv2, numpy as np
        from PySide6.QtGui import QImage as _QImage
        img = qimage.convertToFormat(_QImage.Format.Format_RGB888)
        ptr = img.bits()
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(img.height(), img.width(), 3).copy()
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=arr)
        try:
            self._landmarker.detect_async(mp_img, int(time.time() * 1000))
        except Exception:
            pass
