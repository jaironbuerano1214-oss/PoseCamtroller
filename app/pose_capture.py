"""PoseCaptureDialog — live camera feed with 3-2-1 countdown and landmark snapshot."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QFont, QPainter, QColor, QImage


class PoseCaptureDialog(QDialog):
    def __init__(self, camera_thread, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Capture Pose")
        self.setModal(True)
        self.resize(680, 560)

        self._camera_thread = camera_thread
        self._last_landmarks = None
        self._last_qimage: QImage | None = None
        self.captured_landmarks: list | None = None
        self._countdown_value = 0
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._tick)

        # ── Layout ──────────────────────────────────────────────────────
        layout = QVBoxLayout(self)

        self._name_edit = QLineEdit(placeholderText="Pose name (e.g. Arms Up)")
        layout.addWidget(self._name_edit)

        self._feed_label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self._feed_label.setFixedSize(640, 420)
        self._feed_label.setStyleSheet("background:#000;")
        layout.addWidget(self._feed_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._status_label = QLabel("Press 'Capture' to start countdown.", alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        self._capture_btn = QPushButton("Capture")
        self._capture_btn.clicked.connect(self._start_countdown)
        self._save_btn = QPushButton("Save")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._do_save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._capture_btn)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        # Connect camera
        self._camera_thread.frame_ready.connect(self._on_frame)
        self._camera_thread.landmarks_ready.connect(self._on_landmarks)

    # ── Slots ────────────────────────────────────────────────────────────
    def _on_frame(self, qimage: QImage):
        self._last_qimage = qimage
        pixmap = QPixmap.fromImage(qimage).scaled(
            self._feed_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if self._countdown_value > 0:
            pixmap = self._overlay_digit(pixmap, str(self._countdown_value))
        self._feed_label.setPixmap(pixmap)

    def _on_landmarks(self, landmarks):
        self._last_landmarks = landmarks

    def _start_countdown(self):
        self._countdown_value = 3
        self._capture_btn.setEnabled(False)
        self._status_label.setText("Get into pose…")
        self._countdown_timer.start()

    def _tick(self):
        if self._countdown_value <= 1:
            self._countdown_timer.stop()
            self._countdown_value = 0
            self._snapshot()
        else:
            self._countdown_value -= 1

    def _snapshot(self):
        if not self._last_landmarks:
            self._status_label.setText("⚠ No person detected — try again.")
            self._capture_btn.setEnabled(True)
            return
        self.captured_landmarks = [
            [lm.x, lm.y, lm.z, lm.visibility] for lm in self._last_landmarks
        ]
        self._status_label.setText("✓ Pose captured! Enter a name and click Save.")
        self._save_btn.setEnabled(True)
        self._capture_btn.setEnabled(True)

    def _do_save(self):
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Name required", "Please enter a name for this pose.")
            return
        self.accept()

    def pose_name(self) -> str:
        return self._name_edit.text().strip()

    # ── Helpers ──────────────────────────────────────────────────────────
    @staticmethod
    def _overlay_digit(pixmap: QPixmap, text: str) -> QPixmap:
        result = QPixmap(pixmap)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(
            result.width() // 2 - 55, result.height() // 2 - 65, 110, 110,
            QColor(0, 0, 0, 140),
        )
        font = QFont("Segoe UI", 72, QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(result.rect(), Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        return result

    def closeEvent(self, event):  # noqa: N802
        self._countdown_timer.stop()
        self._camera_thread.frame_ready.disconnect(self._on_frame)
        self._camera_thread.landmarks_ready.disconnect(self._on_landmarks)
        super().closeEvent(event)
