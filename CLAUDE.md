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
```

## Architecture
- `controllercontroller/engine.py` is the core, free of I/O: it takes `out` (uinput), `media`, `bridge` as injected objects, so tests use fakes (`tests/test_engine.py`). `button()`/`abs_event()` consume pad events; `tick(dt)` (120 Hz from `controller.py`) emits pointer motion, scrolling and repeating nav.
- **Two modes**, chosen per event by `Engine.browser_mode` = extension connected AND a browser window focused AND not force-mouse (Guide). Browser mode sends `nav/select/back/osk` JSON to the extension instead of moving the pointer/clicking.
- `bridge.py` is a WebSocket server on 127.0.0.1:8765 that only accepts `moz-extension://`/`chrome-extension://` origins (any web page can reach localhost, so keep this check). Protocol is documented at the top of the file.
- Extension (`extension/`): `background.js` owns the socket and relays to the active tab; `osk.js` creates the closed shadow-DOM overlay (`window.__cc`) and the on-screen keyboard; `content.js` does spatial navigation (`collect` -> `pick`), the focus box, and "player mode" (when a video is fullscreen, directions go back to the daemon as real key presses because sites ignore synthetic keys).
- Pad button/axis mapping uses Linux xpad codes (`BTN_NORTH` = X, `BTN_WEST` = Y). The Bluetooth Xbox pad reports the right stick as `ABS_Z/RZ` and triggers as `ABS_BRAKE/GAS`; `controller.axis_remap` normalises it to the xpad layout, so keep new axis logic in xpad terms.
- `Bridge.send` delivers action messages (`nav/select/back/osk/search/mode`) only to the focused browser; the extension reports `typing` so the Engine does not tap stray keys (`f`, space) into a text field. Keys the extension may request are whitelisted in `engine.EXT_KEYS`.
- On native links/buttons `content.select()` focuses the element and asks the daemon for a real Enter key (trusted user activation); only div-style targets get synthetic events.
- `media.seek` needs `--` before negative offsets (busctl parses them as options); media calls return False on failure so the engine can fall back to key presses.
- Overlay UI lives in `extension/osk.js` (popover top layer so modal dialogs cannot cover it; styling uses libadwaita tokens and the `AccentColor` system colour).
- `tests/browser/run.py` stubs `chrome.runtime` and injects the content scripts into headless Chrome via CDP, because branded Chrome >=137 ignores `--load-extension`.
