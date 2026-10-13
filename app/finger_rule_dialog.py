"""FingerRuleDialog — configure a FingerRule (hand + finger count + keystroke)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QSpinBox, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from app.profile_store import FingerRule, Keystroke
from app.key_recorder_dialog import KeyRecorderDialog

_HAND_LABELS = {"any": "Either hand", "left": "Left hand", "right": "Right hand"}

# Visual hand diagrams — unicode finger glyphs for the count preview
_HAND_ICONS = {0: "✊", 1: "☝", 2: "✌", 3: "🤟", 4: "🖐", 5: "🖐"}


class FingerRuleDialog(QDialog):
    def __init__(self, existing: FingerRule | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Finger Count Rule")
        self.setModal(True)
        self.setFixedSize(380, 260)

        self._keystroke = Keystroke()
        if existing:
            self._keystroke = existing.keystroke

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit(placeholderText="e.g. Five fingers")
        if existing:
            self._name_edit.setText(existing.name)
        name_row.addWidget(self._name_edit, stretch=1)
        layout.addLayout(name_row)

        # Hand selector
        hand_row = QHBoxLayout()
        hand_row.addWidget(QLabel("Hand:"))
        self._hand_combo = QComboBox()
        for key, label in _HAND_LABELS.items():
            self._hand_combo.addItem(label, key)
        if existing:
            idx = list(_HAND_LABELS.keys()).index(existing.hand)
            self._hand_combo.setCurrentIndex(idx)
        hand_row.addWidget(self._hand_combo, stretch=1)
        layout.addLayout(hand_row)

        # Finger count
        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("Finger count:"))
        self._count_spin = QSpinBox()
        self._count_spin.setRange(0, 5)
        self._count_spin.setValue(existing.finger_count if existing else 5)
        self._count_spin.valueChanged.connect(self._update_icon)
        count_row.addWidget(self._count_spin)
        self._icon_lbl = QLabel("🖐")
        self._icon_lbl.setFont(QFont("Segoe UI Emoji", 24))
        count_row.addWidget(self._icon_lbl)
        count_row.addStretch()
        layout.addLayout(count_row)

        # Keystroke
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Keystroke:"))
        self._key_badge = QLabel("— none —")
        self._key_badge.setStyleSheet(
            "background:#2a2a3e; border:1px solid #555; border-radius:4px; "
            "padding:3px 8px; font-family:Consolas; font-size:12px;"
        )
        key_row.addWidget(self._key_badge, stretch=1)
        assign_btn = QPushButton("Assign…")
        assign_btn.clicked.connect(self._assign_keystroke)
        key_row.addWidget(assign_btn)
        layout.addLayout(key_row)

        # Buttons
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setStyleSheet(
            "background:#a6e3a1; color:#1e1e2e; font-weight:bold; padding:5px 14px; border-radius:6px;"
        )
        ok_btn.clicked.connect(self._do_accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._update_badge()
        self._update_icon(self._count_spin.value())

    # ── helpers ──────────────────────────────────────────────────────────
    def _update_icon(self, val: int):
        self._icon_lbl.setText(_HAND_ICONS.get(val, "🖐"))

    def _assign_keystroke(self):
        dlg = KeyRecorderDialog(initial_config=self._keystroke.__dict__, parent=self)
        if dlg.exec() == KeyRecorderDialog.DialogCode.Accepted:
            self._keystroke = Keystroke(**dlg.keystroke_config())
            self._update_badge()

    def _update_badge(self):
        keys = self._keystroke.keys
        if keys:
            self._key_badge.setText(
                " + ".join(k.capitalize() for k in keys) + f"  [{self._keystroke.mode}]"
            )
        else:
            self._key_badge.setText("— none —")

    def _do_accept(self):
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "Name required", "Please enter a name.")
            return
        self.accept()

    # ── result ───────────────────────────────────────────────────────────
    def rule(self) -> FingerRule:
        hand = self._hand_combo.currentData()
        return FingerRule(
            name=self._name_edit.text().strip(),
            hand=hand,
            finger_count=self._count_spin.value(),
            keystroke=self._keystroke,
        )
