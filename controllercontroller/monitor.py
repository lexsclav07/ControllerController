"""Live view of what the daemon sees from the pad.

The daemon listens on a user-only Unix socket ($XDG_RUNTIME_DIR/controllercontroller.sock) and streams
newline-delimited JSON to whoever connects: the settings window's "Live input" page and the
`controllercontroller monitor` command. Nothing here reaches the browser; web pages cannot open it.

  {"t": "hello",  "pad": str|null, "mode": "browser"|"mouse"|"game", "extension": bool, "paused": bool,
                  "axes": {...}, "down": [button, ...]}                       on connect
  {"t": "status", "pad": ..., "mode": ..., "extension": bool, "paused": bool} when any of them changes
  {"t": "button", "name": "A", "pressed": bool, "action": "select", "label": "Select / click",
                  "mode": "browser"|"mouse"|"game"|"paused", "ts": float}            every press and release
  {"t": "axes",   "lx", "ly", "rx", "ry": -1..1, "lt", "rt": 0..1}            up to 30 per second

client -> daemon: {"t": "pause", "value": bool}   ignore the pad while true (the buttons above still stream).
Pausing lasts only as long as the connection, so a window that is closed or crashes never leaves the
controller dead.

Axes are raw (no deadzone or curve); +y is down, as the kernel reports it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
import time
from collections import deque
from pathlib import Path
from typing import Callable

from .config import action_label

log = logging.getLogger(__name__)
AXES = ("lx", "ly", "rx", "ry", "lt", "rt")
MAX_BACKLOG = 1_000_000   # bytes a stuck client may fall behind before it is dropped


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "controllercontroller.sock"


# ---------------------------------------------------------------- daemon side
class Monitor:
    def __init__(self, path: Path | None = None, interval: float = 1 / 30) -> None:
        self.path = Path(path) if path else socket_path()
        self.interval = interval
        self.status_fn: Callable[[], dict] = dict   # mode / extension / paused, filled in by the daemon
        self.on_pause: Callable[[bool], None] = lambda _paused: None
        self.pad: str | None = None
        self.axes_state = dict.fromkeys(AXES, 0.0)
        self._down: set[str] = set()
        self._clients: set[asyncio.StreamWriter] = set()
        self._pausers: set[asyncio.StreamWriter] = set()   # clients that asked for the pad to be ignored
        self._status_sent: dict | None = None
        self._dirty = False

    # -- called by the Engine / pad reader (always on the event loop thread)
    def button(self, name: str, pressed: bool, action: str, mode: str) -> None:
        (self._down.add if pressed else self._down.discard)(name)
        self._broadcast({"t": "button", "name": name, "pressed": pressed, "action": action,
                         "label": action_label(action), "mode": mode, "ts": round(time.time(), 3)})

    def axes(self, values: dict[str, float]) -> None:
        self.axes_state = {k: round(values.get(k, 0.0), 3) for k in AXES}
        self._dirty = True

    def set_pad(self, name: str | None) -> None:
        self.pad = name
        if name is None:
            self._down.clear()
            self.axes_state = dict.fromkeys(AXES, 0.0)
            self._dirty = True

    # -- plumbing
    def _status(self) -> dict:
        return {"pad": self.pad, "mode": "mouse", "extension": False, "paused": False, **self.status_fn()}

    def _broadcast(self, msg: dict) -> None:
        if not self._clients:
            return
        data = (json.dumps(msg, separators=(",", ":")) + "\n").encode()
        for writer in list(self._clients):
            try:
                if writer.transport.get_write_buffer_size() > MAX_BACKLOG:
                    raise ConnectionError("client too slow")
                writer.write(data)
            except Exception:   # closing or stuck: forget it
                self._forget(writer)
                writer.close()

    def _forget(self, writer: asyncio.StreamWriter) -> None:
        self._clients.discard(writer)
        if writer in self._pausers:
            self._pausers.discard(writer)
            self.on_pause(bool(self._pausers))

    def _handle(self, writer: asyncio.StreamWriter, line: bytes) -> None:
        try:
            msg = json.loads(line)
        except ValueError:
            return
        if isinstance(msg, dict) and msg.get("t") == "pause":
            (self._pausers.add if msg.get("value") is True else self._pausers.discard)(writer)
            self.on_pause(bool(self._pausers))

    def flush(self) -> None:
        """Send changed axes and status (called ~30 times a second by serve())."""
        if self._dirty:
            self._dirty = False
            self._broadcast({"t": "axes", **self.axes_state})
        status = self._status()
        if status != self._status_sent:
            self._status_sent = status
            self._broadcast({"t": "status", **status})

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        hello = {"t": "hello", **self._status(), "axes": self.axes_state, "down": sorted(self._down)}
        writer.write((json.dumps(hello, separators=(",", ":")) + "\n").encode())
        self._clients.add(writer)
        try:
            while line := await reader.readline():
                self._handle(writer, line)
        except (OSError, ValueError):   # reset, or a line far longer than anything we expect
            pass
        finally:
            self._forget(writer)
            writer.close()

    async def serve(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.unlink(missing_ok=True)
            server = await asyncio.start_unix_server(self._client, path=str(self.path))
            os.chmod(self.path, 0o600)
        except OSError as exc:   # the live view is optional; never take the daemon down with it
            log.warning("live input socket unavailable: %s", exc)
            return
        log.info("live input on %s", self.path)
        async with server:
            while True:
                await asyncio.sleep(self.interval)
                self.flush()


# ------------------------------------------------------------ terminal client
BUTTON_ORDER = ("A", "B", "X", "Y", "LB", "RB", "LT", "RT", "SELECT", "START", "GUIDE", "L3", "R3",
                "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT")
SHORT = {"SELECT": "View", "START": "Menu", "GUIDE": "Xbox", "DPAD_UP": "Up", "DPAD_DOWN": "Down",
         "DPAD_LEFT": "Left", "DPAD_RIGHT": "Right"}
DEADZONE_NOTE = 0.2


def direction(x: float, y: float) -> str:
    """Words for a stick position (y is down-positive)."""
    if max(abs(x), abs(y)) < DEADZONE_NOTE:
        return "centre"
    vertical = "down" if y > DEADZONE_NOTE else "up" if y < -DEADZONE_NOTE else ""
    horizontal = "right" if x > DEADZONE_NOTE else "left" if x < -DEADZONE_NOTE else ""
    return "-".join(p for p in (vertical, horizontal) if p)


def centred_bar(value: float, width: int = 21) -> str:
    half = width // 2
    n = min(half, round(abs(value) * half))
    if value < 0:
        return " " * (half - n) + "█" * n + "│" + " " * half
    return " " * half + "│" + "█" * n + " " * (half - n)


def level_bar(value: float, width: int = 21) -> str:
    n = min(width, round(max(0.0, value) * width))
    return "█" * n + "░" * (width - n)


class Dashboard:
    """State of the pad as a terminal sees it. `apply` takes messages, `render` returns the screen text."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.connected = False
        self.status: dict = {}
        self.axes = dict.fromkeys(AXES, 0.0)
        self.down: set[str] = set()
        self.recent: deque[str] = deque(maxlen=8)

    def apply(self, msg: dict) -> None:
        kind = msg.get("t")
        if kind == "hello":
            self.connected = True
            self.status = {k: msg.get(k) for k in ("pad", "mode", "extension", "paused")}
            self.axes.update(msg.get("axes", {}))
            self.down = set(msg.get("down", []))
        elif kind == "status":
            self.status = {k: msg.get(k) for k in ("pad", "mode", "extension", "paused")}
        elif kind == "axes":
            self.axes.update({k: msg[k] for k in AXES if k in msg})
        elif kind == "button":
            (self.down.add if msg["pressed"] else self.down.discard)(msg["name"])
            self.recent.appendleft(log_line(msg))

    def render(self, color: bool = True) -> str:
        def style(text: str, code: str) -> str:
            return f"\x1b[{code}m{text}\x1b[0m" if color else text

        if not self.connected:
            return ("ControllerController live input\n\n  Waiting for the daemon...\n"
                    "  (is it running? systemctl --user status controllercontroller)\n")
        s = self.status
        pad = s.get("pad") or "no controller connected"
        lines = [
            style("ControllerController live input", "1") + style("    Ctrl-C to quit", "2"),
            f"  Controller: {pad}",
            f"  Mode: {s.get('mode', '?')}    Browser extension: {'connected' if s.get('extension') else 'not connected'}",
            *([style("  Controls paused: presses are shown but do nothing", "33")] if s.get("paused") else []),
            *([style("  Game running: the pad is left to the game", "33")] if s.get("mode") == "game" else []),
            "",
        ]
        for name, kx, ky in (("Left stick ", "lx", "ly"), ("Right stick", "rx", "ry")):
            x, y = self.axes[kx], self.axes[ky]
            lines.append(f"  {name} x {x:+.2f} {centred_bar(x)}  y {y:+.2f} {centred_bar(y)}  {direction(x, y)}")
        lines.append(f"  Left trigger  {self.axes['lt']:.2f} {level_bar(self.axes['lt'])}")
        lines.append(f"  Right trigger {self.axes['rt']:.2f} {level_bar(self.axes['rt'])}")
        lines.append("")
        chips = [style(f" {SHORT.get(b, b)} ", "7;1" if b in self.down else "2") for b in BUTTON_ORDER]
        lines.append("  " + " ".join(chips))
        lines += ["", style("  Recent", "2")]
        lines += [f"  {line}" for line in self.recent] or [style("  (press something)", "2")]
        return "\n".join(lines) + "\n"


def log_line(msg: dict) -> str:
    stamp = time.strftime("%H:%M:%S", time.localtime(msg.get("ts", time.time())))
    stamp += f".{int(msg.get('ts', 0) * 1000) % 1000:03d}"
    verb = "pressed " if msg["pressed"] else "released"
    name = SHORT.get(msg["name"], msg["name"])
    detail = f"-> {msg.get('label', msg.get('action', ''))}" if msg["pressed"] else ""
    return f"{stamp}  {name:<6} {verb} {detail}  [{msg.get('mode', '?')}]".rstrip()


def cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="controllercontroller monitor", description="Live view of the controller as the daemon sees it.")
    parser.add_argument("--json", action="store_true", help="print the raw JSON lines from the daemon")
    parser.add_argument("--log", action="store_true", help="print one line per button press instead of the live screen")
    parser.add_argument("--pause", action="store_true",
                        help="make the controller do nothing on the PC while this is running")
    args = parser.parse_args(argv)
    live = sys.stdout.isatty() and not (args.json or args.log)
    dash = Dashboard()
    waiting_said = False
    if live:
        sys.stdout.write("\x1b[?25l\x1b[2J")   # hide the cursor, clear the screen
    try:
        while True:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(str(socket_path()))
            except OSError:
                sock.close()
                if live:
                    sys.stdout.write("\x1b[H\x1b[J" + dash.render())
                    sys.stdout.flush()
                elif not waiting_said:
                    print("waiting for the daemon (systemctl --user status controllercontroller)...", file=sys.stderr)
                    waiting_said = True
                time.sleep(1)
                continue
            waiting_said = False
            dash.reset()
            if args.pause:   # lasts only as long as this connection
                sock.sendall(b'{"t":"pause","value":true}\n')
            _read(sock, dash, args, live)
            sock.close()
    except KeyboardInterrupt:
        return 0
    finally:
        if live:
            sys.stdout.write("\x1b[?25h\n")
            sys.stdout.flush()


def _read(sock: socket.socket, dash: Dashboard, args: argparse.Namespace, live: bool) -> None:
    """Read until the daemon goes away; redraw at most 20 times a second."""
    sock.settimeout(0.05)
    buffer, dirty, drawn = b"", False, 0.0
    while True:
        try:
            chunk = sock.recv(65536)
            if not chunk:
                return
            buffer += chunk
        except socket.timeout:
            pass
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if args.json:
                print(line.decode(errors="replace"), flush=True)
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            dash.apply(msg)
            dirty = True
            if not live:
                if msg.get("t") == "button":
                    print(log_line(msg), flush=True)
                elif msg.get("t") in ("hello", "status"):
                    s = dash.status
                    print(f"-- {s.get('pad') or 'no controller'} | {s.get('mode')} mode | "
                          f"extension {'connected' if s.get('extension') else 'not connected'}", flush=True)
        if live and dirty and time.monotonic() - drawn > 0.05:
            sys.stdout.write("\x1b[H" + dash.render().replace("\n", "\x1b[K\n") + "\x1b[J")
            sys.stdout.flush()
            drawn, dirty = time.monotonic(), False
