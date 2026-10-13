"""KeystrokeEngine — translates pose match scores into pynput keyboard events."""
from __future__ import annotations

import time

from pynput.keyboard import Controller, Key, KeyCode

_controller = Controller()

# Map lowercase string names → pynput Key enum or KeyCode
_SPECIAL: dict[str, Key] = {
    "ctrl": Key.ctrl,
    "ctrl_l": Key.ctrl_l,
    "ctrl_r": Key.ctrl_r,
    "shift": Key.shift,
    "shift_l": Key.shift_l,
    "shift_r": Key.shift_r,
    "alt": Key.alt,
    "alt_l": Key.alt_l,
    "alt_r": Key.alt_r,
    "cmd": Key.cmd,
    "win": Key.cmd,
    "super": Key.cmd,
    "enter": Key.enter,
    "return": Key.enter,
    "space": Key.space,
    "tab": Key.tab,
    "backspace": Key.backspace,
    "delete": Key.delete,
    "del": Key.delete,
    "esc": Key.esc,
    "escape": Key.esc,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "home": Key.home,
    "end": Key.end,
    "page_up": Key.page_up,
    "page_down": Key.page_down,
    "insert": Key.insert,
    "caps_lock": Key.caps_lock,
    "num_lock": Key.num_lock,
    "scroll_lock": Key.scroll_lock,
    "print_screen": Key.print_screen,
    "pause": Key.pause,
    "menu": Key.menu,
}
# Add function keys f1–f20
for _i in range(1, 21):
    _SPECIAL[f"f{_i}"] = getattr(Key, f"f{_i}", None)
_SPECIAL = {k: v for k, v in _SPECIAL.items() if v is not None}

_TAP_COOLDOWN = 0.5  # seconds


def _parse_keys(keys: list[str]):
    """Convert string key names to pynput Key / KeyCode objects."""
    result = []
    for k in keys:
        k_lower = k.lower()
        if k_lower in _SPECIAL:
            result.append(_SPECIAL[k_lower])
        elif len(k) == 1:
            result.append(KeyCode.from_char(k))
        else:
            # Try KeyCode from vk or just char fallback
            result.append(KeyCode.from_char(k[0]))
    return result


class KeystrokeEngine:
    def __init__(self):
        # pose_id → {"active": bool, "last_fired": float}
        self._state: dict[str, dict] = {}
        self._held_keys: dict[str, list] = {}  # pose_id → list of pynput keys currently held

    def _get_state(self, pose_id: str) -> dict:
        if pose_id not in self._state:
            self._state[pose_id] = {"active": False, "last_fired": 0.0}
        return self._state[pose_id]

    # ------------------------------------------------------------------
    def update(self, pose_id: str, score: float, threshold: float, config: dict) -> None:
        """Called each frame for a single pose.

        *config* example: {"keys": ["ctrl", "shift", "f5"], "mode": "tap"}
        """
        state = self._get_state(pose_id)
        keys = _parse_keys(config.get("keys", []))
        mode = config.get("mode", "tap")
        triggered = score >= threshold

        if mode == "tap":
            if triggered and not state["active"]:
                now = time.monotonic()
                if now - state["last_fired"] >= _TAP_COOLDOWN:
                    self._tap(keys)
                    state["last_fired"] = now
                state["active"] = True
            elif not triggered:
                state["active"] = False

        elif mode == "hold":
            if triggered and not state["active"]:
                self._press_all(pose_id, keys)
                state["active"] = True
            elif not triggered and state["active"]:
                self._release_held(pose_id)
                state["active"] = False

    def _tap(self, keys: list) -> None:
        for k in keys:
            _controller.press(k)
        for k in reversed(keys):
            _controller.release(k)

    def _press_all(self, pose_id: str, keys: list) -> None:
        for k in keys:
            _controller.press(k)
        self._held_keys[pose_id] = keys

    def _release_held(self, pose_id: str) -> None:
        for k in reversed(self._held_keys.get(pose_id, [])):
            try:
                _controller.release(k)
            except Exception:
                pass
        self._held_keys.pop(pose_id, None)

    def release_all(self) -> None:
        """Release every key currently held — call on app shutdown."""
        for pose_id in list(self._held_keys.keys()):
            self._release_held(pose_id)
        self._state.clear()
