"""PoseCard — reusable widget showing one pose in the profile editor."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QFrame,
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont

from app.widgets.threshold_slider import ThresholdSlider


class PoseCard(QFrame):
    edit_requested = Signal(str)    # pose id
    delete_requested = Signal(str)  # pose id

    def __init__(self, pose, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("PoseCard")
        self.setStyleSheet(
            "#PoseCard { background:#252535; border:1px solid #3a3a4a; border-radius:8px; }"
        )
        self._pose = pose

        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)

        # Info column
        info = QVBoxLayout()
        self._name_lbl = QLabel(pose.name)
        self._name_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))

        key_text = " + ".join(pose.keystroke.keys) if pose.keystroke.keys else "— unassigned —"
        mode_text = f"[{pose.keystroke.mode}]"
        self._key_lbl = QLabel(f"{key_text}  {mode_text}")
        self._key_lbl.setStyleSheet("color:#888;")

        self._threshold_slider = ThresholdSlider(pose.threshold)
        self._threshold_slider.value_changed.connect(self._on_threshold_change)

        info.addWidget(self._name_lbl)
        info.addWidget(self._key_lbl)

        thresh_row = QHBoxLayout()
        thresh_row.addWidget(QLabel("Threshold:"))
        thresh_row.addWidget(self._threshold_slider)
        info.addLayout(thresh_row)

        outer.addLayout(info, stretch=1)

        # Buttons column
        btns = QVBoxLayout()
        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(64)
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self._pose.id))
        del_btn = QPushButton("Delete")
        del_btn.setFixedWidth(64)
        del_btn.setStyleSheet("color:#f38ba8;")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._pose.id))
        btns.addWidget(edit_btn)
        btns.addWidget(del_btn)
        btns.addStretch()
        outer.addLayout(btns)

    def _on_threshold_change(self, value: float):
        self._pose.threshold = value

    def refresh(self, pose):
        self._pose = pose
        self._name_lbl.setText(pose.name)
        key_text = " + ".join(pose.keystroke.keys) if pose.keystroke.keys else "— unassigned —"
        self._key_lbl.setText(f"{key_text}  [{pose.keystroke.mode}]")
        self._threshold_slider.set_value(pose.threshold)
