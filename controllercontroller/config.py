"""Keybind configuration. Only button -> action bindings are user-configurable."""

from __future__ import annotations

import asyncio
import logging
import os
import tomllib
from pathlib import Path

log = logging.getLogger(__name__)

BUTTONS = (
    "A", "B", "X", "Y", "LB", "RB", "LT", "RT", "START", "SELECT", "GUIDE",
    "L3", "R3", "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
)

ACTIONS = (
    "select", "context", "back", "up", "down", "left", "right",
    "seek_back", "seek_fwd", "vol_up", "vol_down", "play_pause",
    "fullscreen", "search", "osk", "help", "toggle_mode", "tab_prev", "tab_next", "none",
)

DEFAULT_BINDINGS: dict[str, str] = {
    "A": "select",
    "B": "back",
    "X": "help",
    "Y": "search",
    "LB": "seek_back",
    "RB": "seek_fwd",
    "LT": "vol_down",
    "RT": "vol_up",
    "START": "play_pause",
    "SELECT": "fullscreen",
    "GUIDE": "toggle_mode",
    "L3": "tab_prev",
    "R3": "tab_next",
    "DPAD_UP": "up",
    "DPAD_DOWN": "down",
    "DPAD_LEFT": "left",
    "DPAD_RIGHT": "right",
}

# Friendly names, shared by the settings window.
BUTTON_LABELS = {
    "A": "A", "B": "B", "X": "X", "Y": "Y", "LB": "Left bumper (LB)", "RB": "Right bumper (RB)",
    "LT": "Left trigger (LT)", "RT": "Right trigger (RT)", "START": "Menu", "SELECT": "View",
    "GUIDE": "Xbox button", "L3": "Left stick click", "R3": "Right stick click",
    "DPAD_UP": "D-pad up", "DPAD_DOWN": "D-pad down", "DPAD_LEFT": "D-pad left", "DPAD_RIGHT": "D-pad right",
}
ACTION_LABELS = {
    "select": "Select / click", "back": "Back / close", "context": "Right-click",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "seek_back": "Back 10 seconds", "seek_fwd": "Forward 10 seconds",
    "vol_up": "Volume up", "vol_down": "Volume down", "play_pause": "Play / pause",
    "fullscreen": "Fullscreen", "search": "Search", "osk": "On-screen keyboard", "help": "Show controls",
    "toggle_mode": "Mouse mode on / off", "tab_prev": "Previous tab", "tab_next": "Next tab",
    "none": "Do nothing",
}


def render_toml(overrides: dict[str, str]) -> str:
    """Config text: only the bindings that differ from the defaults, so new defaults still apply."""
    lines = [
        "# ControllerController keybinds. Easiest to change in the ControllerController settings window.",
        '# Format: BUTTON = "action". Anything not listed here uses the default.',
        f"# Buttons: {', '.join(BUTTONS)}",
        f"# Actions: {', '.join(ACTIONS)}",
        "# Defaults: " + ", ".join(f"{b}={a}" for b, a in DEFAULT_BINDINGS.items()),
        "[bindings]",
    ]
    lines += [f'{b} = "{a}"' for b, a in overrides.items()]
    return "\n".join(lines) + "\n"


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "controllercontroller" / "config.toml"


def load_bindings(path: Path | None = None) -> dict[str, str]:
    """Load bindings, creating the default file on first run. Never raises on bad config."""
    path = path or config_path()
    bindings = dict(DEFAULT_BINDINGS)
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(render_toml({}))
        except OSError as exc:
            log.warning("could not write default config: %s", exc)
        return bindings
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("ignoring unreadable config %s: %s", path, exc)
        return bindings
    for button, action in data.get("bindings", {}).items():
        if button not in BUTTONS:
            log.warning("config: unknown button %r", button)
        elif action not in ACTIONS:
            log.warning("config: unknown action %r for %s", action, button)
        else:
            bindings[button] = action
    return bindings


def save_bindings(bindings: dict[str, str], path: Path | None = None) -> None:
    """Write bindings atomically (the daemon reloads the file when it changes)."""
    path = path or config_path()
    overrides = {b: a for b, a in bindings.items() if DEFAULT_BINDINGS.get(b) != a}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(render_toml(overrides))
    os.replace(tmp, path)


async def watch(bindings: dict[str, str], path: Path | None = None, interval: float = 1.0) -> None:
    """Reload keybinds into `bindings` (in place) whenever the config file changes."""
    path = path or config_path()

    def stamp() -> int:
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    last = stamp()
    while True:
        await asyncio.sleep(interval)
        now = stamp()
        if now != last:
            last = now
            fresh = load_bindings(path)
            bindings.clear()
            bindings.update(fresh)
            log.info("keybinds reloaded")
