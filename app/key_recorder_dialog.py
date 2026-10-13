"""KeyRecorderDialog — capture a key combination via pynput listener."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QRadioButton, QButtonGroup,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from pynput.keyboard import Listener, Key


_MODIFIER_NAMES = {
    Key.ctrl, Key.ctrl_l, Key.ctrl_r,
    Key.shift, Key.shift_l, Key.shift_r,
    Key.alt, Key.alt_l, Key.alt_r,
    Key.cmd, Key.cmd_l, Key.cmd_r,
}

_KEY_DISPLAY: dict = {
    Key.ctrl: "Ctrl", Key.ctrl_l: "Ctrl", Key.ctrl_r: "Ctrl",
    Key.shift: "Shift", Key.shift_l: "Shift", Key.shift_r: "Shift",
    Key.alt: "Alt", Key.alt_l: "Alt", Key.alt_r: "Alt",
    Key.cmd: "Win", Key.cmd_l: "Win", Key.cmd_r: "Win",
    Key.enter: "Enter", Key.space: "Space", Key.tab: "Tab",
    Key.backspace: "Backspace", Key.delete: "Delete", Key.esc: "Esc",
    Key.up: "Up", Key.down: "Down", Key.left: "Left", Key.right: "Right",
    Key.home: "Home", Key.end: "End", Key.page_up: "PgUp", Key.page_down: "PgDn",
}
for _i in range(1, 21):
    _k = getattr(Key, f"f{_i}", None)
    if _k:
        _KEY_DISPLAY[_k] = f"F{_i}"


def _key_to_str(k) -> str:
    """Return a display string and a serialisable name for a pynput key."""
    if k in _KEY_DISPLAY:
        return _KEY_DISPLAY[k]
    if hasattr(k, "char") and k.char:
        return k.char.upper()
    return str(k)


def _key_to_name(k) -> str:
    """Return the lowercase name used in KeystrokeEngine._parse_keys."""
    display = _KEY_DISPLAY.get(k)
    if display:
        return display.lower()
    if hasattr(k, "char") and k.char:
        return k.char.lower()
    return str(k).replace("Key.", "")


class KeyRecorderDialog(QDialog):
    def __init__(self, initial_config: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Assign Keystroke")
        self.setModal(True)
        self.setFixedSize(400, 220)

        self._pressed: list = []          # pynput key objects held during recording
        self._recorded: list[str] = []    # serialisable key names
        self._listener: Listener | None = None
        self._recording = False

        layout = QVBoxLayout(self)

        # Combo display
        self._badge = QLabel("— none —", alignment=Qt.AlignmentFlag.AlignCenter)
        self._badge.setFont(QFont("Consolas", 16, QFont.Weight.Bold))
        self._badge.setStyleSheet(
            "background:#2a2a3e; border:1px solid #555; border-radius:6px; padding:8px;"
        )
        layout.addWidget(self._badge)

        # Mode radio buttons
        mode_row = QHBoxLayout()
        self._tap_radio = QRadioButton("Tap (fire once on enter)")
        self._hold_radio = QRadioButton("Hold (hold while pose active)")
        self._tap_radio.setChecked(True)
        mode_row.addWidget(self._tap_radio)
        mode_row.addWidget(self._hold_radio)
        layout.addLayout(mode_row)

        # Buttons
        btn_row = QHBoxLayout()
        self._record_btn = QPushButton("Record")
        self._record_btn.clicked.connect(self._start_recording)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self._clear)
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._record_btn)
        btn_row.addWidget(self._clear_btn)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        # Pre-populate if editing
        if initial_config:
            self._recorded = list(initial_config.get("keys", []))
            mode = initial_config.get("mode", "tap")
            self._hold_radio.setChecked(mode == "hold")
            self._update_badge()

    # ── Recording ────────────────────────────────────────────────────────
    def _start_recording(self):
        self._recording = True
        self._pressed = []
        self._recorded = []
        self._badge.setText("Press keys…")
        self._record_btn.setEnabled(False)
        self._listener = Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def _on_press(self, key):
        if key not in self._pressed:
            self._pressed.append(key)

    def _on_release(self, key):
        if not self._recording:
            return
        # Stop on the first non-modifier key release
        if key not in _MODIFIER_NAMES:
            self._recording = False
            self._recorded = [_key_to_name(k) for k in self._pressed]
            QTimer.singleShot(0, self._finish_recording)

    def _finish_recording(self):
        if self._listener:
            self._listener.stop()
            self._listener = None
        self._pressed.clear()
        self._update_badge()
        self._record_btn.setEnabled(True)

    def _clear(self):
        self._recorded = []
        self._badge.setText("— none —")

    def _update_badge(self):
        if self._recorded:
            self._badge.setText(" + ".join(k.capitalize() for k in self._recorded))
        else:
            self._badge.setText("— none —")

    # ── Result ───────────────────────────────────────────────────────────
    def keystroke_config(self) -> dict:
        mode = "hold" if self._hold_radio.isChecked() else "tap"
        return {"keys": list(self._recorded), "mode": mode}

    def closeEvent(self, event):  # noqa: N802
        if self._listener:
            self._listener.stop()
        super().closeEvent(event)
