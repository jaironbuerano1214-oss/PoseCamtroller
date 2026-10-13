"""ZoneEngine — fires keystrokes when tracked landmarks enter rectangular zones.

Zones use normalised [0,1] coordinates matching MediaPipe's NormalizedLandmark
x/y values so no pixel conversion is needed at evaluation time.

Synthetic marker landmarks (index >= MARKER_INDEX_OFFSET=100) are supported
alongside body landmarks.  When a zone's landmark_indices is empty ("Full Body"),
only body landmarks (index < 100) are evaluated so that a stray marker in frame
doesn't accidentally fire every zone.
"""
from __future__ import annotations

import time
from app.keystroke_engine import KeystrokeEngine
from app.profile_store import ZoneRule
from app.marker_tracker import MARKER_INDEX_OFFSET

_TAP_COOLDOWN = 0.5  # seconds, same as pose tap cooldown


class ZoneEngine:
    """Stateful engine — one instance lives for the lifetime of the app."""

    def __init__(self, keystroke_engine: KeystrokeEngine):
        self._ks = keystroke_engine
        # zone_id → {"active": bool, "last_fired": float}
        self._state: dict[str, dict] = {}

    # ------------------------------------------------------------------
    def update(self, zones: list[ZoneRule], landmarks) -> dict[str, bool]:
        """Evaluate all zones against the current landmarks.

        Returns a dict zone_id → triggered (bool) for the overlay to use.
        """
        results: dict[str, bool] = {}
        if not landmarks:
            # No body visible — release all held zone keys
            for zid, st in self._state.items():
                if st.get("active"):
                    self._ks._release_held(zid)  # noqa: SLF001
                    st["active"] = False
            return {z.id: False for z in zones}

        for zone in zones:
            triggered = self._zone_hit(zone, landmarks)
            results[zone.id] = triggered
            state = self._get_state(zone.id)
            cfg = zone.keystroke.__dict__
            self._ks.update(zone.id, 1.0 if triggered else 0.0, 1.0, cfg)

        return results

    def release_all(self) -> None:
        for zid in list(self._state.keys()):
            self._ks._release_held(zid)  # noqa: SLF001
        self._state.clear()

    # ------------------------------------------------------------------
    def _get_state(self, zone_id: str) -> dict:
        if zone_id not in self._state:
            self._state[zone_id] = {"active": False, "last_fired": 0.0}
        return self._state[zone_id]

    @staticmethod
    def _zone_hit(zone: ZoneRule, landmarks) -> bool:
        """Return True if any watched landmark is inside the zone rect.

        When landmark_indices is empty ("Full Body") only body landmarks
        (index < MARKER_INDEX_OFFSET) are checked so markers don't fire
        unintended zones.
        """
        x0, y0 = zone.x, zone.y
        x1, y1 = zone.x + zone.w, zone.y + zone.h

        if zone.landmark_indices:
            indices = zone.landmark_indices
        else:
            # Full Body — body landmarks only, exclude synthetic markers
            indices = [i for i in range(len(landmarks)) if i < MARKER_INDEX_OFFSET]

        for i in indices:
            if i >= len(landmarks):
                continue
            lm = landmarks[i]
            if lm is None:
                continue
            vis = getattr(lm, "visibility", 1.0) or 1.0
            if vis < 0.2:
                continue
            if x0 <= lm.x <= x1 and y0 <= lm.y <= y1:
                return True
        return False
