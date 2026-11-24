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
DIRS = ("up", "down", "left", "right")
NAV_THRESHOLD = 0.25      # curved stick value that counts as a "push"
NAV_FIRST_REPEAT = 0.40   # seconds before a held direction starts repeating
NAV_REPEAT = 0.15
# Keys the browser extension may ask us to press (e.g. arrows for in-player seeking).
EXT_KEYS = {"up": e.KEY_UP, "down": e.KEY_DOWN, "left": e.KEY_LEFT, "right": e.KEY_RIGHT,
            "space": e.KEY_SPACE, "enter": e.KEY_ENTER, "slash": e.KEY_SLASH}
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
                 bg: Callable = _background, bridge=None) -> None:
        self.out = out
        self.bindings = bindings
        self.media = media
        self.bg = bg
        self.bridge = bridge
        self.force_mouse = False
        self.sticks = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0}
        self._frac = {"px": 0.0, "py": 0.0, "sx": 0.0, "sy": 0.0}
        self._held: dict[str, int] = {}       # button -> key code currently held down
        self._nav: dict[str, str] = {}        # button -> direction (browser mode)
        self._dpad_on: set[str] = set()
        self._trigger_down = {"LT": False, "RT": False}
        self._clock = 0.0
        self._nav_dir: str | None = None
        self._nav_next = 0.0

    @property
    def browser_mode(self) -> bool:
        return bool(self.bridge and self.bridge.active and not self.force_mouse)

    def ext_key(self, name: str) -> None:
        """A key the extension asked for (arrow keys while a video is fullscreen)."""
        if name in EXT_KEYS:
            self.out.tap(EXT_KEYS[name])

    # -- input ---------------------------------------------------------
    def button(self, name: str, pressed: bool) -> None:
        action = self.bindings.get(name, "none")
        if not pressed:
            if self._nav.pop(name, None) is None and name in self._held:
                self.out.key(self._held.pop(name), False)
            return
        if self.browser_mode:
            if action in DIRS:
                self._nav[name] = action
                return
            if action in ("select", "back", "osk", "search"):
                self.bridge.send({"type": action})
                return
            if action == "context":
                return
        elif action == "osk":
            return
        if action == "toggle_mode":
            self.force_mouse = not self.force_mouse
            self._nav.clear()
            if self.bridge:
                self.bridge.send({"type": "mode", "mouse": self.force_mouse})
            log.info("mode: %s", "mouse (forced)" if self.force_mouse else "auto")
        elif action in HELD:
            self._held[name] = HELD[action]
            self.out.key(HELD[action], True)
        else:
            self._fire(action)

    def _typing(self) -> bool:
        return bool(self.bridge and getattr(self.bridge, "typing", False))

    def _fire(self, action: str) -> None:
        # While a text field has focus, a stray "f" or space would be typed into it.
        if action in ("fullscreen", "search") and self._typing():
            return
        if action in TAPPED:
            self.out.tap(TAPPED[action])
        elif action == "play_pause":
            self.bg(self._media_or_key, self.media.play_pause, e.KEY_SPACE)
        elif action == "seek_back":
            self.bg(self._seek, -SEEK_SECONDS, e.KEY_LEFT)
        elif action == "seek_fwd":
            self.bg(self._seek, SEEK_SECONDS, e.KEY_RIGHT)

    def _media_or_key(self, fn: Callable[[], bool], key: int) -> None:
        if not fn() and not self._typing():
            self.out.tap(key)

    def _seek(self, seconds: int, fallback_key: int) -> None:
        if not self.media.seek(seconds) and not self._typing():
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
            if active != (name in self._dpad_on):
                (self._dpad_on.add if active else self._dpad_on.discard)(name)
                self.button(name, active)

    # -- continuous output (call at ~120 Hz) -----------------------------
    def tick(self, dt: float) -> None:
        self._clock += dt
        s, f = self.sticks, self._frac
        if self.browser_mode:
            self._tick_nav()
        else:
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

    def _stick_dir(self) -> str | None:
        x, y = self.sticks["lx"], self.sticks["ly"]
        if max(abs(x), abs(y)) < NAV_THRESHOLD:
            return None
        if abs(x) >= abs(y):
            return "right" if x > 0 else "left"
        return "down" if y > 0 else "up"

    def _tick_nav(self) -> None:
        """Fire navigation once on push, then repeat while the direction stays held."""
        direction = next(iter(self._nav.values()), None) or self._stick_dir()
        if direction != self._nav_dir:
            self._nav_dir = direction
            self._nav_next = self._clock + NAV_FIRST_REPEAT
            if direction:
                self.bridge.send({"type": "nav", "dir": direction})
        elif direction and self._clock >= self._nav_next:
            self._nav_next = self._clock + NAV_REPEAT
            self.bridge.send({"type": "nav", "dir": direction})

    def release_all(self) -> None:
        for code in self._held.values():
            self.out.key(code, False)
        self._held.clear()
        self._nav.clear()
        self._dpad_on.clear()
        self._nav_dir = None
        self._trigger_down = {"LT": False, "RT": False}
        self.sticks = dict.fromkeys(self.sticks, 0.0)
