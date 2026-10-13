"""ZoneEditorDialog — draw a zone rectangle on the live camera feed and assign a keystroke.

Usage
-----
    dlg = ZoneEditorDialog(camera_thread, parent=self)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        zone = dlg.zone()          # ZoneRule with normalised coords + keystroke
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QMessageBox, QCheckBox, QScrollArea, QWidget, QGridLayout,
    QGroupBox,
)
from PySide6.QtCore import Qt, QRect, QPoint, QRectF
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QFont, QCursor

from app.profile_store import ZoneRule, Keystroke
from app.key_recorder_dialog import KeyRecorderDialog
from app.marker_tracker import marker_landmark_index, marker_name, MAX_MARKER_ID

# MediaPipe 33-point body landmark names (index → short label)
_LM_NAMES: dict[int, str] = {
    0: "Nose", 1: "L.Eye(in)", 2: "L.Eye", 3: "L.Eye(out)", 4: "R.Eye(in)",
    5: "R.Eye", 6: "R.Eye(out)", 7: "L.Ear", 8: "R.Ear",
    9: "L.Mouth", 10: "R.Mouth",
    11: "L.Shoulder", 12: "R.Shoulder",
    13: "L.Elbow", 14: "R.Elbow",
    15: "L.Wrist", 16: "R.Wrist",
    17: "L.Pinky", 18: "R.Pinky", 19: "L.Index", 20: "R.Index",
    21: "L.Thumb", 22: "R.Thumb",
    23: "L.Hip", 24: "R.Hip",
    25: "L.Knee", 26: "R.Knee",
    27: "L.Ankle", 28: "R.Ankle",
    29: "L.Heel", 30: "R.Heel",
    31: "L.Foot", 32: "R.Foot",
}

# Convenient grouped presets shown as toggle buttons
# Row 0 = body parts, Row 1 = ArUco markers
_PRESETS_BODY: list[tuple[str, list[int]]] = [
    ("Hands",       [15, 16, 17, 18, 19, 20, 21, 22]),
    ("Wrists",      [15, 16]),
    ("Elbows",      [13, 14]),
    ("Shoulders",   [11, 12]),
    ("Hips",        [23, 24]),
    ("Knees",       [25, 26]),
    ("Ankles",      [27, 28]),
    ("Feet",        [29, 30, 31, 32]),
    ("Head",        [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
    ("Full Body",   []),   # empty = any body landmark
]
_PRESETS_MARKERS: list[tuple[str, list[int]]] = [
    (marker_name(i), [marker_landmark_index(i)]) for i in range(4)
]
_PRESETS = _PRESETS_BODY + _PRESETS_MARKERS


class ZoneEditorDialog(QDialog):
    """Modal dialog. Click-drag on the camera image to draw the zone rectangle."""

    def __init__(self, camera_thread, existing: ZoneRule | None = None,
                 marker_tracker=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Zone Editor")
        self.setModal(True)
        self.resize(780, 700)

        self._camera_thread = camera_thread
        self._marker_tracker = marker_tracker
        self._last_qimage: QImage | None = None
        self._frozen_pixmap: QPixmap | None = None
        self._frozen = False

        self._drag_start: QPoint | None = None
        self._drag_rect: QRect | None = None

        self._norm_rect: tuple[float, float, float, float] | None = None

        self._keystroke: Keystroke = Keystroke()
        self._selected_indices: list[int] = []

        if existing:
            self._norm_rect = (existing.x, existing.y, existing.w, existing.h)
            self._keystroke = existing.keystroke
            self._selected_indices = list(existing.landmark_indices)

        self._build_ui()

        if existing:
            self._name_edit.setText(existing.name)
            self._update_key_badge()
            self._update_preset_buttons()

        self._camera_thread.frame_ready.connect(self._on_frame)
        if self._marker_tracker:
            self._marker_tracker.markers_ready.connect(self._on_markers)

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Name row
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Zone name:"))
        self._name_edit = QLineEdit(placeholderText="e.g. Left zone")
        name_row.addWidget(self._name_edit, stretch=1)
        layout.addLayout(name_row)

        # Instruction label
        self._instr_lbl = QLabel(
            "Click and drag on the image below to draw the trigger zone.",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self._instr_lbl.setStyleSheet("color:#cba6f7; font-size:11px;")
        layout.addWidget(self._instr_lbl)

        # Camera canvas
        self._canvas = _ZoneCanvas(self)
        self._canvas.setFixedSize(720, 400)
        self._canvas.setStyleSheet("background:#000; border-radius:6px;")
        self._canvas.rect_drawn.connect(self._on_rect_drawn)
        layout.addWidget(self._canvas, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Body-part + marker preset buttons (two rows)
        preset_box = QGroupBox("Trigger when this part/marker enters the zone")
        preset_box.setStyleSheet("QGroupBox { font-size:11px; color:#cdd6f4; }")
        preset_grid = QGridLayout(preset_box)
        preset_grid.setSpacing(4)
        self._preset_btns: dict[str, QPushButton] = {}
        for col, (label, indices) in enumerate(_PRESETS_BODY):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                "QPushButton { border:1px solid #555; border-radius:4px; padding:2px 6px; }"
                "QPushButton:checked { background:#cba6f7; color:#1e1e2e; }"
            )
            btn.clicked.connect(lambda checked, lbl=label, idx=indices: self._on_preset(lbl, idx))
            preset_grid.addWidget(btn, 0, col)
            self._preset_btns[label] = btn
        for col, (label, indices) in enumerate(_PRESETS_MARKERS):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                "QPushButton { border:1px solid #89dceb; border-radius:4px; padding:2px 6px; }"
                "QPushButton:checked { background:#89dceb; color:#1e1e2e; }"
            )
            btn.clicked.connect(lambda checked, lbl=label, idx=indices: self._on_preset(lbl, idx))
            preset_grid.addWidget(btn, 1, col)
            self._preset_btns[label] = btn
        layout.addWidget(preset_box)

        # Keystroke row
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("Keystroke:"))
        self._key_badge = QLabel("— none —")
        self._key_badge.setStyleSheet(
            "background:#2a2a3e; border:1px solid #555; border-radius:4px; padding:3px 8px;"
            "font-family:Consolas; font-size:13px;"
        )
        key_row.addWidget(self._key_badge, stretch=1)
        assign_btn = QPushButton("Assign…")
        assign_btn.clicked.connect(self._assign_keystroke)
        key_row.addWidget(assign_btn)
        layout.addLayout(key_row)

        # OK / Cancel
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Save Zone")
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

        # Draw existing rect if editing
        if self._norm_rect:
            self._canvas.set_norm_rect(self._norm_rect)

    # ── Camera ────────────────────────────────────────────────────────────
    def _on_frame(self, qimage: QImage):
        self._last_qimage = qimage
        pixmap = QPixmap.fromImage(qimage).scaled(
            self._canvas.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._canvas.set_frame(pixmap)

    def _on_markers(self, markers: list):
        """Forward live marker positions to the canvas for overlay."""
        self._canvas.set_markers(markers)

    # ── Rect drawn callback ───────────────────────────────────────────────
    def _on_rect_drawn(self, rect: QRect):
        """Called by _ZoneCanvas when the user finishes dragging. rect is in label pixels."""
        cw, ch = self._canvas.width(), self._canvas.height()
        if cw == 0 or ch == 0:
            return
        # Keep normalised coords clamped to [0,1]
        x = max(0.0, min(1.0, rect.x() / cw))
        y = max(0.0, min(1.0, rect.y() / ch))
        w = max(0.01, min(1.0 - x, rect.width() / cw))
        h = max(0.01, min(1.0 - y, rect.height() / ch))
        self._norm_rect = (x, y, w, h)
        self._instr_lbl.setText(
            f"Zone: x={x:.2f}  y={y:.2f}  w={w:.2f}  h={h:.2f}   "
            "Drag again to redraw."
        )

    # ── Presets ───────────────────────────────────────────────────────────
    def _on_preset(self, label: str, indices: list[int]):
        # Deselect all others
        for lbl, btn in self._preset_btns.items():
            btn.setChecked(lbl == label)
        self._selected_indices = list(indices)

    def _update_preset_buttons(self):
        """Check the preset button whose indices match _selected_indices."""
        for label, indices in _PRESETS:
            self._preset_btns[label].setChecked(
                sorted(indices) == sorted(self._selected_indices)
            )

    # ── Keystroke ─────────────────────────────────────────────────────────
    def _assign_keystroke(self):
        dlg = KeyRecorderDialog(
            initial_config=self._keystroke.__dict__, parent=self
        )
        if dlg.exec() == KeyRecorderDialog.DialogCode.Accepted:
            cfg = dlg.keystroke_config()
            self._keystroke = Keystroke(**cfg)
            self._update_key_badge()

    def _update_key_badge(self):
        keys = self._keystroke.keys
        if keys:
            self._key_badge.setText(
                " + ".join(k.capitalize() for k in keys)
                + f"  [{self._keystroke.mode}]"
            )
        else:
            self._key_badge.setText("— none —")

    # ── Accept ────────────────────────────────────────────────────────────
    def _do_accept(self):
        if not self._name_edit.text().strip():
            QMessageBox.warning(self, "Name required", "Please enter a zone name.")
            return
        if not self._norm_rect:
            QMessageBox.warning(self, "No zone drawn", "Draw a rectangle on the camera image first.")
            return
        self.accept()

    def zone(self) -> ZoneRule:
        """Call after exec() == Accepted to retrieve the completed ZoneRule."""
        x, y, w, h = self._norm_rect
        return ZoneRule(
            name=self._name_edit.text().strip(),
            x=x, y=y, w=w, h=h,
            landmark_indices=list(self._selected_indices),
            keystroke=self._keystroke,
        )

    def closeEvent(self, event):  # noqa: N802
        self._camera_thread.frame_ready.disconnect(self._on_frame)
        if self._marker_tracker:
            try:
                self._marker_tracker.markers_ready.disconnect(self._on_markers)
            except Exception:
                pass
        super().closeEvent(event)


# ── Canvas widget ─────────────────────────────────────────────────────────────
class _ZoneCanvas(QWidget):
    """Displays the camera feed and lets the user drag a rectangle."""

    from PySide6.QtCore import Signal as _Signal
    rect_drawn = _Signal(QRect)  # emitted when drag is released

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setMouseTracking(True)
        self._pixmap: QPixmap | None = None
        self._drag_start: QPoint | None = None
        self._drag_rect: QRect | None = None
        self._final_rect: QRect | None = None
        self._markers: list = []   # latest _MarkerLandmark list for overlay

    def set_frame(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self.update()

    def set_markers(self, markers: list):
        self._markers = markers
        self.update()

    def set_norm_rect(self, norm: tuple[float, float, float, float]):
        """Display a rect from normalised coords (for editing existing zone)."""
        x, y, w, h = norm
        self._final_rect = QRect(
            int(x * self.width()), int(y * self.height()),
            int(w * self.width()), int(h * self.height()),
        )
        self.update()

    # ── Mouse events ──────────────────────────────────────────────────────
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.pos()
            self._drag_rect = QRect(self._drag_start, self._drag_start)
            self._final_rect = None
            self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_start is not None:
            self._drag_rect = QRect(self._drag_start, event.pos()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            rect = QRect(self._drag_start, event.pos()).normalized()
            self._final_rect = rect
            self._drag_start = None
            self._drag_rect = None
            self.update()
            if rect.width() > 4 and rect.height() > 4:
                self.rect_drawn.emit(rect)

    # ── Paint ─────────────────────────────────────────────────────────────
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Camera frame
        if self._pixmap:
            p.drawPixmap(0, 0, self._pixmap)
        else:
            p.fillRect(self.rect(), QColor("#000"))

        # Committed zone (solid border + translucent fill)
        if self._final_rect:
            self._draw_zone_rect(p, self._final_rect, QColor("#cba6f7"), alpha=50)

        # Rubber-band while dragging (dashed line, no fill)
        if self._drag_rect:
            pen = QPen(QColor("#f9e2af"), 2, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self._drag_rect)

        # ArUco marker crosshairs — cyan + with ID label
        if self._markers:
            w, h = self.width(), self.height()
            for m in self._markers:
                px = int(m.x * w)
                py = int(m.y * h)
                arm = 12
                p.setPen(QPen(QColor("#89dceb"), 2))
                p.drawLine(px - arm, py, px + arm, py)
                p.drawLine(px, py - arm, px, py + arm)
                p.setPen(QColor("#89dceb"))
                font = QFont("Segoe UI", 8, QFont.Weight.Bold)
                p.setFont(font)
                p.drawText(px + arm + 2, py - 2, f"#{m.marker_id}")

        p.end()

    @staticmethod
    def _draw_zone_rect(p: QPainter, rect: QRect, color: QColor, alpha: int = 50):
        fill = QColor(color)
        fill.setAlpha(alpha)
        p.setBrush(fill)
        pen = QPen(color, 2)
        p.setPen(pen)
        p.drawRect(rect)

        # Corner label
        p.setPen(QColor("#ffffff"))
        font = QFont("Segoe UI", 8)
        p.setFont(font)
        p.drawText(rect.x() + 4, rect.y() + 14, "ZONE")
