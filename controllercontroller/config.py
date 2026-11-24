"""Keybind configuration. Only button -> action bindings are user-configurable."""

from __future__ import annotations

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
    "fullscreen", "search", "osk", "toggle_mode", "none",
)

DEFAULT_BINDINGS: dict[str, str] = {
    "A": "select",
    "B": "back",
    "X": "osk",
    "Y": "search",
    "LB": "seek_back",
    "RB": "seek_fwd",
    "LT": "vol_down",
    "RT": "vol_up",
    "START": "play_pause",
    "SELECT": "fullscreen",
    "GUIDE": "toggle_mode",
    "DPAD_UP": "up",
    "DPAD_DOWN": "down",
    "DPAD_LEFT": "left",
    "DPAD_RIGHT": "right",
}

DEFAULT_TOML = """\
# ControllerController keybinds. Format: BUTTON = "action"
# Buttons: {buttons}
# Actions: {actions}
[bindings]
{lines}
""".format(
    buttons=", ".join(BUTTONS),
    actions=", ".join(ACTIONS),
    lines="\n".join(f'{b} = "{a}"' for b, a in DEFAULT_BINDINGS.items()),
)


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
            path.write_text(DEFAULT_TOML)
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
