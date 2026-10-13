"""ProfileStore — dataclasses and JSON persistence for profiles, poses, and zone rules."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Any

_PROFILES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "profiles")
_SCHEMA_VERSION = 1


@dataclass
class ZoneRule:
    """A rectangular zone (in normalised 0-1 coords) that fires a keystroke when
    any of the listed body-part landmark indices are inside it.

    x, y, w, h are all in [0, 1] (fraction of frame width/height).
    landmark_indices: which MediaPipe landmark indices to watch (33-point model).
      Pass [] to mean "any landmark".
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Zone"
    # normalised rect — top-left corner + size, all in [0,1]
    x: float = 0.3
    y: float = 0.3
    w: float = 0.2
    h: float = 0.2
    # which landmark indices trigger this zone (empty = any/all)
    landmark_indices: list[int] = field(default_factory=list)
    keystroke: "Keystroke" = field(default_factory=lambda: Keystroke())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "w": self.w,
            "h": self.h,
            "landmark_indices": self.landmark_indices,
            "keystroke": self.keystroke.to_dict(),
        }

    @staticmethod
    def from_dict(d: dict) -> "ZoneRule":
        return ZoneRule(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", "Zone"),
            x=float(d.get("x", 0.3)),
            y=float(d.get("y", 0.3)),
            w=float(d.get("w", 0.2)),
            h=float(d.get("h", 0.2)),
            landmark_indices=[int(i) for i in d.get("landmark_indices", [])],
            keystroke=Keystroke.from_dict(d.get("keystroke", {})),
        )


@dataclass
class FingerRule:
    """Fire a keystroke when a specific number of fingers are held up on a hand.

    hand: "left" | "right" | "any"
    finger_count: 0–5  (number of extended fingers)
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Finger Rule"
    hand: str = "any"           # "left" | "right" | "any"
    finger_count: int = 5       # 0-5
    keystroke: "Keystroke" = field(default_factory=lambda: Keystroke())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "hand": self.hand,
            "finger_count": self.finger_count,
            "keystroke": self.keystroke.to_dict(),
        }

    @staticmethod
    def from_dict(d: dict) -> "FingerRule":
        return FingerRule(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", "Finger Rule"),
            hand=d.get("hand", "any"),
            finger_count=int(d.get("finger_count", 5)),
            keystroke=Keystroke.from_dict(d.get("keystroke", {})),
        )


@dataclass
class SequenceRule:
    """Fire a keystroke when a list of poses are triggered in order within a time window.

    pose_ids: ordered list of pose IDs that must each cross threshold in sequence.
    window_sec: maximum seconds allowed between each consecutive step.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Sequence"
    pose_ids: list[str] = field(default_factory=list)
    window_sec: float = 3.0
    keystroke: "Keystroke" = field(default_factory=lambda: Keystroke())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "pose_ids": self.pose_ids,
            "window_sec": self.window_sec,
            "keystroke": self.keystroke.to_dict(),
        }

    @staticmethod
    def from_dict(d: dict) -> "SequenceRule":
        return SequenceRule(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", "Sequence"),
            pose_ids=list(d.get("pose_ids", [])),
            window_sec=float(d.get("window_sec", 3.0)),
            keystroke=Keystroke.from_dict(d.get("keystroke", {})),
        )


@dataclass
class VoiceRule:
    """Fire a keystroke when a spoken phrase is detected.

    phrase:      the text to listen for (case-insensitive substring match by default)
    exact:       if True, the full utterance must equal the phrase exactly
    cooldown:    minimum seconds between firings (prevents repeated triggers)
    keystroke:   what to press when matched
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Voice Rule"
    phrase: str = ""
    exact: bool = False
    cooldown: float = 2.0
    keystroke: "Keystroke" = field(default_factory=lambda: Keystroke())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "phrase": self.phrase,
            "exact": self.exact,
            "cooldown": self.cooldown,
            "keystroke": self.keystroke.to_dict(),
        }

    @staticmethod
    def from_dict(d: dict) -> "VoiceRule":
        return VoiceRule(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", "Voice Rule"),
            phrase=d.get("phrase", ""),
            exact=bool(d.get("exact", False)),
            cooldown=float(d.get("cooldown", 2.0)),
            keystroke=Keystroke.from_dict(d.get("keystroke", {})),
        )


@dataclass
class Keystroke:
    keys: list[str] = field(default_factory=list)
    mode: str = "tap"  # "tap" | "hold"

    def to_dict(self) -> dict:
        return {"keys": self.keys, "mode": self.mode}

    @staticmethod
    def from_dict(d: dict) -> "Keystroke":
        return Keystroke(keys=d.get("keys", []), mode=d.get("mode", "tap"))


@dataclass
class Pose:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "Unnamed Pose"
    description: str = ""
    landmarks: list[list[float]] = field(default_factory=list)
    keystroke: Keystroke = field(default_factory=Keystroke)
    threshold: float = 0.75

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "landmarks": self.landmarks,
            "keystroke": self.keystroke.to_dict(),
            "threshold": self.threshold,
        }

    @staticmethod
    def from_dict(d: dict) -> "Pose":
        return Pose(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", "Unnamed"),
            description=d.get("description", ""),
            landmarks=d.get("landmarks", []),
            keystroke=Keystroke.from_dict(d.get("keystroke", {})),
            threshold=float(d.get("threshold", 0.75)),
        )


@dataclass
class Profile:
    name: str = "Default"
    poses: list[Pose] = field(default_factory=list)
    zones: list[ZoneRule] = field(default_factory=list)
    finger_rules: list[FingerRule] = field(default_factory=list)
    sequence_rules: list[SequenceRule] = field(default_factory=list)
    voice_rules: list[VoiceRule] = field(default_factory=list)
    version: int = _SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "name": self.name,
            "poses": [p.to_dict() for p in self.poses],
            "zones": [z.to_dict() for z in self.zones],
            "finger_rules": [f.to_dict() for f in self.finger_rules],
            "sequence_rules": [s.to_dict() for s in self.sequence_rules],
            "voice_rules": [v.to_dict() for v in self.voice_rules],
        }

    @staticmethod
    def from_dict(d: dict) -> "Profile":
        _validate_schema(d)
        return Profile(
            name=d["name"],
            poses=[Pose.from_dict(p) for p in d.get("poses", [])],
            zones=[ZoneRule.from_dict(z) for z in d.get("zones", [])],
            finger_rules=[FingerRule.from_dict(f) for f in d.get("finger_rules", [])],
            sequence_rules=[SequenceRule.from_dict(s) for s in d.get("sequence_rules", [])],
            voice_rules=[VoiceRule.from_dict(v) for v in d.get("voice_rules", [])],
            version=d.get("version", _SCHEMA_VERSION),
        )


def _validate_schema(d: Any) -> None:
    if not isinstance(d, dict):
        raise ValueError("Profile JSON must be an object.")
    for key in ("version", "name", "poses"):
        if key not in d:
            raise ValueError(f"Profile JSON missing required key: '{key}'")
    if not isinstance(d["poses"], list):
        raise ValueError("'poses' must be a list.")


class ProfileStore:
    def __init__(self, profiles_dir: str = _PROFILES_DIR):
        self._dir = profiles_dir
        os.makedirs(self._dir, exist_ok=True)

    def _path(self, name: str) -> str:
        safe = name.replace("/", "_").replace("\\", "_")
        return os.path.join(self._dir, f"{safe}.json")

    # ------------------------------------------------------------------
    def load_all(self) -> list[Profile]:
        profiles = []
        for fname in os.listdir(self._dir):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(self._dir, fname), encoding="utf-8") as f:
                        profiles.append(Profile.from_dict(json.load(f)))
                except Exception:
                    pass  # Skip corrupt files
        return profiles

    def save(self, profile: Profile) -> None:
        with open(self._path(profile.name), "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, indent=2)

    def delete(self, name: str) -> None:
        path = self._path(name)
        if os.path.exists(path):
            os.remove(path)

    def import_profile(self, src_path: str) -> Profile:
        with open(src_path, encoding="utf-8") as f:
            data = json.load(f)
        profile = Profile.from_dict(data)  # validates schema
        self.save(profile)
        return profile

    def export_profile(self, name: str, dest_path: str) -> None:
        src = self._path(name)
        if not os.path.exists(src):
            raise FileNotFoundError(f"Profile '{name}' not found.")
        shutil.copy2(src, dest_path)
