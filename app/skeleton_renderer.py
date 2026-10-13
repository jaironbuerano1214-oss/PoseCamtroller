"""SkeletonRenderer — draws the MediaPipe 33-point skeleton onto a BGR frame and returns a QImage.

Compatible with mediapipe >= 0.10.30 (Tasks API).
"""
import cv2
import numpy as np
import mediapipe as mp
from PySide6.QtGui import QImage


# Green connections, white joint dots
_CONN_COLOR = (0, 255, 0)       # BGR green
_JOINT_COLOR = (255, 255, 255)  # BGR white
_CONN_THICKNESS = 2
_JOINT_RADIUS = 4

# Tasks API connections: list of (start_idx, end_idx) tuples
_CONNECTIONS = [
    (c.start, c.end)
    for c in mp.tasks.vision.PoseLandmarksConnections.POSE_LANDMARKS
]


class SkeletonRenderer:
    def draw(self, frame_bgr: np.ndarray, landmarks) -> QImage:
        """Draw skeleton on a copy of *frame_bgr* and return as QImage.

        *landmarks* may be None (no person detected) — the frame is still returned.
        The landmark objects are mp.tasks.components.containers.NormalizedLandmark,
        which have .x, .y, .z, and .visibility attributes.
        """
        out = frame_bgr.copy()
        h, w = out.shape[:2]

        if landmarks is not None:
            # Draw connections
            for start_idx, end_idx in _CONNECTIONS:
                if start_idx >= len(landmarks) or end_idx >= len(landmarks):
                    continue
                lm_start = landmarks[start_idx]
                lm_end = landmarks[end_idx]
                vis_s = getattr(lm_start, "visibility", 1.0) or 1.0
                vis_e = getattr(lm_end, "visibility", 1.0) or 1.0
                if vis_s < 0.3 or vis_e < 0.3:
                    continue
                pt1 = (int(lm_start.x * w), int(lm_start.y * h))
                pt2 = (int(lm_end.x * w), int(lm_end.y * h))
                cv2.line(out, pt1, pt2, _CONN_COLOR, _CONN_THICKNESS, cv2.LINE_AA)

            # Draw joints
            for lm in landmarks:
                vis = getattr(lm, "visibility", 1.0) or 1.0
                if vis < 0.3:
                    continue
                pt = (int(lm.x * w), int(lm.y * h))
                cv2.circle(out, pt, _JOINT_RADIUS, _JOINT_COLOR, -1, cv2.LINE_AA)

        # BGR → RGB → QImage
        rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
        h2, w2, ch = rgb.shape
        return QImage(rgb.data.tobytes(), w2, h2, ch * w2, QImage.Format.Format_RGB888)
