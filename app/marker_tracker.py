"""MarkerTracker — detects ArUco markers in each camera frame and emits their
normalised centre positions as synthetic landmark objects compatible with
ZoneEngine.

Marker IDs 0-15 map to synthetic landmark indices 100-115, well above
MediaPipe's 33-point body range (0-32).  This lets them slot directly into
the existing zone landmark_indices system with zero changes to ZoneEngine.

Attach to a running CameraThread via  attach(camera_thread).
Subscribe to  markers_ready  Signal(list)  — list of _MarkerLandmark.

Dictionary: DICT_4X4_50 (fast, reliable, easy to print).
Print markers at: https://chev.me/arucogen/
Select "4x4" dictionary, IDs 0-3, size ~200px, print and hold up to camera.
"""
from __future__ import annotations

import threading

import cv2
import numpy as np
from PySide6.QtCore import QObject, Signal

# ── Constants ─────────────────────────────────────────────────────────────────
MARKER_INDEX_OFFSET = 100   # landmark index = 100 + marker_id
MAX_MARKER_ID = 15           # track IDs 0-15 (DICT_4X4_50 has 50 but we limit)


class _MarkerLandmark:
    """Duck-typed NormalizedLandmark for a detected ArUco marker centre.

    Compatible with ZoneEngine._zone_hit() which only reads .x, .y, .visibility.
    """
    __slots__ = ("x", "y", "z", "visibility", "marker_id")

    def __init__(self, x: float, y: float, marker_id: int):
        self.x = x
        self.y = y
        self.z = 0.0
        self.visibility = 1.0
        self.marker_id = marker_id


def marker_landmark_index(marker_id: int) -> int:
    """Return the synthetic landmark index for a given ArUco marker ID (0-15)."""
    return MARKER_INDEX_OFFSET + marker_id


def marker_name(marker_id: int) -> str:
    return f"Marker #{marker_id}"


class MarkerTracker(QObject):
    """Detects ArUco markers each frame and emits normalised centre positions.

    Usage::

        tracker = MarkerTracker(parent=self)
        tracker.attach(camera_thread)
        tracker.markers_ready.connect(my_slot)  # slot(list[_MarkerLandmark])
    """
    markers_ready = Signal(list)   # list[_MarkerLandmark]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._camera_thread = None
        self._frame_count = 0
        self._lock = threading.Lock()
        self._latest: list[_MarkerLandmark] = []

        # Build detector once — 4×4_50 dictionary
        aruco_dict   = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        aruco_params = cv2.aruco.DetectorParameters()
        self._detector = cv2.aruco.ArucoDetector(aruco_dict, aruco_params)

    # ── Public API ────────────────────────────────────────────────────────
    def attach(self, camera_thread) -> None:
        """Connect to raw_frame_ready — receives BGR numpy array directly."""
        self._camera_thread = camera_thread
        camera_thread.raw_frame_ready.connect(self._on_frame)

    def detach(self) -> None:
        if self._camera_thread:
            try:
                self._camera_thread.raw_frame_ready.disconnect(self._on_frame)
            except Exception:
                pass
            self._camera_thread = None
        with self._lock:
            self._latest = []

    def latest(self) -> list[_MarkerLandmark]:
        """Return last detected markers (thread-safe snapshot)."""
        with self._lock:
            return list(self._latest)

    # ── Internal ──────────────────────────────────────────────────────────
    def _on_frame(self, frame: np.ndarray) -> None:
        """Receive raw BGR numpy frame and detect ArUco markers.

        Tries detection on both the plain grayscale image and an
        adaptively-thresholded version so it works under varied lighting.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # First pass — plain grayscale
        corners, ids, _ = self._detector.detectMarkers(gray)

        # Second pass — adaptive threshold (helps under uneven / dim lighting)
        if ids is None or len(ids) == 0:
            thresh = cv2.adaptiveThreshold(
                gray, 255,
                cv2.ADAPTIVE_THRESH_MEAN_C,
                cv2.THRESH_BINARY, 21, 5,
            )
            corners, ids, _ = self._detector.detectMarkers(thresh)

        results: list[_MarkerLandmark] = []
        if ids is not None:
            h, w = frame.shape[:2]
            for corner_group, mid in zip(corners, ids.flatten()):
                if mid > MAX_MARKER_ID:
                    continue
                pts = corner_group[0]            # shape (4, 2)
                cx = float(np.mean(pts[:, 0])) / w
                cy = float(np.mean(pts[:, 1])) / h
                results.append(_MarkerLandmark(cx, cy, int(mid)))

        with self._lock:
            self._latest = results

        self.markers_ready.emit(results)
