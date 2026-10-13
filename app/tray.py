"""PoseKeysTray — QSystemTrayIcon wrapper."""
from __future__ import annotations

from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QPixmap, QColor
from PySide6.QtCore import Signal, QObject
import os


def _fallback_icon() -> QIcon:
    """Create a simple green square icon if no asset is found."""
    px = QPixmap(32, 32)
    px.fill(QColor("#a6e3a1"))
    return QIcon(px)


class PoseKeysTray(QSystemTrayIcon):
    open_requested = Signal()
    pause_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "assets", "icon.png"
        )
        icon = QIcon(icon_path) if os.path.exists(icon_path) else _fallback_icon()
        super().__init__(icon, parent)

        self._paused = False

        menu = QMenu()
        self._open_action = menu.addAction("Open PoseKeys")
        self._open_action.triggered.connect(self.open_requested)
        menu.addSeparator()
        self._pause_action = menu.addAction("Pause Detection")
        self._pause_action.triggered.connect(self._toggle_pause)
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self.quit_requested)

        self.setContextMenu(menu)
        self.setToolTip("PoseKeys — idle")
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_requested.emit()

    def _toggle_pause(self):
        self._paused = not self._paused
        self.pause_requested.emit()
        self._pause_action.setText("Resume Detection" if self._paused else "Pause Detection")

    def set_status(self, profile_name: str, active: bool, paused: bool = False):
        state = "paused" if paused else ("detecting" if active else "idle")
        self.setToolTip(f"PoseKeys — {profile_name} — {state}")
