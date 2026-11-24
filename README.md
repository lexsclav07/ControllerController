# ControllerController

Control your Linux PC from bed with an Xbox controller. Built for YouTube and Netflix, with
console-style web navigation (a focus box that jumps between links and buttons, and an
on-screen keyboard for text fields) and a mouse mode for everything else.

Target: Fedora / GNOME on Wayland (uses `/dev/uinput`, so it works without X11).

## How it works
- **Daemon** (`controllercontroller/`, Python): reads the pad via evdev and emits a virtual keyboard/mouse via `/dev/uinput`.
- **Browser extension** (`extension/`): console-style navigation. The stick moves a focus box between links and buttons, **A** clicks, and focusing a text box raises an on-screen keyboard. Talks to the daemon over `ws://127.0.0.1:8765` (only browser extensions are allowed to connect).
- **Modes are automatic**: when a browser window with the extension is focused you get focus-box navigation; anywhere else the left stick is a mouse pointer. **Guide** forces mouse mode on/off.
- **Fullscreen video**: the stick/D-pad send real arrow keys (seek/volume), **A** skips intros/ads/next-episode if offered, otherwise play/pause, **B** exits fullscreen.
- **Clicks are real**: **A** on a link or button presses a real Enter key, so popups, autoplay and fullscreen are allowed by the browser. **B** closes dialogs and menus before it goes back.
- **Looks native**: the focus ring and keyboard use libadwaita colours, follow your light/dark setting and (in Firefox) your GNOME accent colour.
- **Supported controllers**: Xbox controllers over USB or Bluetooth (both axis layouts are handled).

## Install
```bash
./install.sh          # daemon, starts on login
```
Extension:
- **Chrome**: `chrome://extensions` -> Developer mode -> *Load unpacked* -> pick `extension/`.
- **Firefox**: `about:debugging` -> This Firefox -> *Load Temporary Add-on* -> `extension/manifest.json` (and allow it on all sites under `about:addons` -> Permissions). Temporary add-ons vanish on restart until the extension is signed.

## Default controls
| Input | Action |
|---|---|
| Left stick / D-pad | Move focus box (browser) / pointer (mouse mode) |
| A / B | Select / Back |
| X | On-screen keyboard |
| Y | Search: opens the page's search box with the keyboard |
| LB / RB | Seek -10s / +10s |
| LT / RT | Volume down / up |
| Start / Select | Play-pause / Fullscreen |
| Guide | Force mouse mode on/off |
| Right stick | Scroll |

Only the button bindings are configurable: `~/.config/controllercontroller/config.toml` (created on first run).

## Development
```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                      # engine + bridge tests
.venv/bin/python tests/browser/run.py # runs the extension content scripts in headless Chrome
.venv/bin/python -m controllercontroller
```
