"""Virtual keyboard + mouse through /dev/uinput (works on Wayland)."""

from __future__ import annotations

from evdev import UInput
from evdev import ecodes as e

from .config import BLOCKED_KEYS, KEY_MAX

# The whole keyboard range (bindings can type any key) plus the mouse buttons. Power/sleep keys are
# left out so this device is never mistaken for a power button.
KEYS = sorted(
    (set(range(1, KEY_MAX + 1)) - BLOCKED_KEYS) | {e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE, e.BTN_SIDE}
)
REL = [e.REL_X, e.REL_Y, e.REL_WHEEL, e.REL_HWHEEL, e.REL_WHEEL_HI_RES, e.REL_HWHEEL_HI_RES]


class Output:
    def __init__(self) -> None:
        self._acc = {"x": 0, "y": 0}
        self.ui = UInput({e.EV_KEY: KEYS, e.EV_REL: REL}, name="ControllerController virtual input")

    def move(self, dx: int, dy: int) -> None:
        if dx:
            self.ui.write(e.EV_REL, e.REL_X, dx)
        if dy:
            self.ui.write(e.EV_REL, e.REL_Y, dy)
        if dx or dy:
            self.ui.syn()

    def scroll(self, hi_dx: int, hi_dy: int) -> None:
        """Scroll in high-resolution units (120 = one wheel notch). +dy scrolls up."""
        for axis, hi, hi_code, lo_code in (
            ("y", hi_dy, e.REL_WHEEL_HI_RES, e.REL_WHEEL),
            ("x", hi_dx, e.REL_HWHEEL_HI_RES, e.REL_HWHEEL),
        ):
            if not hi:
                continue
            self.ui.write(e.EV_REL, hi_code, hi)
            self._acc[axis] += hi
            notches = int(self._acc[axis] / 120)
            if notches:
                self._acc[axis] -= notches * 120
                self.ui.write(e.EV_REL, lo_code, notches)
        if hi_dx or hi_dy:
            self.ui.syn()

    def key(self, code: int, pressed: bool) -> None:
        self.ui.write(e.EV_KEY, code, 1 if pressed else 0)
        self.ui.syn()

    def tap(self, code: int) -> None:
        self.key(code, True)
        self.key(code, False)

    def chord(self, codes: tuple[int, ...]) -> None:
        """Press the keys in order, then release them in reverse (modifiers first, the key last)."""
        for code in codes:
            self.key(code, True)
        for code in reversed(codes):
            self.key(code, False)

    def combo(self, modifier: int, code: int) -> None:
        """Tap `code` while `modifier` is held (e.g. Ctrl+PageDown)."""
        self.key(modifier, True)
        self.tap(code)
        self.key(modifier, False)

    def close(self) -> None:
        self.ui.close()
