"""MainWindow — full PoseKeys UI: Live View + Profiles tabs, tray, detection loop."""
from __future__ import annotations

import json
import os

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QTabWidget,
    QLabel, QVBoxLayout, QHBoxLayout, QPushButton,
    QComboBox, QScrollArea, QProgressBar, QMessageBox,
    QInputDialog, QFileDialog, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtGui import QPixmap, QIcon, QColor, QPainter, QPen

from app.camera_thread import CameraThread
from app.skeleton_renderer import SkeletonRenderer
from app.pose_matcher import PoseMatcher
from app.keystroke_engine import KeystrokeEngine
from app.zone_engine import ZoneEngine
from app.finger_detector import FingerDetector
from app.sequence_engine import SequenceEngine
from app.marker_tracker import MarkerTracker, MARKER_INDEX_OFFSET
from app.voice_engine import VoiceEngine
from app.profile_store import (
    ProfileStore, Profile, Pose, Keystroke, ZoneRule, FingerRule, SequenceRule,
    VoiceRule,
)
from app.pose_capture import PoseCaptureDialog
from app.key_recorder_dialog import KeyRecorderDialog
from app.zone_editor_dialog import ZoneEditorDialog
from app.finger_rule_dialog import FingerRuleDialog
from app.sequence_rule_dialog import SequenceRuleDialog
from app.voice_rule_dialog import VoiceRuleDialog
from app.tray import PoseKeysTray
from app.widgets.pose_card import PoseCard
from app.widgets.threshold_slider import ThresholdSlider

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PoseKeys")
        self.resize(1100, 720)

        # Core services
        self._store = ProfileStore()
        self._engine = KeystrokeEngine()
        self._zone_engine = ZoneEngine(self._engine)
        self._sequence_engine = SequenceEngine(self._engine)
        self._finger_detector = FingerDetector(parent=self)
        self._finger_detector.finger_counts.connect(self._on_finger_counts)
        self._marker_tracker = MarkerTracker(parent=self)
        self._voice_engine: VoiceEngine | None = None
        self._camera: CameraThread | None = None
        self._profiles: list[Profile] = []
        self._active_profile: Profile | None = None
        self._detecting = False
        self._paused = False
        self._live_landmarks = None
        self._live_finger_counts: dict = {"left": 0, "right": 0}

        # Per-pose matchers: pose_id → PoseMatcher (each has its own smoothing buffer)
        self._matchers: dict[str, PoseMatcher] = {}

        # Score bars: pose_id → _ThresholdBar
        self._score_bars: dict[str, "_ThresholdBar"] = {}

        # Zone trigger states: zone_id → bool (for overlay colouring)
        self._zone_states: dict[str, bool] = {}

        # Finger rule active state: rule_id → bool
        self._finger_states: dict[str, bool] = {}

        # Sequence progress: rule_id → current cursor int (for status display)
        self._seq_progress: dict[str, int] = {}

        # Voice rule active: rule_id → bool (for card highlight)
        self._voice_states: dict[str, bool] = {}

        self._build_ui()
        self._setup_tray()
        self._load_profiles()
        self._start_camera()
        self._restore_config()

    # ══════════════════════════════════════════════════════════════════════
    # UI construction
    # ══════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        self._tabs.addTab(self._build_live_tab(), "Live View")
        self._tabs.addTab(self._build_profiles_tab(), "Profiles")

    # ── Live View ─────────────────────────────────────────────────────────
    def _build_live_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)

        # Camera feed
        left = QVBoxLayout()
        self._feed_label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self._feed_label.setFixedSize(720, 540)
        self._feed_label.setStyleSheet("background:#000; border-radius:6px;")
        left.addWidget(self._feed_label)

        # Global sensitivity
        sens_row = QHBoxLayout()
        sens_row.addWidget(QLabel("Global sensitivity:"))
        self._global_slider = ThresholdSlider(0.75)
        sens_row.addWidget(self._global_slider)
        left.addLayout(sens_row)

        # Button row: camera toggle + detection toggle
        btn_row = QHBoxLayout()

        self._camera_btn = QPushButton("📷  Camera On")
        self._camera_btn.setStyleSheet(
            "background:#89dceb; color:#1e1e2e; font-weight:bold; padding:6px 14px; border-radius:6px;"
        )
        self._camera_btn.clicked.connect(self._toggle_camera)
        btn_row.addWidget(self._camera_btn)

        self._detect_btn = QPushButton("▶  Start Detection")
        self._detect_btn.setStyleSheet(
            "background:#a6e3a1; color:#1e1e2e; font-weight:bold; padding:6px 14px; border-radius:6px;"
        )
        self._detect_btn.clicked.connect(self._toggle_detection)
        btn_row.addWidget(self._detect_btn)

        left.addLayout(btn_row)

        layout.addLayout(left)

        # Right panel — tabbed: Pose Scores | Zones
        right_tabs = QTabWidget()
        right_tabs.setFixedWidth(310)

        # ── Pose Scores sub-tab ──────────────────────────────────────────
        scores_outer = QWidget()
        scores_outer_layout = QVBoxLayout(scores_outer)
        scores_outer_layout.setContentsMargins(4, 4, 4, 4)
        scores_outer_layout.addWidget(QLabel("<b>Pose Match Scores</b>"))
        self._scores_container = QVBoxLayout()
        self._scores_container.setAlignment(Qt.AlignmentFlag.AlignTop)
        scores_widget = QWidget()
        scores_widget.setLayout(self._scores_container)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(scores_widget)
        scores_outer_layout.addWidget(scroll, stretch=1)
        right_tabs.addTab(scores_outer, "Poses")

        # ── Zones sub-tab ────────────────────────────────────────────────
        zones_outer = QWidget()
        zones_outer_layout = QVBoxLayout(zones_outer)
        zones_outer_layout.setContentsMargins(4, 4, 4, 4)
        zones_outer_layout.addWidget(QLabel("<b>Zone Triggers</b>"))

        self._zones_list_layout = QVBoxLayout()
        self._zones_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        zones_content = QWidget()
        zones_content.setLayout(self._zones_list_layout)
        zones_scroll = QScrollArea()
        zones_scroll.setWidgetResizable(True)
        zones_scroll.setWidget(zones_content)
        zones_outer_layout.addWidget(zones_scroll, stretch=1)

        add_zone_btn = QPushButton("＋  Add Zone")
        add_zone_btn.setStyleSheet(
            "background:#cba6f7; color:#1e1e2e; font-weight:bold; "
            "padding:5px 10px; border-radius:6px;"
        )
        add_zone_btn.clicked.connect(self._add_zone)
        zones_outer_layout.addWidget(add_zone_btn)
        right_tabs.addTab(zones_outer, "Zones")

        # ── Fingers sub-tab ──────────────────────────────────────────────
        fingers_outer = QWidget()
        fingers_outer_layout = QVBoxLayout(fingers_outer)
        fingers_outer_layout.setContentsMargins(4, 4, 4, 4)

        # Live finger count display
        self._finger_display = QLabel("✋ L: 0   R: 0")
        self._finger_display.setStyleSheet(
            "font-size:16px; font-weight:bold; color:#f9e2af; padding:4px;"
        )
        fingers_outer_layout.addWidget(self._finger_display)
        fingers_outer_layout.addWidget(QLabel("<b>Finger Count Rules</b>"))

        self._finger_rules_layout = QVBoxLayout()
        self._finger_rules_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        fr_content = QWidget()
        fr_content.setLayout(self._finger_rules_layout)
        fr_scroll = QScrollArea()
        fr_scroll.setWidgetResizable(True)
        fr_scroll.setWidget(fr_content)
        fingers_outer_layout.addWidget(fr_scroll, stretch=1)

        add_finger_btn = QPushButton("＋  Add Finger Rule")
        add_finger_btn.setStyleSheet(
            "background:#f9e2af; color:#1e1e2e; font-weight:bold; "
            "padding:5px 10px; border-radius:6px;"
        )
        add_finger_btn.clicked.connect(self._add_finger_rule)
        fingers_outer_layout.addWidget(add_finger_btn)
        right_tabs.addTab(fingers_outer, "Fingers")

        # ── Sequences sub-tab ────────────────────────────────────────────
        seq_outer = QWidget()
        seq_outer_layout = QVBoxLayout(seq_outer)
        seq_outer_layout.setContentsMargins(4, 4, 4, 4)
        seq_outer_layout.addWidget(QLabel("<b>Pose Sequences</b>"))

        self._seq_rules_layout = QVBoxLayout()
        self._seq_rules_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        seq_content = QWidget()
        seq_content.setLayout(self._seq_rules_layout)
        seq_scroll = QScrollArea()
        seq_scroll.setWidgetResizable(True)
        seq_scroll.setWidget(seq_content)
        seq_outer_layout.addWidget(seq_scroll, stretch=1)

        add_seq_btn = QPushButton("＋  Add Sequence")
        add_seq_btn.setStyleSheet(
            "background:#89b4fa; color:#1e1e2e; font-weight:bold; "
            "padding:5px 10px; border-radius:6px;"
        )
        add_seq_btn.clicked.connect(self._add_sequence_rule)
        seq_outer_layout.addWidget(add_seq_btn)
        right_tabs.addTab(seq_outer, "Sequences")

        # ── Voice sub-tab ────────────────────────────────────────────────
        voice_outer = QWidget()
        voice_outer_layout = QVBoxLayout(voice_outer)
        voice_outer_layout.setContentsMargins(4, 4, 4, 4)

        # Status row
        self._voice_status_lbl = QLabel("🎤  Off")
        self._voice_status_lbl.setStyleSheet(
            "font-size:13px; font-weight:bold; color:#585b70; padding:2px;"
        )
        voice_outer_layout.addWidget(self._voice_status_lbl)

        # Live transcript display
        self._voice_transcript_lbl = QLabel("", alignment=Qt.AlignmentFlag.AlignCenter)
        self._voice_transcript_lbl.setStyleSheet(
            "background:#1a1a2e; border:1px solid #444; border-radius:4px; "
            "color:#cba6f7; font-size:10px; padding:3px;"
        )
        self._voice_transcript_lbl.setFixedHeight(24)
        self._voice_transcript_lbl.setWordWrap(False)
        voice_outer_layout.addWidget(self._voice_transcript_lbl)

        voice_outer_layout.addWidget(QLabel("<b>Voice Rules</b>"))

        self._voice_rules_layout = QVBoxLayout()
        self._voice_rules_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        voice_content = QWidget()
        voice_content.setLayout(self._voice_rules_layout)
        voice_scroll = QScrollArea()
        voice_scroll.setWidgetResizable(True)
        voice_scroll.setWidget(voice_content)
        voice_outer_layout.addWidget(voice_scroll, stretch=1)

        add_voice_btn = QPushButton("＋  Add Voice Rule")
        add_voice_btn.setStyleSheet(
            "background:#f38ba8; color:#1e1e2e; font-weight:bold; "
            "padding:5px 10px; border-radius:6px;"
        )
        add_voice_btn.clicked.connect(self._add_voice_rule)
        voice_outer_layout.addWidget(add_voice_btn)
        right_tabs.addTab(voice_outer, "Voice")

        layout.addWidget(right_tabs)

        return w

    # ── Profiles tab ──────────────────────────────────────────────────────
    def _build_profiles_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Profile selector row
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Active profile:"))
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(200)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        top_row.addWidget(self._profile_combo, stretch=1)

        new_btn = QPushButton("+ New Profile")
        new_btn.clicked.connect(self._new_profile)
        del_profile_btn = QPushButton("Delete Profile")
        del_profile_btn.setStyleSheet("color:#f38ba8;")
        del_profile_btn.clicked.connect(self._delete_profile)
        import_btn = QPushButton("Import…")
        import_btn.clicked.connect(self._import_profile)
        export_btn = QPushButton("Export…")
        export_btn.clicked.connect(self._export_profile)

        for b in (new_btn, del_profile_btn, import_btn, export_btn):
            top_row.addWidget(b)
        layout.addLayout(top_row)

        # Pose list
        self._pose_scroll_content = QWidget()
        self._pose_list_layout = QVBoxLayout(self._pose_scroll_content)
        self._pose_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._pose_scroll_content)
        layout.addWidget(scroll, stretch=1)

        add_pose_btn = QPushButton("+ Add Pose")
        add_pose_btn.setStyleSheet(
            "background:#89b4fa; color:#1e1e2e; font-weight:bold; padding:6px 14px; border-radius:6px;"
        )
        add_pose_btn.clicked.connect(self._add_pose)
        layout.addWidget(add_pose_btn)

        return w

    # ══════════════════════════════════════════════════════════════════════
    # Camera
    # ══════════════════════════════════════════════════════════════════════
    def _start_camera(self):
        self._camera = CameraThread(camera_index=0, parent=self)
        self._camera.frame_ready.connect(self._on_frame)
        self._camera.landmarks_ready.connect(self._on_landmarks)
        self._camera.error.connect(self._on_camera_error)
        self._camera.start()
        self._finger_detector.attach(self._camera)
        self._marker_tracker.attach(self._camera)
        self._camera_btn.setText("📷  Camera On")
        self._camera_btn.setStyleSheet(
            "background:#89dceb; color:#1e1e2e; font-weight:bold; padding:6px 14px; border-radius:6px;"
        )

    def _stop_camera(self):
        self._finger_detector.detach()
        self._marker_tracker.detach()
        if self._camera:
            self._camera.stop()
            self._camera = None
        self._feed_label.clear()
        self._feed_label.setStyleSheet("background:#000; border-radius:6px;")
        self._live_landmarks = None
        self._live_finger_counts = {"left": 0, "right": 0}
        self._camera_btn.setText("📷  Camera Off")
        self._camera_btn.setStyleSheet(
            "background:#45475a; color:#cdd6f4; font-weight:bold; padding:6px 14px; border-radius:6px;"
        )

    def _toggle_camera(self):
        if self._camera is None:
            self._start_camera()
        else:
            if self._detecting:
                self._stop_detection()
            self._stop_camera()

    def _on_frame(self, qimage):
        pixmap = QPixmap.fromImage(qimage).scaled(
            self._feed_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Overlay zones
        if self._active_profile and self._active_profile.zones:
            pixmap = _draw_zones_overlay(
                pixmap,
                self._active_profile.zones,
                self._zone_states,
            )
        # Overlay detected ArUco markers as cyan crosshairs
        markers = self._marker_tracker.latest()
        if markers:
            pixmap = _draw_markers_overlay(pixmap, markers, self._zone_states,
                                           self._active_profile.zones if self._active_profile else [])
        self._feed_label.setPixmap(pixmap)

    def _on_landmarks(self, landmarks):
        self._live_landmarks = landmarks
        if self._detecting and not self._paused and self._active_profile:
            self._run_detection(landmarks)

    def _on_finger_counts(self, counts: dict):
        self._live_finger_counts = counts
        self._finger_display.setText(
            f"✋ L: {counts.get('left', 0)}   R: {counts.get('right', 0)}"
        )
        if self._detecting and not self._paused and self._active_profile:
            self._run_finger_detection(counts)

    def _on_camera_error(self, msg: str):
        QMessageBox.critical(self, "Camera Error", msg)

    # ══════════════════════════════════════════════════════════════════════
    # Detection loop
    # ══════════════════════════════════════════════════════════════════════
    def _run_detection(self, landmarks):
        if not self._active_profile:
            return
        # Pose matching — track rising edges for sequence engine
        rising_poses: list[str] = []
        for pose in self._active_profile.poses:
            matcher = self._matchers.setdefault(pose.id, PoseMatcher())
            score = matcher.compare_and_smooth(landmarks, pose.landmarks)
            threshold = pose.threshold
            was_active = self._engine._get_state(pose.id)["active"]  # noqa: SLF001
            self._engine.update(pose.id, score, threshold, pose.keystroke.__dict__)
            now_active = score >= threshold
            if now_active and not was_active:
                rising_poses.append(pose.id)
            bar = self._score_bars.get(pose.id)
            if bar:
                bar.set_score(score)
        # Sequence detection — notify on every rising-edge pose
        if self._active_profile.sequence_rules and rising_poses:
            for pid in rising_poses:
                self._sequence_engine.notify_pose_active(
                    pid, self._active_profile.sequence_rules
                )
            self._update_seq_progress()
        # Zone detection — merge body landmarks + synthetic marker landmarks
        if self._active_profile.zones:
            markers = self._marker_tracker.latest()
            # Extend landmarks list: body landmarks at 0-32, markers at 100-115.
            # Fill the gap with None so index-based access works.
            merged = list(landmarks)
            if markers:
                max_marker_idx = max(m.marker_id for m in markers)
                needed = MARKER_INDEX_OFFSET + max_marker_idx + 1
                while len(merged) < needed:
                    merged.append(None)
                for m in markers:
                    merged[MARKER_INDEX_OFFSET + m.marker_id] = m
            self._zone_states = self._zone_engine.update(
                self._active_profile.zones, merged
            )

    def _run_finger_detection(self, counts: dict):
        """Evaluate FingerRules against the current live finger counts."""
        if not self._active_profile:
            return
        for rule in self._active_profile.finger_rules:
            left_count  = counts.get("left",  0)
            right_count = counts.get("right", 0)
            if rule.hand == "left":
                triggered = (left_count == rule.finger_count)
            elif rule.hand == "right":
                triggered = (right_count == rule.finger_count)
            else:  # any
                triggered = (left_count == rule.finger_count or
                             right_count == rule.finger_count)
            self._engine.update(rule.id, 1.0 if triggered else 0.0, 1.0,
                                rule.keystroke.__dict__)
            self._finger_states[rule.id] = triggered
        self._refresh_finger_rule_cards()

    def _update_seq_progress(self):
        if not self._active_profile:
            return
        for rule in self._active_profile.sequence_rules:
            self._seq_progress[rule.id] = self._sequence_engine.progress(rule.id)
        self._refresh_seq_rule_cards()

    def _toggle_detection(self):
        if self._detecting:
            self._stop_detection()
        else:
            self._start_detection()

    def _start_detection(self):
        if not self._active_profile:
            QMessageBox.warning(self, "No Profile", "Select or create a profile first.")
            return
        self._detecting = True
        self._paused = False
        self._detect_btn.setText("⏹  Stop Detection")
        self._detect_btn.setStyleSheet(
            "background:#f38ba8; color:#1e1e2e; font-weight:bold; padding:6px 14px; border-radius:6px;"
        )
        self._tray.show()
        self._tray.set_status(self._active_profile.name, True)
        # Start voice engine if there are voice rules
        self._start_voice_engine()

    def _stop_detection(self):
        self._detecting = False
        self._engine.release_all()
        self._zone_engine.release_all()
        self._sequence_engine.reset()
        self._zone_states.clear()
        self._finger_states.clear()
        self._seq_progress.clear()
        self._voice_states.clear()
        self._stop_voice_engine()
        self._detect_btn.setText("▶  Start Detection")
        self._detect_btn.setStyleSheet(
            "background:#a6e3a1; color:#1e1e2e; font-weight:bold; padding:6px 14px; border-radius:6px;"
        )
        if self._active_profile:
            self._tray.set_status(self._active_profile.name, False)

    # ── Voice engine lifecycle ────────────────────────────────────────────
    def _start_voice_engine(self):
        if not self._active_profile or not self._active_profile.voice_rules:
            return
        if self._voice_engine and self._voice_engine.isRunning():
            self._voice_engine.set_rules(self._active_profile.voice_rules)
            return
        self._voice_engine = VoiceEngine(parent=self)
        self._voice_engine.set_rules(self._active_profile.voice_rules)
        self._voice_engine.set_keystroke_engine(self._engine)
        self._voice_engine.phrase_heard.connect(self._on_phrase_heard)
        self._voice_engine.partial_heard.connect(self._on_voice_partial)
        self._voice_engine.rule_fired.connect(self._on_voice_rule_fired)
        self._voice_engine.status_changed.connect(self._on_voice_status)
        self._voice_engine.start()

    def _stop_voice_engine(self):
        if self._voice_engine:
            self._voice_engine.stop_listening()
            self._voice_engine.wait(2000)
            self._voice_engine = None
        self._voice_status_lbl.setText("🎤  Off")
        self._voice_status_lbl.setStyleSheet(
            "font-size:13px; font-weight:bold; color:#585b70; padding:2px;"
        )

    def _on_phrase_heard(self, text: str):
        self._voice_transcript_lbl.setText(f"✓ \"{text}\"")

    def _on_voice_partial(self, text: str):
        self._voice_transcript_lbl.setText(f"… {text}")

    def _on_voice_status(self, status: str):
        if status == "listening":
            self._voice_status_lbl.setText("🎤  Listening")
            self._voice_status_lbl.setStyleSheet(
                "font-size:13px; font-weight:bold; color:#a6e3a1; padding:2px;"
            )
        else:
            self._voice_status_lbl.setText(f"🎤  {status.capitalize()}")
            self._voice_status_lbl.setStyleSheet(
                "font-size:13px; font-weight:bold; color:#585b70; padding:2px;"
            )

    def _on_voice_rule_fired(self, rule_id: str):
        self._voice_states[rule_id] = True
        self._refresh_voice_rule_cards()
        # Flash for 1 s then clear
        QTimer.singleShot(1000, lambda: self._voice_states.update({rule_id: False})
                          or self._refresh_voice_rule_cards())

    # ══════════════════════════════════════════════════════════════════════
    # Tray
    # ══════════════════════════════════════════════════════════════════════
    def _setup_tray(self):
        self._tray = PoseKeysTray(parent=self)
        self._tray.open_requested.connect(self._show_window)
        self._tray.pause_requested.connect(self._toggle_pause)
        self._tray.quit_requested.connect(self.close)

    def _show_window(self):
        self.showNormal()
        self.activateWindow()

    def _toggle_pause(self):
        self._paused = not self._paused
        if self._active_profile:
            self._tray.set_status(self._active_profile.name, self._detecting, self._paused)
        if not self._paused:
            pass  # detection resumes automatically on next landmarks_ready signal

    # ══════════════════════════════════════════════════════════════════════
    # Profiles
    # ══════════════════════════════════════════════════════════════════════
    def _load_profiles(self):
        self._profiles = self._store.load_all()
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        for p in self._profiles:
            self._profile_combo.addItem(p.name)
        self._profile_combo.blockSignals(False)
        if self._profiles:
            self._set_active_profile(self._profiles[0])

    def _on_profile_selected(self, index: int):
        if 0 <= index < len(self._profiles):
            self._set_active_profile(self._profiles[index])

    def _set_active_profile(self, profile: Profile):
        self._active_profile = profile
        self._sequence_engine.reset()
        self._rebuild_pose_list()
        self._rebuild_score_bars()
        self._rebuild_zones_list()
        self._rebuild_finger_rules_list()
        self._rebuild_seq_rules_list()
        self._rebuild_voice_rules_list()
        self._save_config()

    def _new_profile(self):
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if not ok or not name.strip():
            return
        p = Profile(name=name.strip())
        self._store.save(p)
        self._profiles.append(p)
        self._profile_combo.addItem(p.name)
        self._profile_combo.setCurrentIndex(len(self._profiles) - 1)

    def _delete_profile(self):
        if not self._active_profile:
            return
        ans = QMessageBox.question(
            self, "Delete Profile",
            f"Delete profile '{self._active_profile.name}'? This cannot be undone.",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._store.delete(self._active_profile.name)
        self._profiles.remove(self._active_profile)
        self._active_profile = None
        self._load_profiles()

    def _import_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Profile", "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            p = self._store.import_profile(path)
            self._profiles.append(p)
            self._profile_combo.addItem(p.name)
            self._profile_combo.setCurrentIndex(len(self._profiles) - 1)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", str(e))

    def _export_profile(self):
        if not self._active_profile:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Profile", f"{self._active_profile.name}.json", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            self._store.export_profile(self._active_profile.name, path)
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    # ══════════════════════════════════════════════════════════════════════
    # Poses
    # ══════════════════════════════════════════════════════════════════════
    def _add_pose(self):
        if not self._active_profile:
            QMessageBox.warning(self, "No Profile", "Select or create a profile first.")
            return
        if not self._camera:
            return

        dlg = PoseCaptureDialog(self._camera, parent=self)
        if dlg.exec() != PoseCaptureDialog.DialogCode.Accepted:
            return
        if not dlg.captured_landmarks:
            return

        # Key assignment
        key_dlg = KeyRecorderDialog(parent=self)
        if key_dlg.exec() != KeyRecorderDialog.DialogCode.Accepted:
            return
        cfg = key_dlg.keystroke_config()

        pose = Pose(
            name=dlg.pose_name(),
            landmarks=dlg.captured_landmarks,
            keystroke=Keystroke(**cfg),
        )
        self._active_profile.poses.append(pose)
        self._store.save(self._active_profile)
        self._rebuild_pose_list()
        self._rebuild_score_bars()

    def _edit_pose(self, pose_id: str):
        if not self._active_profile:
            return
        pose = next((p for p in self._active_profile.poses if p.id == pose_id), None)
        if not pose:
            return
        key_dlg = KeyRecorderDialog(
            initial_config=pose.keystroke.__dict__, parent=self
        )
        if key_dlg.exec() != KeyRecorderDialog.DialogCode.Accepted:
            return
        cfg = key_dlg.keystroke_config()
        pose.keystroke = Keystroke(**cfg)
        self._store.save(self._active_profile)
        self._rebuild_pose_list()

    def _delete_pose(self, pose_id: str):
        if not self._active_profile:
            return
        self._active_profile.poses = [
            p for p in self._active_profile.poses if p.id != pose_id
        ]
        self._store.save(self._active_profile)
        self._rebuild_pose_list()
        self._rebuild_score_bars()

    # ══════════════════════════════════════════════════════════════════════
    # Zones
    # ══════════════════════════════════════════════════════════════════════
    def _add_zone(self):
        if not self._active_profile:
            QMessageBox.warning(self, "No Profile", "Select or create a profile first.")
            return
        if not self._camera:
            QMessageBox.warning(self, "Camera off", "Turn the camera on first.")
            return
        dlg = ZoneEditorDialog(self._camera, marker_tracker=self._marker_tracker, parent=self)
        if dlg.exec() != ZoneEditorDialog.DialogCode.Accepted:
            return
        zone = dlg.zone()
        self._active_profile.zones.append(zone)
        self._store.save(self._active_profile)
        self._rebuild_zones_list()

    def _edit_zone(self, zone_id: str):
        if not self._active_profile or not self._camera:
            return
        zone = next((z for z in self._active_profile.zones if z.id == zone_id), None)
        if not zone:
            return
        dlg = ZoneEditorDialog(self._camera, existing=zone,
                               marker_tracker=self._marker_tracker, parent=self)
        if dlg.exec() != ZoneEditorDialog.DialogCode.Accepted:
            return
        updated = dlg.zone()
        updated.id = zone_id  # preserve the original id
        idx = next(i for i, z in enumerate(self._active_profile.zones) if z.id == zone_id)
        self._active_profile.zones[idx] = updated
        self._store.save(self._active_profile)
        self._rebuild_zones_list()

    def _delete_zone(self, zone_id: str):
        if not self._active_profile:
            return
        self._active_profile.zones = [
            z for z in self._active_profile.zones if z.id != zone_id
        ]
        self._store.save(self._active_profile)
        self._rebuild_zones_list()

    def _rebuild_zones_list(self):
        while self._zones_list_layout.count():
            item = self._zones_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._active_profile:
            return
        for zone in self._active_profile.zones:
            card = _ZoneCard(zone, parent=None)
            card.edit_requested.connect(self._edit_zone)
            card.delete_requested.connect(self._delete_zone)
            self._zones_list_layout.addWidget(card)

    # ══════════════════════════════════════════════════════════════════════
    # Finger Rules
    # ══════════════════════════════════════════════════════════════════════
    def _add_finger_rule(self):
        if not self._active_profile:
            QMessageBox.warning(self, "No Profile", "Select or create a profile first.")
            return
        dlg = FingerRuleDialog(parent=self)
        if dlg.exec() != FingerRuleDialog.DialogCode.Accepted:
            return
        self._active_profile.finger_rules.append(dlg.rule())
        self._store.save(self._active_profile)
        self._rebuild_finger_rules_list()

    def _edit_finger_rule(self, rule_id: str):
        if not self._active_profile:
            return
        rule = next((r for r in self._active_profile.finger_rules if r.id == rule_id), None)
        if not rule:
            return
        dlg = FingerRuleDialog(existing=rule, parent=self)
        if dlg.exec() != FingerRuleDialog.DialogCode.Accepted:
            return
        updated = dlg.rule()
        updated.id = rule_id
        idx = next(i for i, r in enumerate(self._active_profile.finger_rules) if r.id == rule_id)
        self._active_profile.finger_rules[idx] = updated
        self._store.save(self._active_profile)
        self._rebuild_finger_rules_list()

    def _delete_finger_rule(self, rule_id: str):
        if not self._active_profile:
            return
        self._active_profile.finger_rules = [
            r for r in self._active_profile.finger_rules if r.id != rule_id
        ]
        self._store.save(self._active_profile)
        self._rebuild_finger_rules_list()

    def _rebuild_finger_rules_list(self):
        while self._finger_rules_layout.count():
            item = self._finger_rules_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._active_profile:
            return
        for rule in self._active_profile.finger_rules:
            card = _FingerRuleCard(rule, parent=None)
            card.edit_requested.connect(self._edit_finger_rule)
            card.delete_requested.connect(self._delete_finger_rule)
            self._finger_rules_layout.addWidget(card)

    def _refresh_finger_rule_cards(self):
        """Update active highlight on all finger rule cards without full rebuild."""
        for i in range(self._finger_rules_layout.count()):
            w = self._finger_rules_layout.itemAt(i).widget()
            if isinstance(w, _FingerRuleCard):
                w.set_active(self._finger_states.get(w.rule_id, False))

    # ══════════════════════════════════════════════════════════════════════
    # Sequence Rules
    # ══════════════════════════════════════════════════════════════════════
    def _add_sequence_rule(self):
        if not self._active_profile:
            QMessageBox.warning(self, "No Profile", "Select or create a profile first.")
            return
        if not self._active_profile.poses:
            QMessageBox.warning(self, "No Poses", "Add at least 2 poses to the profile first.")
            return
        dlg = SequenceRuleDialog(self._active_profile.poses, parent=self)
        if dlg.exec() != SequenceRuleDialog.DialogCode.Accepted:
            return
        self._active_profile.sequence_rules.append(dlg.rule())
        self._store.save(self._active_profile)
        self._rebuild_seq_rules_list()

    def _edit_sequence_rule(self, rule_id: str):
        if not self._active_profile:
            return
        rule = next((r for r in self._active_profile.sequence_rules if r.id == rule_id), None)
        if not rule:
            return
        dlg = SequenceRuleDialog(self._active_profile.poses, existing=rule, parent=self)
        if dlg.exec() != SequenceRuleDialog.DialogCode.Accepted:
            return
        updated = dlg.rule()
        updated.id = rule_id
        idx = next(i for i, r in enumerate(self._active_profile.sequence_rules) if r.id == rule_id)
        self._active_profile.sequence_rules[idx] = updated
        self._store.save(self._active_profile)
        self._rebuild_seq_rules_list()

    def _delete_sequence_rule(self, rule_id: str):
        if not self._active_profile:
            return
        self._active_profile.sequence_rules = [
            r for r in self._active_profile.sequence_rules if r.id != rule_id
        ]
        self._store.save(self._active_profile)
        self._rebuild_seq_rules_list()

    def _rebuild_seq_rules_list(self):
        while self._seq_rules_layout.count():
            item = self._seq_rules_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._active_profile:
            return
        pose_names = {p.id: p.name for p in self._active_profile.poses}
        for rule in self._active_profile.sequence_rules:
            card = _SeqRuleCard(rule, pose_names, parent=None)
            card.edit_requested.connect(self._edit_sequence_rule)
            card.delete_requested.connect(self._delete_sequence_rule)
            self._seq_rules_layout.addWidget(card)

    def _refresh_seq_rule_cards(self):
        """Update progress display on all sequence rule cards."""
        if not self._active_profile:
            return
        pose_names = {p.id: p.name for p in self._active_profile.poses}
        for i in range(self._seq_rules_layout.count()):
            w = self._seq_rules_layout.itemAt(i).widget()
            if isinstance(w, _SeqRuleCard):
                cursor = self._seq_progress.get(w.rule_id, 0)
                w.set_progress(cursor, pose_names)

    # ══════════════════════════════════════════════════════════════════════
    # Voice Rules
    # ══════════════════════════════════════════════════════════════════════
    def _add_voice_rule(self):
        if not self._active_profile:
            QMessageBox.warning(self, "No Profile", "Select or create a profile first.")
            return
        engine = self._voice_engine if (self._voice_engine and self._voice_engine.isRunning()) else None
        dlg = VoiceRuleDialog(voice_engine=engine, parent=self)
        if dlg.exec() != VoiceRuleDialog.DialogCode.Accepted:
            return
        self._active_profile.voice_rules.append(dlg.rule())
        self._store.save(self._active_profile)
        self._rebuild_voice_rules_list()
        # If detection is running, update the engine's rule list
        if self._voice_engine:
            self._voice_engine.set_rules(self._active_profile.voice_rules)

    def _edit_voice_rule(self, rule_id: str):
        if not self._active_profile:
            return
        rule = next((r for r in self._active_profile.voice_rules if r.id == rule_id), None)
        if not rule:
            return
        engine = self._voice_engine if (self._voice_engine and self._voice_engine.isRunning()) else None
        dlg = VoiceRuleDialog(existing=rule, voice_engine=engine, parent=self)
        if dlg.exec() != VoiceRuleDialog.DialogCode.Accepted:
            return
        updated = dlg.rule()
        updated.id = rule_id
        idx = next(i for i, r in enumerate(self._active_profile.voice_rules) if r.id == rule_id)
        self._active_profile.voice_rules[idx] = updated
        self._store.save(self._active_profile)
        self._rebuild_voice_rules_list()
        if self._voice_engine:
            self._voice_engine.set_rules(self._active_profile.voice_rules)

    def _delete_voice_rule(self, rule_id: str):
        if not self._active_profile:
            return
        self._active_profile.voice_rules = [
            r for r in self._active_profile.voice_rules if r.id != rule_id
        ]
        self._store.save(self._active_profile)
        self._rebuild_voice_rules_list()
        if self._voice_engine:
            self._voice_engine.set_rules(self._active_profile.voice_rules)

    def _rebuild_voice_rules_list(self):
        while self._voice_rules_layout.count():
            item = self._voice_rules_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._active_profile:
            return
        for rule in self._active_profile.voice_rules:
            card = _VoiceRuleCard(rule, parent=None)
            card.edit_requested.connect(self._edit_voice_rule)
            card.delete_requested.connect(self._delete_voice_rule)
            self._voice_rules_layout.addWidget(card)

    def _refresh_voice_rule_cards(self):
        for i in range(self._voice_rules_layout.count()):
            w = self._voice_rules_layout.itemAt(i).widget()
            if isinstance(w, _VoiceRuleCard):
                w.set_active(self._voice_states.get(w.rule_id, False))

    # ══════════════════════════════════════════════════════════════════════
    # UI rebuild helpers
    # ══════════════════════════════════════════════════════════════════════
    def _rebuild_pose_list(self):
        # Clear
        while self._pose_list_layout.count():
            item = self._pose_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._active_profile:
            return

        for pose in self._active_profile.poses:
            card = PoseCard(pose, parent=self._pose_scroll_content)
            card.edit_requested.connect(self._edit_pose)
            card.delete_requested.connect(self._delete_pose)
            self._pose_list_layout.addWidget(card)

    def _rebuild_score_bars(self):
        # Clear old bars and reset matchers for poses that are gone
        while self._scores_container.count():
            item = self._scores_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._score_bars.clear()
        self._matchers.clear()

        if not self._active_profile:
            return

        for pose in self._active_profile.poses:
            row = QWidget()
            rl = QVBoxLayout(row)
            rl.setContentsMargins(0, 4, 0, 4)

            lbl = QLabel(pose.name)
            lbl.setStyleSheet("font-size:11px; color:#cdd6f4;")
            rl.addWidget(lbl)

            bar = _ThresholdBar(pose.threshold, parent=row)

            def _make_threshold_handler(p, b):
                def _on_threshold(val: float):
                    p.threshold = val
                    b.set_threshold(val)
                    if self._active_profile:
                        self._store.save(self._active_profile)
                return _on_threshold

            bar.threshold_changed.connect(_make_threshold_handler(pose, bar))
            rl.addWidget(bar)
            self._scores_container.addWidget(row)
            self._score_bars[pose.id] = bar

    # ══════════════════════════════════════════════════════════════════════
    # Config persistence
    # ══════════════════════════════════════════════════════════════════════
    def _save_config(self):
        cfg = {"last_profile": self._active_profile.name if self._active_profile else ""}
        try:
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f)
        except Exception:
            pass

    def _restore_config(self):
        if not os.path.exists(_CONFIG_PATH):
            return
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
            last = cfg.get("last_profile", "")
            for i, p in enumerate(self._profiles):
                if p.name == last:
                    self._profile_combo.setCurrentIndex(i)
                    break
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════
    # Shutdown
    # ══════════════════════════════════════════════════════════════════════
    def closeEvent(self, event):  # noqa: N802
        self._engine.release_all()
        self._stop_voice_engine()
        if self._camera:
            self._camera.stop()
            self._camera = None
        self._tray.hide()
        event.accept()


# ══════════════════════════════════════════════════════════════════════════════
# _ThresholdBar — score bar with a draggable threshold line and slider
# ══════════════════════════════════════════════════════════════════════════════
class _ThresholdBar(QWidget):
    """Compound widget: a filled score bar with a visible threshold line + slider."""

    from PySide6.QtCore import Signal as _Signal
    threshold_changed = _Signal(float)

    def __init__(self, threshold: float = 0.75, parent=None):
        super().__init__(parent)
        self._score: float = 0.0
        self._threshold: float = threshold

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Custom painted bar
        self._canvas = _BarCanvas(self._score, self._threshold, parent=self)
        self._canvas.setFixedHeight(22)
        layout.addWidget(self._canvas)

        # Threshold slider row
        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(0, 0, 0, 0)
        thresh_lbl = QLabel("Trigger at:")
        thresh_lbl.setStyleSheet("font-size:10px; color:#888;")
        slider_row.addWidget(thresh_lbl)

        from app.widgets.threshold_slider import ThresholdSlider
        self._slider = ThresholdSlider(threshold, parent=self)
        self._slider.value_changed.connect(self._on_slider)
        slider_row.addWidget(self._slider)
        layout.addLayout(slider_row)

    def _on_slider(self, val: float):
        self._threshold = val
        self._canvas.set_threshold(val)
        self.threshold_changed.emit(val)

    def set_score(self, score: float):
        self._score = score
        self._canvas.set_score(score)

    def set_threshold(self, val: float):
        self._threshold = val
        self._slider.set_value(val)
        self._canvas.set_threshold(val)


class _BarCanvas(QWidget):
    """Paints a filled bar + a vertical threshold line."""

    def __init__(self, score: float, threshold: float, parent=None):
        super().__init__(parent)
        self._score = score
        self._threshold = threshold

    def set_score(self, score: float):
        self._score = score
        self.update()

    def set_threshold(self, threshold: float):
        self._threshold = threshold
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1a1a2e"))
        p.drawRoundedRect(0, 0, w, h, 4, 4)

        # Filled portion — green if above threshold, blue otherwise
        fill_w = max(0, int(w * self._score))
        color = QColor("#a6e3a1") if self._score >= self._threshold else QColor("#89b4fa")
        p.setBrush(color)
        p.drawRoundedRect(0, 0, fill_w, h, 4, 4)

        # Threshold line — bright yellow vertical bar
        tx = int(w * self._threshold)
        pen = QPen(QColor("#f9e2af"), 2)
        p.setPen(pen)
        p.drawLine(tx, 0, tx, h)

        # Score label
        p.setPen(QColor("#ffffff"))
        font = self.font()
        font.setPointSize(8)
        p.setFont(font)
        p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, f"{int(self._score * 100)}%")

        p.end()


# ══════════════════════════════════════════════════════════════════════════════
# _ZoneCard — compact row in the Zones panel
# ══════════════════════════════════════════════════════════════════════════════
class _ZoneCard(QWidget):
    from PySide6.QtCore import Signal as _Signal
    edit_requested = _Signal(str)    # zone id
    delete_requested = _Signal(str)  # zone id

    def __init__(self, zone: "ZoneRule", parent=None):
        super().__init__(parent)
        self._zone = zone
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        info = QVBoxLayout()
        name_lbl = QLabel(f"<b>{zone.name}</b>")
        name_lbl.setStyleSheet("font-size:11px;")
        keys = zone.keystroke.keys
        key_text = " + ".join(k.capitalize() for k in keys) if keys else "— unassigned —"
        key_lbl = QLabel(f"{key_text}  [{zone.keystroke.mode}]")
        key_lbl.setStyleSheet("font-size:10px; color:#888;")
        rect_lbl = QLabel(
            f"x={zone.x:.2f}  y={zone.y:.2f}  "
            f"w={zone.w:.2f}  h={zone.h:.2f}"
        )
        rect_lbl.setStyleSheet("font-size:9px; color:#585b70;")
        info.addWidget(name_lbl)
        info.addWidget(key_lbl)
        info.addWidget(rect_lbl)
        layout.addLayout(info, stretch=1)

        btn_col = QVBoxLayout()
        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(50)
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self._zone.id))
        del_btn = QPushButton("Del")
        del_btn.setFixedWidth(50)
        del_btn.setStyleSheet("color:#f38ba8;")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._zone.id))
        btn_col.addWidget(edit_btn)
        btn_col.addWidget(del_btn)
        layout.addLayout(btn_col)

        self.setStyleSheet(
            "background:#252535; border:1px solid #3a3a4a; border-radius:6px; margin:2px;"
        )


# ══════════════════════════════════════════════════════════════════════════════
# _draw_zones_overlay — paints zone rectangles onto a QPixmap copy
# ══════════════════════════════════════════════════════════════════════════════
def _draw_zones_overlay(
    pixmap: "QPixmap",
    zones: list,
    states: dict,
) -> "QPixmap":
    """Return a copy of *pixmap* with zone rectangles painted on top."""
    result = QPixmap(pixmap)
    p = QPainter(result)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w, h = result.width(), result.height()

    for zone in zones:
        triggered = states.get(zone.id, False)
        # Green when triggered, purple otherwise
        color = QColor("#a6e3a1") if triggered else QColor("#cba6f7")
        fill = QColor(color)
        fill.setAlpha(40 if triggered else 25)

        rx = int(zone.x * w)
        ry = int(zone.y * h)
        rw = int(zone.w * w)
        rh = int(zone.h * h)

        p.setPen(QPen(color, 2))
        p.setBrush(fill)
        p.drawRect(rx, ry, rw, rh)

        # Zone label
        p.setPen(QColor("#ffffff"))
        font = p.font()
        font.setPointSize(8)
        font.setBold(True)
        p.setFont(font)
        p.drawText(rx + 4, ry + 14, zone.name)

    p.end()
    return result


# ══════════════════════════════════════════════════════════════════════════════
# _draw_markers_overlay — paint ArUco marker crosshairs onto the live feed
# ══════════════════════════════════════════════════════════════════════════════
def _draw_markers_overlay(
    pixmap: "QPixmap",
    markers: list,
    zone_states: dict,
    zones: list,
) -> "QPixmap":
    """Paint a cyan crosshair + ID label for each detected ArUco marker.

    If the marker's landmark index matches a triggered zone, the crosshair
    turns green.
    """
    from app.marker_tracker import marker_landmark_index
    result = QPixmap(pixmap)
    p = QPainter(result)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w, h = result.width(), result.height()

    for m in markers:
        # Is this marker inside any triggered zone?
        midx = marker_landmark_index(m.marker_id)
        in_triggered_zone = any(
            zone_states.get(z.id, False) and midx in z.landmark_indices
            for z in zones
        )
        color = QColor("#a6e3a1") if in_triggered_zone else QColor("#89dceb")

        px = int(m.x * w)
        py = int(m.y * h)
        arm = 14

        # Crosshair
        p.setPen(QPen(color, 2))
        p.drawLine(px - arm, py, px + arm, py)
        p.drawLine(px, py - arm, px, py + arm)

        # Centre dot
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(px - 3, py - 3, 6, 6)

        # ID badge
        p.setPen(QColor("#ffffff"))
        from PySide6.QtGui import QFont as _QFont
        font = _QFont("Segoe UI", 8, _QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(px + arm + 3, py + 4, f"Marker #{m.marker_id}")

    p.end()
    return result


# ══════════════════════════════════════════════════════════════════════════════
# _FingerRuleCard — compact row in the Fingers panel
# ══════════════════════════════════════════════════════════════════════════════
class _FingerRuleCard(QWidget):
    from PySide6.QtCore import Signal as _Signal
    edit_requested = _Signal(str)
    delete_requested = _Signal(str)

    _ICONS = {0: "✊", 1: "☝", 2: "✌", 3: "🤟", 4: "🖐", 5: "🖐"}

    def __init__(self, rule: "FingerRule", parent=None):
        super().__init__(parent)
        self.rule_id = rule.id
        self._rule = rule
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        icon = self._ICONS.get(rule.finger_count, "🖐")
        info = QVBoxLayout()
        name_lbl = QLabel(f"<b>{rule.name}</b>  {icon} × {rule.finger_count}  ({rule.hand})")
        name_lbl.setStyleSheet("font-size:11px;")
        keys = rule.keystroke.keys
        key_text = " + ".join(k.capitalize() for k in keys) if keys else "— unassigned —"
        key_lbl = QLabel(f"{key_text}  [{rule.keystroke.mode}]")
        key_lbl.setStyleSheet("font-size:10px; color:#888;")
        info.addWidget(name_lbl)
        info.addWidget(key_lbl)
        layout.addLayout(info, stretch=1)

        btn_col = QVBoxLayout()
        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(50)
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.rule_id))
        del_btn = QPushButton("Del")
        del_btn.setFixedWidth(50)
        del_btn.setStyleSheet("color:#f38ba8;")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.rule_id))
        btn_col.addWidget(edit_btn)
        btn_col.addWidget(del_btn)
        layout.addLayout(btn_col)

        self._base_style = (
            "border:1px solid #3a3a4a; border-radius:6px; margin:2px;"
        )
        self.setStyleSheet(f"background:#252535; {self._base_style}")

    def set_active(self, active: bool):
        bg = "#2d4a2d" if active else "#252535"
        self.setStyleSheet(f"background:{bg}; {self._base_style}")


# ══════════════════════════════════════════════════════════════════════════════
# _SeqRuleCard — compact row in the Sequences panel
# ══════════════════════════════════════════════════════════════════════════════
class _SeqRuleCard(QWidget):
    from PySide6.QtCore import Signal as _Signal
    edit_requested = _Signal(str)
    delete_requested = _Signal(str)

    def __init__(self, rule: "SequenceRule", pose_names: dict, parent=None):
        super().__init__(parent)
        self.rule_id = rule.id
        self._rule = rule
        self._total = len(rule.pose_ids)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        top_row = QHBoxLayout()
        self._name_lbl = QLabel(f"<b>{rule.name}</b>")
        self._name_lbl.setStyleSheet("font-size:11px;")
        top_row.addWidget(self._name_lbl, stretch=1)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(50)
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.rule_id))
        del_btn = QPushButton("Del")
        del_btn.setFixedWidth(50)
        del_btn.setStyleSheet("color:#f38ba8;")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.rule_id))
        top_row.addWidget(edit_btn)
        top_row.addWidget(del_btn)
        layout.addLayout(top_row)

        steps = " → ".join(
            pose_names.get(pid, pid[:8]) for pid in rule.pose_ids
        )
        self._steps_lbl = QLabel(steps)
        self._steps_lbl.setStyleSheet("font-size:9px; color:#585b70;")
        self._steps_lbl.setWordWrap(True)
        layout.addWidget(self._steps_lbl)

        keys = rule.keystroke.keys
        key_text = " + ".join(k.capitalize() for k in keys) if keys else "— unassigned —"
        key_lbl = QLabel(f"→ {key_text}  [{rule.keystroke.mode}]  "
                         f"({rule.window_sec:.1f}s window)")
        key_lbl.setStyleSheet("font-size:10px; color:#888;")
        layout.addWidget(key_lbl)

        # Progress bar
        self._prog_lbl = QLabel("Step 0 / " + str(self._total))
        self._prog_lbl.setStyleSheet("font-size:10px; color:#cba6f7;")
        layout.addWidget(self._prog_lbl)

        self._base_style = "border:1px solid #3a3a4a; border-radius:6px; margin:2px;"
        self.setStyleSheet(f"background:#252535; {self._base_style}")

    def set_progress(self, cursor: int, pose_names: dict):
        self._prog_lbl.setText(f"Step {cursor} / {self._total}")
        if cursor > 0:
            self._prog_lbl.setStyleSheet("font-size:10px; color:#a6e3a1;")
        else:
            self._prog_lbl.setStyleSheet("font-size:10px; color:#cba6f7;")


# ══════════════════════════════════════════════════════════════════════════════
# _VoiceRuleCard — compact row in the Voice panel
# ══════════════════════════════════════════════════════════════════════════════
class _VoiceRuleCard(QWidget):
    from PySide6.QtCore import Signal as _Signal
    edit_requested = _Signal(str)
    delete_requested = _Signal(str)

    def __init__(self, rule: "VoiceRule", parent=None):
        super().__init__(parent)
        self.rule_id = rule.id
        self._rule = rule

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)

        info = QVBoxLayout()

        match_type = "exact" if rule.exact else "contains"
        name_lbl = QLabel(f'<b>{rule.name}</b>  🎤  "{rule.phrase}"  [{match_type}]')
        name_lbl.setStyleSheet("font-size:11px;")

        keys = rule.keystroke.keys
        key_text = " + ".join(k.capitalize() for k in keys) if keys else "⚠ unassigned ⚠"
        key_lbl = QLabel(f"{key_text}  [{rule.keystroke.mode}]  cooldown: {rule.cooldown:.1f}s")
        key_lbl.setStyleSheet("font-size:10px; color:#888;")

        info.addWidget(name_lbl)
        info.addWidget(key_lbl)
        layout.addLayout(info, stretch=1)

        btn_col = QVBoxLayout()
        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(50)
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.rule_id))
        del_btn = QPushButton("Del")
        del_btn.setFixedWidth(50)
        del_btn.setStyleSheet("color:#f38ba8;")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self.rule_id))
        btn_col.addWidget(edit_btn)
        btn_col.addWidget(del_btn)
        layout.addLayout(btn_col)

        self._base_style = "border:1px solid #3a3a4a; border-radius:6px; margin:2px;"
        self.setStyleSheet(f"background:#252535; {self._base_style}")

    def set_active(self, active: bool):
        bg = "#2d4a2d" if active else "#252535"
        self.setStyleSheet(f"background:{bg}; {self._base_style}")
