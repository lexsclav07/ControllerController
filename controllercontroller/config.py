"""Keybind configuration. Only button -> action bindings are user-configurable."""

from __future__ import annotations

import asyncio
import logging
import os
import textwrap
import tomllib
from pathlib import Path

from evdev import ecodes as e

log = logging.getLogger(__name__)

BUTTONS = (
    "A", "B", "X", "Y", "LB", "RB", "LT", "RT", "START", "SELECT", "GUIDE",
    "L3", "R3", "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT",
)

# What the settings window offers, in order. Everything past the first few is optional: the
# defaults below only use the ones that existed from the start, so these are all unbound until picked.
ACTION_GROUPS = (
    ("Navigate", ("select", "back", "up", "down", "left", "right", "search", "osk", "help",
                  "toggle_mode", "context")),
    ("Playback", ("play_pause", "seek_back", "seek_fwd", "vol_up", "vol_down", "mute", "fullscreen",
                  "skip", "next_track", "prev_track", "captions", "next_video", "prev_video",
                  "speed_up", "speed_down", "theater")),
    ("Browser", ("tab_prev", "tab_next", "new_tab", "close_tab", "reopen_tab", "refresh", "forward",
                 "address_bar", "find", "zoom_in", "zoom_out", "zoom_reset", "scroll_up", "scroll_down",
                 "page_up", "page_down", "top", "bottom")),
    ("Keyboard keys", ("enter", "escape", "space", "tab", "shift_tab", "backspace", "delete",
                       "copy", "cut", "paste", "select_all", "undo")),
    ("System", ("overview", "switch_window", "screenshot", "lock", "close_window")),
)
ACTIONS = tuple(a for _, actions in ACTION_GROUPS for a in actions) + ("none",)

# Key presses the daemon types for you: id -> (label, combo). A combo is modifiers plus one key,
# joined with "+": ctrl, shift, alt, super and any Linux key name without the KEY_ prefix.
SHORTCUTS: dict[str, tuple[str, str]] = {
    "mute": ("Mute sound", "mute"),
    "next_track": ("Next track", "nextsong"),
    "prev_track": ("Previous track", "previoussong"),
    "captions": ("Captions on / off (YouTube)", "c"),
    "next_video": ("Next video (YouTube)", "shift+n"),
    "prev_video": ("Previous video (YouTube)", "shift+p"),
    "speed_up": ("Faster playback (YouTube)", "shift+dot"),
    "speed_down": ("Slower playback (YouTube)", "shift+comma"),
    "theater": ("Theater mode (YouTube)", "t"),
    "new_tab": ("New tab", "ctrl+t"),
    "close_tab": ("Close tab", "ctrl+w"),
    "reopen_tab": ("Reopen closed tab", "ctrl+shift+t"),
    "refresh": ("Reload page", "f5"),
    "forward": ("Forward", "alt+right"),
    "address_bar": ("Address bar", "ctrl+l"),
    "find": ("Find in page", "ctrl+f"),
    "zoom_in": ("Zoom in", "ctrl+equal"),
    "zoom_out": ("Zoom out", "ctrl+minus"),
    "zoom_reset": ("Reset zoom", "ctrl+0"),
    "page_up": ("Page up", "pageup"),
    "page_down": ("Page down", "pagedown"),
    "top": ("Top of page", "home"),
    "bottom": ("Bottom of page", "end"),
    "enter": ("Enter", "enter"),
    "escape": ("Escape", "esc"),
    "space": ("Space", "space"),
    "tab": ("Tab", "tab"),
    "shift_tab": ("Shift+Tab", "shift+tab"),
    "backspace": ("Backspace", "backspace"),
    "delete": ("Delete", "delete"),
    "copy": ("Copy", "ctrl+c"),
    "cut": ("Cut", "ctrl+x"),
    "paste": ("Paste", "ctrl+v"),
    "select_all": ("Select all", "ctrl+a"),
    "undo": ("Undo", "ctrl+z"),
    "overview": ("Activities overview", "super"),
    "switch_window": ("Switch window", "alt+tab"),
    "screenshot": ("Screenshot", "sysrq"),
    "lock": ("Lock screen", "super+l"),
    "close_window": ("Close window", "alt+f4"),
}
# Single-letter site hotkeys: skipped while a text field has focus, or they would be typed into it.
PAGE_SHORTCUTS = frozenset({"captions", "next_video", "prev_video", "speed_up", "speed_down", "theater"})

MODIFIERS = {"ctrl": e.KEY_LEFTCTRL, "shift": e.KEY_LEFTSHIFT, "alt": e.KEY_LEFTALT, "super": e.KEY_LEFTMETA}
MODIFIER_ALIASES = {"control": "ctrl", "windows": "super", "meta": "super", "logo": "super"}
KEY_ALIASES = {"escape": "esc", "return": "enter", "pgup": "pageup", "pgdn": "pagedown", "del": "delete",
               "period": "dot", "spacebar": "space", "print": "sysrq", "plus": "equal"}
# Never typeable from a binding (a stray one would power the machine off or suspend it).
BLOCKED_KEYS = frozenset({e.KEY_POWER, e.KEY_SLEEP, e.KEY_WAKEUP, e.KEY_SUSPEND})
KEY_MAX = 255   # keyboard range of the virtual device

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
    "skip": "Skip intro / ad / next episode", "scroll_up": "Scroll up", "scroll_down": "Scroll down",
    "none": "Do nothing",
}
ACTION_LABELS.update({name: label for name, (label, _combo) in SHORTCUTS.items()})

KEY_LABELS = {"pageup": "Page Up", "pagedown": "Page Down", "esc": "Esc", "dot": ".", "comma": ",",
              "equal": "=", "minus": "-", "slash": "/", "backspace": "Backspace", "sysrq": "Print Screen",
              "nextsong": "Next Track", "previoussong": "Previous Track", "mute": "Mute", "super": "Super",
              "leftbrace": "[", "rightbrace": "]", "semicolon": ";", "apostrophe": "'", "grave": "`",
              "backslash": "\\", "capslock": "Caps Lock", "kpenter": "Keypad Enter"}


# ---- key combos ----
def key_code(name: str) -> int | None:
    """Linux key code for a name like "enter", "f5" or "a" (None if unknown or not allowed)."""
    name = name.strip().lower()
    name = KEY_ALIASES.get(name, name)
    if name in MODIFIERS:
        return MODIFIERS[name]
    code = getattr(e, "KEY_" + name.upper(), None) if name.isalnum() else None
    if isinstance(code, int) and 0 < code <= KEY_MAX and code not in BLOCKED_KEYS:
        return code
    return None


def key_name(code: int) -> str | None:
    names = e.KEY.get(code)
    for n in ([names] if isinstance(names, str) else names or ()):
        if n.startswith("KEY_") and getattr(e, n, None) == code and not n.endswith("_INTERESTING"):
            return n[4:].lower()
    return None


def combo_codes(combo: str) -> tuple[int, ...] | None:
    """"ctrl+shift+t" -> (KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_T): modifiers first, the key last."""
    parts = [p.strip().lower() for p in combo.split("+")]
    if not all(parts):
        return None
    codes: list[int] = []
    for mod in parts[:-1]:
        mod = MODIFIER_ALIASES.get(mod, mod)
        if mod not in MODIFIERS:
            return None
        if MODIFIERS[mod] not in codes:
            codes.append(MODIFIERS[mod])
    key = key_code(MODIFIER_ALIASES.get(parts[-1], parts[-1]))
    if key is None:
        return None
    if key not in codes:
        codes.append(key)
    return tuple(codes)


def key_codes(action: str) -> tuple[int, ...] | None:
    """Key codes to type for a shortcut or custom `key:` action, else None."""
    if action in SHORTCUTS:
        return combo_codes(SHORTCUTS[action][1])
    if action.startswith("key:"):
        return combo_codes(action[4:])
    return None


_MODIFIER_LABELS = {e.KEY_LEFTCTRL: "Ctrl", e.KEY_LEFTSHIFT: "Shift", e.KEY_LEFTALT: "Alt", e.KEY_LEFTMETA: "Super"}


def _part_label(code: int) -> str:
    if code in _MODIFIER_LABELS:
        return _MODIFIER_LABELS[code]
    name = key_name(code) or str(code)
    if name in KEY_LABELS:
        return KEY_LABELS[name]
    return name.upper() if len(name) == 1 or (name[0] == "f" and name[1:].isdigit()) else name.title()


def combo_label(combo: str) -> str:
    codes = combo_codes(combo)
    return "+".join(_part_label(c) for c in codes) if codes else combo


def action_label(action: str) -> str:
    if action in ACTION_LABELS:
        return ACTION_LABELS[action]
    if action.startswith("key:"):
        return "Key: " + combo_label(action[4:])
    return action


def is_valid_action(action: str) -> bool:
    return action in ACTIONS or (action.startswith("key:") and combo_codes(action[4:]) is not None)


def combo_from_event(code: int, ctrl: bool = False, shift: bool = False, alt: bool = False,
                     sup: bool = False) -> str | None:
    """Combo string for a key the user just pressed (None for a bare modifier or an unusable key)."""
    name = key_name(code)
    if name is None or key_code(name) != code or code in MODIFIERS.values():
        return None
    mods = [m for m, on in (("ctrl", ctrl), ("alt", alt), ("shift", shift), ("super", sup)) if on]
    return "+".join(mods + [name])


def render_toml(overrides: dict[str, str]) -> str:
    """Config text: only the bindings that differ from the defaults, so new defaults still apply."""
    lines = [
        "# ControllerController keybinds. Easiest to change in the ControllerController settings window.",
        '# Format: BUTTON = "action". Anything not listed here uses the default.',
        f"# Buttons: {', '.join(BUTTONS)}",
        *textwrap.wrap(f"Actions: {', '.join(ACTIONS)}", width=98, initial_indent="# ", subsequent_indent="#   "),
        '# Any key or shortcut: "key:ctrl+shift+t", "key:f5", "key:pagedown" (modifiers: ctrl, shift, alt, super)',
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
        elif not isinstance(action, str) or not is_valid_action(action):
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
