"""SequenceRuleDialog — build a pose sequence "cheat code" with a keystroke reward."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QDoubleSpinBox,
    QComboBox, QMessageBox, QAbstractItemView,
)
from PySide6.QtCore import Qt

from app.profile_store import SequenceRule, Keystroke, Pose
from app.key_recorder_dialog import KeyRecorderDialog


class SequenceRuleDialog(QDialog):
    """Dialog to create or edit a SequenceRule.

    poses: the list of Pose objects in the current profile (to populate the step picker).
    """

    def __init__(self, poses: list[Pose], existing: SequenceRule | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pose Sequence (Cheat Code)")
        self.setModal(True)
        self.resize(440, 420)

        self._poses = poses
        self._keystroke = Keystroke()
        # ordered list of pose_ids in the sequence
        self._step_ids: list[str] = []

        if existing:
            self._keystroke = existing.keystroke
            self._step_ids = list(existing.pose_ids)

        self._pose_by_id = {p.id: p for p in poses}
        self._build_ui()

        if existing:
            self._name_edit.setText(existing.name)
            self._window_spin.setValue(existing.window_sec)
            self._rebuild_step_list()
            self._update_badge()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Sequence name:"))
        self._name_edit = QLineEdit(placeholderText="e.g. Arms Up then Down")
        name_row.addWidget(self._name_edit, stretch=1)
        layout.addLayout(name_row)

        # Step picker
        layout.addWidget(QLabel("Steps (in order):"))
        step_row = QHBoxLayout()
        self._pose_combo = QComboBox()
        for p in self._poses:
            self._pose_combo.addItem(p.name, p.id)
        step_row.addWidget(self._pose_combo, stretch=1)
        add_step_btn = QPushButton("+ Add Step")
        add_step_btn.clicked.connect(self._add_step)
        step_row.addWidget(add_step_btn)
        layout.addLayout(step_row)

        # Step list
        self._step_list = QListWidget()
        self._step_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._step_list.setFixedHeight(140)
        self._step_list.setStyleSheet(
            "QListWidget { background:#1e1e2e; border:1px solid #444; border-radius:4px; }"
            "QListWidget::item { padding:4px; color:#cdd6f4; }"
            "QListWidget::item:selected { background:#313244; }"
        )
        layout.addWidget(self._step_list)

        remove_btn = QPushButton("Remove selected step")
        remove_btn.setStyleSheet("color:#f38ba8;")
        remove_btn.clicked.connect(self._remove_step)
        layout.addWidget(remove_btn)

        # Window
        win_row = QHBoxLayout()
        win_row.addWidget(QLabel("Time window (seconds):"))
        self._window_spin = QDoubleSpinBox()
        self._window_spin.setRange(0.5, 30.0)
        self._window_spin.setSingleStep(0.5)
        self._window_spin.setValue(3.0)
        win_row.addWidget(self._window_spin)
        win_row.addStretch()
        layout.addLayout(win_row)

        # Keystroke
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Reward keystroke:"))
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
        ok_btn = QPushButton("Save Sequence")
        ok_btn.setStyleSheet(
            "background:#a6e3a1; color:#1e1e2e; font-weight:bold; "
            "padding:5px 14px; border-radius:6px;"
        )
        ok_btn.clicked.connect(self._do_accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    # ── steps ────────────────────────────────────────────────────────────
    def _add_step(self):
        pose_id = self._pose_combo.currentData()
        if not pose_id:
            return
        self._step_ids.append(pose_id)
        self._rebuild_step_list()

    def _remove_step(self):
        row = self._step_list.currentRow()
        if row >= 0:
            self._step_ids.pop(row)
            self._rebuild_step_list()

    def _rebuild_step_list(self):
        self._step_list.clear()
        for i, pid in enumerate(self._step_ids):
            name = self._pose_by_id[pid].name if pid in self._pose_by_id else f"(deleted) {pid[:8]}"
            item = QListWidgetItem(f"  {i + 1}.  {name}")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self._step_list.addItem(item)

    # ── keystroke ─────────────────────────────────────────────────────────
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

    # ── accept ────────────────────────────────────────────────────────────
    def _do_accept(self):
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "Name required", "Please enter a name.")
            return
        # Re-read order from QListWidget (user may have dragged items)
        self._step_ids = [
            self._step_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._step_list.count())
        ]
        if len(self._step_ids) < 2:
            QMessageBox.warning(self, "Too short", "Add at least 2 pose steps.")
            return
        self.accept()

    def rule(self) -> SequenceRule:
        return SequenceRule(
            name=self._name_edit.text().strip(),
            pose_ids=list(self._step_ids),
            window_sec=self._window_spin.value(),
            keystroke=self._keystroke,
        )
