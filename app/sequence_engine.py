"""SequenceEngine — fires keystrokes when poses are triggered in a defined order.

Each SequenceRule holds an ordered list of pose_ids.  The engine keeps a per-rule
cursor (which step we're waiting for next) and a timestamp of the last step.
When a pose crosses threshold the engine advances any rule whose current step
matches that pose_id.  If the cursor reaches the end within window_sec, the
keystroke fires and the rule resets.  If window_sec elapses without progress the
cursor resets to step 0.
"""
from __future__ import annotations

import time

from app.keystroke_engine import KeystrokeEngine, _parse_keys, _controller as _kb
from app.profile_store import SequenceRule


class SequenceEngine:
    def __init__(self, keystroke_engine: KeystrokeEngine):
        self._ks = keystroke_engine
        # rule_id → {"cursor": int, "last_step_time": float, "fired": bool}
        self._state: dict[str, dict] = {}

    # ------------------------------------------------------------------
    def notify_pose_active(self, pose_id: str, rules: list[SequenceRule]) -> list[str]:
        """Call when a pose crosses threshold (rising edge only — once per activation).

        Returns list of rule_ids that completed this frame (for UI feedback).
        """
        fired_rules: list[str] = []
        now = time.monotonic()

        for rule in rules:
            if not rule.pose_ids:
                continue
            st = self._get_state(rule.id)

            # Timeout check — reset cursor if window expired
            if st["cursor"] > 0 and (now - st["last_step_time"]) > rule.window_sec:
                st["cursor"] = 0

            expected = rule.pose_ids[st["cursor"]]
            if pose_id == expected:
                st["cursor"] += 1
                st["last_step_time"] = now

                if st["cursor"] >= len(rule.pose_ids):
                    # Sequence complete — fire keystroke
                    self._fire(rule)
                    fired_rules.append(rule.id)
                    st["cursor"] = 0

        return fired_rules

    def reset(self) -> None:
        self._state.clear()

    # ------------------------------------------------------------------
    def _get_state(self, rule_id: str) -> dict:
        if rule_id not in self._state:
            self._state[rule_id] = {"cursor": 0, "last_step_time": 0.0}
        return self._state[rule_id]

    def _fire(self, rule: SequenceRule) -> None:
        keys = _parse_keys(rule.keystroke.keys)
        if not keys:
            return
        # Sequences always tap — holding a sequence combo doesn't make semantic sense
        for k in keys:
            _kb.press(k)
        for k in reversed(keys):
            _kb.release(k)

    def progress(self, rule_id: str) -> int:
        """Return current cursor position (0 = not started) for UI feedback."""
        return self._state.get(rule_id, {}).get("cursor", 0)
