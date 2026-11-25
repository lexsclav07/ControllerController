# ControllerController

Control your Linux PC from bed with an Xbox controller. Built for YouTube and Netflix, with
console-style web navigation (a focus box that jumps between links and buttons, and an
on-screen keyboard for text fields) and a mouse mode for everything else.

Target: Fedora / GNOME on Wayland (uses `/dev/uinput`, so it works without X11).

## How it works
- **Daemon** (`controllercontroller/`, Python): reads the pad via evdev and emits a virtual keyboard/mouse via `/dev/uinput`.
- **Browser extension** (`extension/`): console-style navigation. The stick moves a focus box between links and buttons, **A** clicks, and selecting a text box raises an on-screen keyboard. Talks to the daemon over `ws://127.0.0.1:8765` (only browser extensions are allowed to connect).
- **Modes are automatic**: when a browser window with the extension is focused you get focus-box navigation; anywhere else the left stick is a mouse pointer. **Guide** forces mouse mode on/off.
- **Hand-off**: touch the real mouse or keyboard and the focus box (and the on-screen keyboard's selection) disappears; the first controller press brings it back where it was without clicking anything.
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
| X | Show this list of controls on screen (it reflects your own bindings) |
| Y | Search: opens the page's search box with the keyboard |
| LB / RB | Seek -10s / +10s |
| LT / RT | Volume down / up |
| Start / Select | Play-pause / Fullscreen |
| L3 / R3 (click sticks) | Previous / next browser tab |
| Guide | Force mouse mode on/off |
| Right stick | Scroll |

Only the button bindings are configurable. Open **ControllerController** from your app grid (or run `~/.local/share/controllercontroller/venv/bin/python -m controllercontroller settings`) to change what each button does; changes apply immediately, no restart. They are stored in `~/.config/controllercontroller/config.toml`, which only lists the buttons you changed, so new defaults still apply to the rest.

### Everything a button can do
Pick a button in the settings window to get a searchable list (nothing below is bound by default):
- **Playback**: mute, next/previous track, skip intro / ad / next episode, and YouTube's own hotkeys (captions, next/previous video, faster/slower, theater mode).
- **Browser**: new / close / reopen tab, reload, forward, address bar, find, zoom, scroll, page up/down, top/bottom of page.
- **Keyboard keys**: Enter, Escape, Space, Tab, Backspace, Delete, copy / cut / paste / select all / undo.
- **System**: Activities overview, switch window, screenshot, lock screen, close window.
- **Record a key**: press any key or combination (for example Ctrl+Shift+T) and the button types it. In `config.toml` that is `X = "key:ctrl+shift+t"`; modifiers are `ctrl`, `shift`, `alt`, `super`, and key names are the Linux names without `KEY_` (`f5`, `pagedown`, `enter`, ...). Power and sleep keys are refused.

Arrow, page, home/end, backspace, delete and tab keys keep repeating while the button is held; everything else is a single press.

## Development
```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest                      # engine + bridge tests
.venv/bin/python tests/browser/run.py # runs the extension content scripts in headless Chrome
.venv/bin/python -m controllercontroller
```
