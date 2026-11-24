"""Turns controller events into actions. Pure logic apart from the injected output/media."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from evdev import ecodes as e

from . import media as default_media

log = logging.getLogger(__name__)

DEADZONE = 0.18
POINTER_SPEED = 1400.0   # px/s at full deflection
SCROLL_SPEED = 1800.0    # hi-res wheel units/s at full deflection (120 = one notch)
SEEK_SECONDS = 10

BUTTON_CODES = {
    e.BTN_SOUTH: "A", e.BTN_EAST: "B", e.BTN_NORTH: "X", e.BTN_WEST: "Y",
    e.BTN_TL: "LB", e.BTN_TR: "RB", e.BTN_START: "START", e.BTN_SELECT: "SELECT",
    e.BTN_MODE: "GUIDE", e.BTN_THUMBL: "L3", e.BTN_THUMBR: "R3",
}

# Actions that hold a key/button while the controller button is held.
HELD = {
    "select": e.BTN_LEFT, "context": e.BTN_RIGHT,
    "up": e.KEY_UP, "down": e.KEY_DOWN, "left": e.KEY_LEFT, "right": e.KEY_RIGHT,
    "vol_up": e.KEY_VOLUMEUP, "vol_down": e.KEY_VOLUMEDOWN,
}
# Actions that fire once on press.
TAPPED = {"back": e.BTN_SIDE, "fullscreen": e.KEY_F, "search": e.KEY_SLASH}


def axis(value: int, lo: int, hi: int) -> float:
    """Normalize a raw stick value to -1..1 with a radial-free deadzone and a gentle curve."""
    mid = (lo + hi) / 2
    half = (hi - lo) / 2 or 1
    v = max(-1.0, min(1.0, (value - mid) / half))
    if abs(v) < DEADZONE:
        return 0.0
    v = (abs(v) - DEADZONE) / (1 - DEADZONE)
    return (v * v) * (1 if value >= mid else -1)


def _background(fn: Callable, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


class Engine:
    def __init__(self, out, bindings: dict[str, str], media=default_media,
                 bg: Callable = _background) -> None:
        self.out = out
        self.bindings = bindings
        self.media = media
        self.bg = bg
        self.sticks = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0}
        self._frac = {"px": 0.0, "py": 0.0, "sx": 0.0, "sy": 0.0}
        self._held: dict[str, int] = {}     # button -> key code currently held down
        self._trigger_down = {"LT": False, "RT": False}

    # -- input ---------------------------------------------------------
    def button(self, name: str, pressed: bool) -> None:
        action = self.bindings.get(name, "none")
        if action in HELD:
            if pressed:
                self._held[name] = HELD[action]
                self.out.key(HELD[action], True)
            elif name in self._held:
                self.out.key(self._held.pop(name), False)
        elif pressed:
            self._fire(action)

    def _fire(self, action: str) -> None:
        if action in TAPPED:
            self.out.tap(TAPPED[action])
        elif action == "play_pause":
            self.bg(self._media_or_key, self.media.play_pause, e.KEY_SPACE)
        elif action == "seek_back":
            self.bg(self._seek, -SEEK_SECONDS, e.KEY_LEFT)
        elif action == "seek_fwd":
            self.bg(self._seek, SEEK_SECONDS, e.KEY_RIGHT)

    def _media_or_key(self, fn: Callable[[], bool], key: int) -> None:
        if not fn():
            self.out.tap(key)

    def _seek(self, seconds: int, fallback_key: int) -> None:
        if not self.media.seek(seconds):
            self.out.tap(fallback_key)

    def abs_event(self, code: int, value: int, lo: int, hi: int) -> None:
        if code in (e.ABS_X, e.ABS_Y, e.ABS_RX, e.ABS_RY):
            key = {e.ABS_X: "lx", e.ABS_Y: "ly", e.ABS_RX: "rx", e.ABS_RY: "ry"}[code]
            self.sticks[key] = axis(value, lo, hi)
        elif code in (e.ABS_Z, e.ABS_RZ):
            name = "LT" if code == e.ABS_Z else "RT"
            down = (value - lo) > (hi - lo) * 0.5
            if down != self._trigger_down[name]:
                self._trigger_down[name] = down
                self.button(name, down)
        elif code == e.ABS_HAT0X:
            self._dpad(("DPAD_LEFT", "DPAD_RIGHT"), value)
        elif code == e.ABS_HAT0Y:
            self._dpad(("DPAD_UP", "DPAD_DOWN"), value)

    def _dpad(self, names: tuple[str, str], value: int) -> None:
        for name, active in zip(names, (value < 0, value > 0)):
            if active != (name in self._held):
                self.button(name, active)

    # -- continuous output (call at ~120 Hz) -----------------------------
    def tick(self, dt: float) -> None:
        s, f = self.sticks, self._frac
        f["px"] += s["lx"] * POINTER_SPEED * dt
        f["py"] += s["ly"] * POINTER_SPEED * dt
        dx, dy = int(f["px"]), int(f["py"])
        f["px"] -= dx
        f["py"] -= dy
        self.out.move(dx, dy)

        f["sx"] += s["rx"] * SCROLL_SPEED * dt
        f["sy"] += -s["ry"] * SCROLL_SPEED * dt   # stick up = scroll up
        hx, hy = int(f["sx"]), int(f["sy"])
        f["sx"] -= hx
        f["sy"] -= hy
        self.out.scroll(hx, hy)

    def release_all(self) -> None:
        for code in self._held.values():
            self.out.key(code, False)
        self._held.clear()
        self._trigger_down = {"LT": False, "RT": False}
        self.sticks = dict.fromkeys(self.sticks, 0.0)
