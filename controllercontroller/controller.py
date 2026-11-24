"""Find the Xbox pad, stream its events into the Engine, reconnect on unplug."""

from __future__ import annotations

import asyncio
import logging
import time

import evdev
from evdev import ecodes as e

from .engine import BUTTON_CODES, Engine

log = logging.getLogger(__name__)
TICK = 1 / 120


# The Bluetooth Xbox Wireless Controller (hid-microsoft) reports the right stick as ABS_Z/ABS_RZ and the
# triggers as ABS_BRAKE/ABS_GAS; the USB driver (xpad) uses ABS_RX/RY and ABS_Z/RZ. Normalise to xpad.
_BT_REMAP = {e.ABS_Z: e.ABS_RX, e.ABS_RZ: e.ABS_RY, e.ABS_BRAKE: e.ABS_Z, e.ABS_GAS: e.ABS_RZ}


def axis_remap(codes) -> dict[int, int]:
    """Map this pad's raw ABS codes onto the xpad layout the Engine expects."""
    return _BT_REMAP if e.ABS_RX not in codes and e.ABS_GAS in codes else {}


def find_gamepad() -> evdev.InputDevice | None:
    for path in evdev.list_devices():
        try:
            dev = evdev.InputDevice(path)
        except OSError:
            continue
        caps = dev.capabilities()
        has_sticks = e.ABS_X in [c for c, _ in caps.get(e.EV_ABS, [])]
        has_face = e.BTN_SOUTH in caps.get(e.EV_KEY, [])
        if has_sticks and has_face and "ControllerController" not in dev.name:
            return dev
        dev.close()
    return None


async def _ticker(engine: Engine) -> None:
    last = time.monotonic()
    while True:
        await asyncio.sleep(TICK)
        now = time.monotonic()
        engine.tick(now - last)
        last = now


async def _stream(dev: evdev.InputDevice, engine: Engine) -> None:
    ranges = {c: (i.min, i.max) for c, i in dev.capabilities(absinfo=True).get(e.EV_ABS, [])}
    remap = axis_remap(ranges)
    async for ev in dev.async_read_loop():
        if ev.type == e.EV_KEY and ev.code in BUTTON_CODES and ev.value != 2:
            engine.button(BUTTON_CODES[ev.code], bool(ev.value))
        elif ev.type == e.EV_ABS and ev.code in ranges:
            engine.abs_event(remap.get(ev.code, ev.code), ev.value, *ranges[ev.code])


async def run(engine: Engine) -> None:
    ticker = asyncio.create_task(_ticker(engine))
    try:
        while True:
            dev = find_gamepad()
            if dev is None:
                await asyncio.sleep(2)
                continue
            log.info("controller connected: %s", dev.name)
            try:
                await _stream(dev, engine)
            except OSError:
                log.info("controller disconnected")
            finally:
                engine.release_all()
                dev.close()
    finally:
        ticker.cancel()
