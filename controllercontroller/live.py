"""The settings window's "Live input" page: a drawn controller that follows the real one."""

from __future__ import annotations

import json
import math
import socket
from collections import deque

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .monitor import AXES, SHORT, direction, socket_path  # noqa: E402

W, H = 520, 340   # drawing is laid out on this canvas and scaled to fit
FACE = {"A": ((380, 180), (0.15, 0.64, 0.41)), "B": ((412, 148), (0.75, 0.11, 0.16)),
        "X": ((348, 148), (0.11, 0.44, 0.85)), "Y": ((380, 116), (0.90, 0.65, 0.04))}
DPAD = {"DPAD_UP": (-11, -37, 22, 26), "DPAD_DOWN": (-11, 11, 22, 26),
        "DPAD_LEFT": (-37, -11, 26, 22), "DPAD_RIGHT": (11, -11, 26, 22)}
STICKS = {"L3": ((140, 148), "lx", "ly"), "R3": ((320, 238), "rx", "ry")}
DPAD_CENTRE = (205, 238)


def _round_rect(cr, x: float, y: float, w: float, h: float, r: float) -> None:
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class ControllerView(Gtk.DrawingArea):
    """Gamepad diagram; buttons light up, sticks and triggers move."""

    def __init__(self) -> None:
        super().__init__(content_width=W, content_height=H, hexpand=True, vexpand=True)
        self.axes = dict.fromkeys(AXES, 0.0)
        self.down: set[str] = set()
        self.set_draw_func(self._draw)

    def update(self, axes: dict | None = None, down: set[str] | None = None) -> None:
        if axes is not None:
            self.axes.update({k: axes[k] for k in AXES if k in axes})
        if down is not None:
            self.down = set(down)
        self.queue_draw()

    # -- drawing
    def _draw(self, _area, cr, width: int, height: int) -> None:
        fg = self.get_color()
        accent = Adw.StyleManager.get_default().get_accent_color_rgba()

        def ink(alpha: float, colour=None) -> None:
            c = colour or (fg.red, fg.green, fg.blue)
            cr.set_source_rgba(c[0], c[1], c[2], alpha)

        def lit(c=None):
            return c or (accent.red, accent.green, accent.blue)

        def text(label: str, x: float, y: float, size: float, alpha: float = 0.85, colour=None) -> None:
            cr.select_font_face("sans", 0, 1)
            cr.set_font_size(size)
            ext = cr.text_extents(label)
            ink(alpha, colour)
            cr.move_to(x - ext.width / 2 - ext.x_bearing, y - ext.height / 2 - ext.y_bearing)
            cr.show_text(label)

        scale = min(width / W, height / H)
        cr.translate((width - W * scale) / 2, (height - H * scale) / 2)
        cr.scale(scale, scale)
        cr.set_line_width(2)

        # body
        _round_rect(cr, 30, 62, 460, 250, 84)
        ink(0.05)
        cr.fill_preserve()
        ink(0.16)
        cr.stroke()

        def pad(name: str, shape, label: str, label_size: float = 15, colour=None) -> None:
            on = name in self.down
            shape()
            if on:
                ink(1, lit(colour))
                cr.fill()
            else:
                ink(0.10)
                cr.fill_preserve()
                ink(0.28)
                cr.stroke()
            text(label, *self._centre, label_size, 1.0 if on and not colour else 0.9,
                 (1, 1, 1) if on else colour)

        def circle(cx, cy, r):
            self._centre = (cx, cy)
            return lambda: (cr.new_path(), cr.arc(cx, cy, r, 0, 2 * math.pi))

        def rect(x, y, w, h, r):
            self._centre = (x + w / 2, y + h / 2)
            return lambda: (cr.new_path(), _round_rect(cr, x, y, w, h, r))

        # bumpers and trigger meters
        pad("LB", rect(84, 40, 110, 24, 11), "LB", 13)
        pad("RB", rect(326, 40, 110, 24, 11), "RB", 13)
        for key, x, label in (("lt", 84, "LT"), ("rt", 326, "RT")):
            _round_rect(cr, x, 8, 110, 24, 11)
            ink(0.10)
            cr.fill()
            if self.axes[key] > 0.01:
                cr.save()
                _round_rect(cr, x, 8, 110, 24, 11)
                cr.clip()
                ink(1, lit())
                cr.rectangle(x, 8, 110 * self.axes[key], 24)
                cr.fill()
                cr.restore()
            text(label, x + 55, 20, 13, 0.9 if self.axes[key] > 0.5 else 0.65,
                 (1, 1, 1) if self.axes[key] > 0.5 else None)

        # sticks: ring, dot that follows the raw position, filled while clicked
        for name, ((cx, cy), kx, ky) in STICKS.items():
            self._centre = (cx, cy)
            cr.new_path()
            cr.arc(cx, cy, 46, 0, 2 * math.pi)
            if name in self.down:
                ink(0.35, lit())
                cr.fill_preserve()
            ink(0.28)
            cr.stroke()
            cr.new_path()
            cr.arc(cx, cy, 46 * 0.18, 0, 2 * math.pi)   # the deadzone the daemon ignores
            ink(0.18)
            cr.set_dash([3, 3])
            cr.stroke()
            cr.set_dash([])
            x, y = self.axes[kx], self.axes[ky]
            cr.new_path()
            cr.arc(cx + x * 36, cy + y * 36, 11, 0, 2 * math.pi)
            ink(1, lit())
            cr.fill()

        # d-pad
        dx, dy = DPAD_CENTRE
        cr.new_path()
        _round_rect(cr, dx - 11, dy - 11, 22, 22, 3)
        ink(0.10)
        cr.fill()
        for name, (ox, oy, w, h) in DPAD.items():
            on = name in self.down
            cr.new_path()
            _round_rect(cr, dx + ox, dy + oy, w, h, 5)
            if on:
                ink(1, lit())
                cr.fill()
            else:
                ink(0.10)
                cr.fill_preserve()
                ink(0.28)
                cr.stroke()

        # face buttons in their Xbox colours
        for name, ((fx, fy), colour) in FACE.items():
            pad(name, circle(fx, fy, 17), name, 16, colour)

        # centre buttons
        pad("SELECT", circle(232, 148, 9), "", 1)
        pad("START", circle(288, 148, 9), "", 1)
        pad("GUIDE", circle(260, 108, 16), "", 1)
        text("View", 232, 168, 10, 0.5)
        text("Menu", 288, 168, 10, 0.5)


class Feed:
    """Reads the daemon's JSON lines on the GLib main loop and reconnects whenever it goes away."""

    def __init__(self, on_message, on_state) -> None:
        self.on_message, self.on_state = on_message, on_state
        self._sock: socket.socket | None = None
        self._buffer = b""
        self._watch = 0
        self._retry = 0
        self._stopped = False
        self._want_pause = False

    def set_paused(self, value: bool) -> None:
        """Ask the daemon to ignore the pad (it forgets this when we disconnect)."""
        self._want_pause = value
        self._send_pause()

    def _send_pause(self) -> None:
        if self._sock:
            try:
                self._sock.send(json.dumps({"t": "pause", "value": self._want_pause}).encode() + b"\n")
            except OSError:
                pass   # the read side notices a dead connection

    def start(self) -> None:
        self._retry = 0
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(socket_path()))
        except OSError:
            sock.close()
            self.on_state(False)
            self._schedule()
            return
        sock.setblocking(False)
        self._sock, self._buffer = sock, b""
        self._watch = GLib.io_add_watch(sock.fileno(), GLib.PRIORITY_DEFAULT,
                                        GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._readable)
        if self._want_pause:
            self._send_pause()

    def stop(self) -> None:
        self._stopped = True
        self._drop()
        if self._retry:
            GLib.source_remove(self._retry)
            self._retry = 0

    def _schedule(self) -> None:
        if not self._stopped:
            self._retry = GLib.timeout_add_seconds(1, self.start)

    def _drop(self) -> None:
        if self._watch:
            GLib.source_remove(self._watch)
            self._watch = 0
        if self._sock:
            self._sock.close()
            self._sock = None

    def _readable(self, _fd, _cond) -> bool:
        try:
            data = self._sock.recv(65536)
        except BlockingIOError:
            return True
        except OSError:
            data = b""
        if not data:
            self._watch = 0   # returning False removes this watch
            self._drop()
            self.on_state(False)
            self._schedule()
            return False
        self._buffer += data
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            try:
                self.on_message(json.loads(line))
            except ValueError:
                pass
        return True


class LivePage(Gtk.Box):
    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                         margin_top=12, margin_bottom=18, margin_start=18, margin_end=18)
        self.banner = Adw.Banner(title="The ControllerController daemon isn't running", revealed=True)
        self.status = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, css_classes=["title-4"])
        note = Gtk.Label(label="While this window is in front the controller doesn't do anything on your PC, "
                               "so you can press buttons freely.",
                         wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim-label"])
        self.view = ControllerView()
        self.readout = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER,
                                 css_classes=["caption", "dim-label", "monospace"])
        self.recent = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        self._rows: deque = deque()
        history = Adw.PreferencesGroup(title="Recent presses")
        history.add(self.recent)
        for child in (self.banner, self.status, note, self.view, self.readout, history):
            self.append(child)
        self.down: set[str] = set()
        self.pad: str | None = None
        self._show_status({})
        self.feed = Feed(self.on_message, self._on_state)

    def start(self) -> None:
        self.feed.start()

    def stop(self) -> None:
        self.feed.stop()

    def _on_state(self, connected: bool) -> None:
        self.banner.set_revealed(not connected)
        if not connected:
            self.down.clear()
            self.view.update(dict.fromkeys(AXES, 0.0), self.down)
            self._show_status({})

    def _show_status(self, msg: dict) -> None:
        pad = msg.get("pad")
        if not msg:
            self.status.set_label("Waiting for the daemon…")
        elif not pad:
            self.status.set_label("No controller connected")
        else:
            mode = {"browser": "Browser mode", "game": "Game running, pad left to the game"}.get(
                msg.get("mode"), "Mouse mode")
            paused = " · Controls paused" if msg.get("paused") else ""
            self.status.set_label(f"{pad} · {mode}{paused}")

    def _show_readout(self) -> None:
        a = self.view.axes
        self.readout.set_label(
            f"Left stick {a['lx']:+.2f} {a['ly']:+.2f} ({direction(a['lx'], a['ly'])})   "
            f"Right stick {a['rx']:+.2f} {a['ry']:+.2f} ({direction(a['rx'], a['ry'])})\n"
            f"Left trigger {a['lt']:.2f}   Right trigger {a['rt']:.2f}")

    def on_message(self, msg: dict) -> None:
        kind = msg.get("t")
        if kind == "hello":
            self.banner.set_revealed(False)
            self.down = set(msg.get("down", []))
            self.view.update(msg.get("axes", {}), self.down)
            self._show_status(msg)
            self._show_readout()
        elif kind == "status":
            self._show_status(msg)
        elif kind == "axes":
            self.view.update(msg)
            self._show_readout()
        elif kind == "button":
            (self.down.add if msg["pressed"] else self.down.discard)(msg["name"])
            self.view.update(down=self.down)
            if msg["pressed"]:
                self._log(msg)

    def _log(self, msg: dict) -> None:
        row = Adw.ActionRow(title=SHORT.get(msg["name"], msg["name"]), subtitle=msg.get("label") or msg["action"])
        row.add_suffix(Gtk.Label(label=msg.get("mode", ""), css_classes=["dim-label", "caption"]))
        self.recent.prepend(row)
        self._rows.append(row)
        while len(self._rows) > 5:
            self.recent.remove(self._rows.popleft())
