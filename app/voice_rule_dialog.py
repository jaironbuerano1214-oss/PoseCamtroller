"""VoiceRuleDialog — configure a VoiceRule (phrase + match mode + cooldown + keystroke)."""
from __future__ import annotations

import json
import time

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QDoubleSpinBox, QMessageBox,
    QFrame,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from app.profile_store import VoiceRule, Keystroke
from app.key_recorder_dialog import KeyRecorderDialog


class VoiceRuleDialog(QDialog):
    """Create or edit a VoiceRule.

    Optionally accepts a live VoiceEngine instance so the user can click
    'Record' and speak the phrase — the dialog listens for the next
    completed utterance and fills the phrase field automatically.
    """

    def __init__(self, existing: VoiceRule | None = None,
                 voice_engine=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Voice Command Rule")
        self.setModal(True)
        self.setFixedSize(440, 310)

        self._keystroke = Keystroke()
        self._voice_engine = voice_engine
        self._recording = False
        self._record_timer = QTimer(self)
        self._record_timer.setSingleShot(True)
        self._record_timer.timeout.connect(self._stop_recording)

        if existing:
            self._keystroke = existing.keystroke

        self._build_ui()

        if existing:
            self._name_edit.setText(existing.name)
            self._phrase_edit.setText(existing.phrase)
            self._exact_check.setChecked(existing.exact)
            self._cooldown_spin.setValue(existing.cooldown)
            self._update_badge()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Rule name:"))
        self._name_edit = QLineEdit(placeholderText="e.g. Jokes Over")
        name_row.addWidget(self._name_edit, stretch=1)
        layout.addLayout(name_row)

        # Phrase input + record button
        phrase_row = QHBoxLayout()
        phrase_row.addWidget(QLabel("Phrase:"))
        self._phrase_edit = QLineEdit(placeholderText='e.g. jokes over')
        phrase_row.addWidget(self._phrase_edit, stretch=1)
        self._record_btn = QPushButton("🎤 Record")
        self._record_btn.setFixedWidth(90)
        self._record_btn.setCheckable(True)
        self._record_btn.clicked.connect(self._toggle_recording)
        if self._voice_engine is None:
            self._record_btn.setEnabled(False)
            self._record_btn.setToolTip("Start detection first to enable recording")
        phrase_row.addWidget(self._record_btn)
        layout.addLayout(phrase_row)

        # Live transcript feedback
        self._transcript_lbl = QLabel("", alignment=Qt.AlignmentFlag.AlignCenter)
        self._transcript_lbl.setStyleSheet(
            "background:#1a1a2e; border:1px solid #444; border-radius:4px; "
            "color:#cba6f7; font-size:11px; padding:4px;"
        )
        self._transcript_lbl.setFixedHeight(30)
        layout.addWidget(self._transcript_lbl)

        # Options row
        opts_row = QHBoxLayout()
        self._exact_check = QCheckBox("Exact match (full utterance must equal phrase)")
        opts_row.addWidget(self._exact_check)
        layout.addLayout(opts_row)

        # Cooldown
        cool_row = QHBoxLayout()
        cool_row.addWidget(QLabel("Cooldown (seconds):"))
        self._cooldown_spin = QDoubleSpinBox()
        self._cooldown_spin.setRange(0.5, 30.0)
        self._cooldown_spin.setSingleStep(0.5)
        self._cooldown_spin.setValue(2.0)
        cool_row.addWidget(self._cooldown_spin)
        cool_row.addStretch()
        layout.addLayout(cool_row)

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

        # OK / Cancel
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("OK")
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

        self._update_badge()

    # ── Recording ─────────────────────────────────────────────────────────
    def _toggle_recording(self, checked: bool):
        if checked:
            self._start_recording()
        else:
            self._stop_recording()

    def _start_recording(self):
        self._recording = True
        self._record_btn.setText("⏹ Stop")
        self._transcript_lbl.setText("Listening… say your phrase now")
        if self._voice_engine:
            self._voice_engine.phrase_heard.connect(self._on_phrase_heard)
            self._voice_engine.partial_heard.connect(self._on_partial)
        # Auto-stop after 8 s
        self._record_timer.start(8000)

    def _stop_recording(self):
        self._recording = False
        self._record_btn.setChecked(False)
        self._record_btn.setText("🎤 Record")
        self._record_timer.stop()
        if self._voice_engine:
            try:
                self._voice_engine.phrase_heard.disconnect(self._on_phrase_heard)
            except Exception:
                pass
            try:
                self._voice_engine.partial_heard.disconnect(self._on_partial)
            except Exception:
                pass
        if not self._phrase_edit.text():
            self._transcript_lbl.setText("")

    def _on_phrase_heard(self, text: str):
        """First completed utterance after recording started → fill phrase field."""
        self._phrase_edit.setText(text)
        self._transcript_lbl.setText(f"✓ Captured: \"{text}\"")
        self._stop_recording()

    def _on_partial(self, text: str):
        self._transcript_lbl.setText(f"… {text}")

    # ── Keystroke ─────────────────────────────────────────────────────────
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

    # ── Accept ────────────────────────────────────────────────────────────
    def _do_accept(self):
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "Name required", "Please enter a rule name.")
            return
        if not self._phrase_edit.text().strip():
            QMessageBox.warning(self, "Phrase required", "Please enter or record a phrase.")
            return
        self._stop_recording()
        self.accept()

    def rule(self) -> VoiceRule:
        return VoiceRule(
            name=self._name_edit.text().strip(),
            phrase=self._phrase_edit.text().strip().lower(),
            exact=self._exact_check.isChecked(),
            cooldown=self._cooldown_spin.value(),
            keystroke=self._keystroke,
        )

    def closeEvent(self, event):  # noqa: N802
        self._stop_recording()
        super().closeEvent(event)
