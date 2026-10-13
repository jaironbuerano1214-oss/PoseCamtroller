"""PoseMatcher — bone-vector cosine similarity between live and saved landmark sets.

Compatible with mediapipe >= 0.10.30 (Tasks API).
"""
from __future__ import annotations

from collections import deque

import mediapipe as mp
import numpy as np

# Tasks API connections: list of (start_idx, end_idx) tuples
_CONNECTIONS = [
    (c.start, c.end)
    for c in mp.tasks.vision.PoseLandmarksConnections.POSE_LANDMARKS
]
_SMOOTH_WINDOW = 5


def _bone_vectors(landmarks) -> np.ndarray:
    """Return an (N, 3) array of normalised bone direction vectors from *landmarks*.

    Each row corresponds to one POSE_LANDMARKS_CONNECTIONS edge, direction = end − start,
    then unit-normalised. Zero-length bones become zero vectors (handled gracefully
    by cosine similarity).
    """
    vecs = []
    for start_idx, end_idx in _CONNECTIONS:
        if start_idx >= len(landmarks) or end_idx >= len(landmarks):
            vecs.append(np.zeros(3, dtype=np.float32))
            continue
        lm_s = landmarks[start_idx]
        lm_e = landmarks[end_idx]
        v = np.array([lm_e.x - lm_s.x, lm_e.y - lm_s.y, lm_e.z - lm_s.z], dtype=np.float32)
        norm = np.linalg.norm(v)
        if norm > 1e-6:
            v /= norm
        vecs.append(v)
    return np.array(vecs, dtype=np.float32)


def compare(live, saved) -> float:
    """Compare *live* landmarks against *saved* (list of [x,y,z,vis] lists).

    Returns a raw similarity score in [0, 1].  Stateless — no smoothing.
    """
    if live is None or saved is None:
        return 0.0
    saved_lm = [_LandmarkProxy(*row[:3]) for row in saved]
    live_vecs = _bone_vectors(live)
    saved_vecs = _bone_vectors(saved_lm)
    dots = np.sum(live_vecs * saved_vecs, axis=1)
    sims = np.clip(dots, -1.0, 1.0)
    return float(np.mean((sims + 1.0) / 2.0))


class PoseMatcher:
    """One PoseMatcher instance per pose — maintains its own smoothing buffer."""

    def __init__(self):
        self._buffer: deque[float] = deque(maxlen=_SMOOTH_WINDOW)

    def compare_and_smooth(self, live, saved) -> float:
        """Compare live landmarks against saved, smooth, and return score in [0, 1]."""
        raw = compare(live, saved)
        self._buffer.append(raw)
        return float(np.mean(self._buffer))

    def reset(self) -> None:
        self._buffer.clear()


class _LandmarkProxy:
    """Minimal duck-type for a MediaPipe NormalizedLandmark, built from saved JSON data."""
    __slots__ = ("x", "y", "z", "visibility")

    def __init__(self, x: float, y: float, z: float, visibility: float = 1.0):
        self.x = x
        self.y = y
        self.z = z
        self.visibility = visibility
