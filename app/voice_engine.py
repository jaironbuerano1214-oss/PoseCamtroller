"""VoiceEngine — real-time speech recognition using vosk (fully offline).

Runs a background QThread that streams mic audio through sounddevice,
feeds it to a vosk KaldiRecognizer, and emits phrase_heard(str) whenever
a complete utterance is recognised.

The engine then checks every active VoiceRule and fires keystrokes whose
phrases match the utterance.

Model is auto-downloaded (~50 MB) to assets/vosk-model-small-en-us/ on
first use.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import zipfile

import sounddevice as sd
from vosk import Model, KaldiRecognizer
from PySide6.QtCore import QThread, Signal

from app.keystroke_engine import KeystrokeEngine, _parse_keys, _controller as _kb
from app.profile_store import VoiceRule

_SAMPLE_RATE = 16000
_BLOCK_SIZE  = 4000   # ~250 ms chunks

_ASSETS_DIR   = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
_MODEL_DIR    = os.path.join(_ASSETS_DIR, "vosk-model-small-en-us")
_MODEL_ZIP    = os.path.join(_ASSETS_DIR, "vosk-model-small-en-us.zip")
_MODEL_URL    = (
    "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
)


def _ensure_model() -> str:
    """Download and unzip the small English vosk model if not already present."""
    os.makedirs(_ASSETS_DIR, exist_ok=True)
    if os.path.isdir(_MODEL_DIR):
        return _MODEL_DIR
    if not os.path.exists(_MODEL_ZIP):
        print(f"[PoseKeys] Downloading vosk model to {_MODEL_ZIP} …")
        urllib.request.urlretrieve(_MODEL_URL, _MODEL_ZIP)
        print("[PoseKeys] vosk model downloaded.")
    print("[PoseKeys] Extracting vosk model…")
    with zipfile.ZipFile(_MODEL_ZIP, "r") as zf:
        # The zip contains a single top-level folder; extract into assets/
        members = zf.namelist()
        top = members[0].split("/")[0]
        zf.extractall(_ASSETS_DIR)
        # Rename to our expected dir name if different
        extracted = os.path.join(_ASSETS_DIR, top)
        if extracted != _MODEL_DIR:
            os.rename(extracted, _MODEL_DIR)
    os.remove(_MODEL_ZIP)
    print("[PoseKeys] vosk model ready.")
    return _MODEL_DIR


class VoiceEngine(QThread):
    """Background thread that listens to the microphone and emits recognised phrases."""

    phrase_heard    = Signal(str)   # full recognised utterance (lowercased)
    rule_fired      = Signal(str)   # rule_id of any rule that just matched
    status_changed  = Signal(str)   # "listening" | "stopped" | error message
    partial_heard   = Signal(str)   # live partial transcript (for UI feedback)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules: list[VoiceRule] = []
        self._running = False
        self._last_fired: dict[str, float] = {}   # rule_id → timestamp
        self._ks_engine: KeystrokeEngine | None = None

    # ── Public API ────────────────────────────────────────────────────────
    def set_rules(self, rules: list[VoiceRule]) -> None:
        self._rules = list(rules)

    def set_keystroke_engine(self, ks: KeystrokeEngine) -> None:
        self._ks_engine = ks

    def stop_listening(self) -> None:
        self._running = False

    # ── Thread body ───────────────────────────────────────────────────────
    def run(self) -> None:
        try:
            model_path = _ensure_model()
        except Exception as e:
            self.status_changed.emit(f"Model download failed: {e}")
            return

        try:
            model = Model(model_path)
        except Exception as e:
            self.status_changed.emit(f"Failed to load vosk model: {e}")
            return

        rec = KaldiRecognizer(model, _SAMPLE_RATE)
        rec.SetWords(True)

        self._running = True
        self.status_changed.emit("listening")

        try:
            with sd.RawInputStream(
                samplerate=_SAMPLE_RATE,
                blocksize=_BLOCK_SIZE,
                dtype="int16",
                channels=1,
            ) as stream:
                while self._running:
                    data, _ = stream.read(_BLOCK_SIZE)
                    if rec.AcceptWaveform(bytes(data)):
                        result = json.loads(rec.Result())
                        text = result.get("text", "").strip().lower()
                        if text:
                            self.phrase_heard.emit(text)
                            self._check_rules(text)
                    else:
                        partial = json.loads(rec.PartialResult())
                        pt = partial.get("partial", "").strip().lower()
                        if pt:
                            self.partial_heard.emit(pt)
        except Exception as e:
            self.status_changed.emit(f"Mic error: {e}")
        finally:
            self._running = False
            self.status_changed.emit("stopped")

    # ── Rule matching ─────────────────────────────────────────────────────
    def _check_rules(self, text: str) -> None:
        now = time.monotonic()
        for rule in self._rules:
            if not rule.phrase.strip():
                continue
            phrase = rule.phrase.strip().lower()
            if rule.exact:
                matched = (text == phrase)
            else:
                matched = (phrase in text)
            if not matched:
                continue
            # Cooldown check
            last = self._last_fired.get(rule.id, 0.0)
            if now - last < rule.cooldown:
                continue
            self._last_fired[rule.id] = now
            self._fire(rule)
            self.rule_fired.emit(rule.id)

    def _fire(self, rule: VoiceRule) -> None:
        keys = _parse_keys(rule.keystroke.keys)
        if not keys:
            return
        if rule.keystroke.mode == "tap":
            for k in keys:
                _kb.press(k)
            for k in reversed(keys):
                _kb.release(k)
        elif rule.keystroke.mode == "hold":
            # Voice hold — press once; a second match will release
            # (same semantics: hold starts on first detection)
            if self._ks_engine:
                self._ks_engine.update(
                    rule.id, 1.0, 1.0, rule.keystroke.__dict__
                )
