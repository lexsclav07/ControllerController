# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Linux app (Fedora/GNOME Wayland) that lets an Xbox controller drive the PC from a couch: media control, console-style web navigation, mouse fallback. Goal is zero-config; only button bindings are user-configurable.

## Commands
```bash
.venv/bin/pip install -e '.[dev]'                 # setup (venv is gitignored)
.venv/bin/pytest                                   # all unit tests
.venv/bin/pytest tests/test_engine.py -k nav       # single test
.venv/bin/python -W ignore tests/browser/run.py    # headless-Chrome smoke test of extension/*.js
.venv/bin/python -m controllercontroller           # run the daemon (needs write access to /dev/uinput)
controllercontroller monitor                       # live pad view in the terminal (--log / --json); the installer puts `controllercontroller` in ~/.local/bin
~/.local/share/controllercontroller/venv/bin/python -m controllercontroller settings   # keybind window (GTK4/libadwaita; needs system python3-gobject + evdev, so use the installed venv, not .venv)
```

## Architecture
- `controllercontroller/engine.py` is the core, free of I/O: it takes `out` (uinput), `media`, `bridge` as injected objects, so tests use fakes (`tests/test_engine.py`). `button()`/`abs_event()` consume pad events; `tick(dt)` (120 Hz from `controller.py`) emits pointer motion, scrolling and repeating nav.
- **Two modes**, chosen per event by `Engine.browser_mode` = extension connected AND a browser window focused AND not force-mouse (Guide). Browser mode sends `nav/select/back/osk` JSON to the extension instead of moving the pointer/clicking.
- **Games**: `games.py` polls `/proc` for Steam's `reaper SteamLaunch AppId=N` (GNOME refuses window introspection, so focus can't be queried). `Engine.standing_down` = game running and no focused extension browser; the pad is then ignored (mode `game`). Every ignore reason goes through `Engine._sync`, which releases held keys on the way in.
- `bridge.py` is a WebSocket server on 127.0.0.1:8765 that only accepts `moz-extension://`/`chrome-extension://` origins (any web page can reach localhost, so keep this check). Protocol is documented at the top of the file.
- Extension (`extension/`): `background.js` owns the socket and relays to the active tab; `osk.js` creates the closed shadow-DOM overlay (`window.__cc`) and the on-screen keyboard; `content.js` does spatial navigation (`collect` -> `pick`), the focus box, and "player mode" (when a video is fullscreen, directions go back to the daemon as real key presses because sites ignore synthetic keys).
- Actions: `config.ACTION_GROUPS` (settings window order) -> `ACTIONS`; `SHORTCUTS` maps ids to key combos, and any `key:<combo>` string is valid too (`key_codes`/`combo_codes` parse it, `BLOCKED_KEYS` refuses power keys). `Engine._press_keys` holds navigation keys (`REPEATABLE`) and taps the rest via `Output.chord`; `PAGE_SHORTCUTS` (YouTube letters) are skipped while typing. The virtual keyboard declares the whole key range, so new keys need no uinput change. `skip` is an extension action (like select/back).
- Keybinds: `config.py` owns defaults, friendly labels (shared by the GTK settings window and checked against `BUTTONS`/`ACTIONS` in tests) and `save_bindings`, which writes only overrides so new defaults still reach existing users. The daemon's `config.watch` task reloads the dict **in place** when the file changes (the Engine holds the same dict).
- Pad button/axis mapping uses Linux xpad codes (`BTN_NORTH` = X, `BTN_WEST` = Y). The Bluetooth Xbox pad reports the right stick as `ABS_Z/RZ` and triggers as `ABS_BRAKE/GAS`; `controller.axis_remap` normalises it to the xpad layout, so keep new axis logic in xpad terms.
- `Bridge.send` delivers action messages (`nav/select/back/osk/search/mode`) only to the focused browser; the extension reports `typing` so the Engine does not tap stray keys (`f`, space) into a text field. The `help` action sends the live bindings plus their labels (`config.action_label`) to the extension, which draws the controls cheat sheet from them (`osk.js` `showHelp`), so never hard-code the list. Keys the extension may request are whitelisted in `engine.EXT_KEYS`.
- Keyboard/mouse hand-off: trusted `keydown`/`mousedown`/real `mousemove` in the page set `idle` (box and OSK selection hidden) in `content.js`. The daemon's own injected keys look identical, so `Engine._fire` sends a `ctl` message first and `content.js` ignores input within `CTL_WINDOW` of any daemon message or `sendKey` (either order). The first nav/select while idle only reveals the box.
- On native links/buttons `content.select()` focuses the element and asks the daemon for a real Enter key (trusted user activation); only div-style targets get synthetic events.
- `media.seek` needs `--` before negative offsets (busctl parses them as options); media calls return False on failure so the engine can fall back to key presses.
- Live view: `monitor.py` is both ends. `Monitor` (daemon) streams JSON lines over a 0600 Unix socket in `$XDG_RUNTIME_DIR`; the Engine feeds it (`button` events with action/mode, raw axes via `RAW_AXES`) and `controller.run` reports the pad name. Clients are `Dashboard`/`cli` (terminal: `controllercontroller monitor [--json|--log]`) and `live.py` (the settings window's Live input page, a cairo `ControllerView` fed by `Feed` on the GLib loop). Clients may send `{"t":"pause","value":true}`: `Engine.set_paused` then ignores the pad (buttons still stream with mode `paused`) for exactly as long as that connection lives, so a closed or crashed window can never leave the pad dead; the settings window sends it while it `is-active`. The protocol is in the `monitor.py` docstring; a failing socket must never take the daemon down.
- Overlay UI lives in `extension/osk.js` (popover top layer so modal dialogs cannot cover it; styling uses libadwaita tokens and the `AccentColor` system colour).
- `tests/browser/run.py` stubs `chrome.runtime` and injects the content scripts into headless Chrome via CDP, because branded Chrome >=137 ignores `--load-extension`.
