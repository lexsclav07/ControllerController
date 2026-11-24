# ControllerController

Control your Linux PC from bed with an Xbox controller. Built for YouTube and Netflix, with
console-style web navigation (a focus box that jumps between links and buttons, and an
on-screen keyboard for text fields) and a mouse mode for everything else.

Target: Fedora / GNOME on Wayland (uses `/dev/uinput`, so it works without X11).

## Status
Early development. Planned pieces:

- `controllercontroller/` – Python daemon: reads the pad (evdev), emits virtual keyboard/mouse (uinput), talks to the browser extension over a local WebSocket.
- `extension/` – Firefox/Chrome extension: spatial navigation, focus box, on-screen keyboard.
- `packaging/` – installer, udev rule, systemd user service.

## Default controls
| Input | Action |
|---|---|
| Left stick / D-pad | Move focus (browser) or pointer (mouse mode) |
| A / B | Select / Back |
| X | On-screen keyboard |
| LB / RB | Seek -10s / +10s |
| LT / RT | Volume down / up |
| Start / Select | Play-pause / Fullscreen |
| Guide | Toggle browser / mouse mode |
| Right stick | Scroll |

Only the button bindings are configurable: `~/.config/controllercontroller/config.toml`.
