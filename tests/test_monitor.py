import asyncio
import json
import os
import re

from evdev import ecodes as e

from controllercontroller import config
from controllercontroller.engine import Engine
from controllercontroller.monitor import AXES, Dashboard, Monitor, centred_bar, direction, level_bar, log_line


class FakeMonitor:
    def __init__(self):
        self.buttons, self.axes_seen = [], []

    def button(self, name, pressed, action, mode):
        self.buttons.append((name, pressed, action, mode))

    def axes(self, values):
        self.axes_seen.append(dict(values))


class NullOut:
    def __getattr__(self, _name):
        return lambda *a, **k: None


def _engine(**kw):
    mon = FakeMonitor()
    return Engine(NullOut(), dict(config.DEFAULT_BINDINGS), media=None, monitor=mon, **kw), mon


def test_engine_reports_buttons_with_their_action_and_mode():
    eng, mon = _engine()
    eng.button("A", True)
    eng.button("A", False)
    assert mon.buttons == [("A", True, "select", "mouse"), ("A", False, "select", "mouse")]


def test_engine_reports_raw_axes_without_deadzone_and_triggers_as_zero_to_one():
    eng, mon = _engine()
    eng.abs_event(e.ABS_X, 2000, -32768, 32767)      # inside the deadzone: still visible raw
    assert 0.05 < mon.axes_seen[-1]["lx"] < 0.07 and eng.sticks["lx"] == 0.0
    eng.abs_event(e.ABS_Y, -32768, -32768, 32767)
    assert mon.axes_seen[-1]["ly"] == -1.0
    eng.abs_event(e.ABS_RZ, 1023, 0, 1023)
    assert mon.axes_seen[-1]["rt"] == 1.0 and mon.axes_seen[-1]["lt"] == 0.0


def test_dashboard_tracks_buttons_sticks_and_renders_plain_text():
    d = Dashboard()
    assert "Waiting for the daemon" in d.render(color=False)
    d.apply({"t": "hello", "pad": "Xbox Wireless Controller", "mode": "browser", "extension": True,
             "axes": {"lx": 0.5, "ly": -0.9}, "down": ["LB"]})
    d.apply({"t": "axes", "rt": 1.0})
    d.apply({"t": "button", "name": "A", "pressed": True, "action": "select", "label": "Select / click",
             "mode": "browser", "ts": 1700000000.123})
    text = d.render(color=False)
    assert "Xbox Wireless Controller" in text and "Mode: browser" in text and "connected" in text
    assert "x +0.50" in text and "y -0.90" in text and "up-right" in text
    assert re.search(r"A\s+pressed", text) and "-> Select / click" in text
    assert d.down == {"LB", "A"}
    d.apply({"t": "button", "name": "A", "pressed": False, "action": "select", "label": "", "mode": "browser"})
    assert d.down == {"LB"}
    assert "\x1b[7;1m LB " in d.render(color=True)   # held buttons are drawn in reverse video


def test_bars_and_directions():
    assert direction(0.05, -0.1) == "centre" and direction(-0.8, 0.0) == "left" and direction(0.5, 0.9) == "down-right"
    assert len(centred_bar(-1)) == len(centred_bar(1)) == len(centred_bar(0)) == 21
    assert centred_bar(-1).startswith("██████████│") and centred_bar(1).endswith("│██████████")
    assert level_bar(0.0) == "░" * 21 and level_bar(1.0) == "█" * 21
    assert "released" in log_line({"t": "button", "name": "START", "pressed": False, "action": "x", "ts": 0.0})


def test_monitor_streams_hello_buttons_axes_and_status_over_a_user_only_socket(tmp_path):
    path = tmp_path / "cc.sock"

    async def scenario():
        mon = Monitor(path, interval=0.02)
        mon.status_fn = lambda: {"mode": "browser", "extension": True}
        mon.set_pad("Test Pad")
        mon.button("B", True, "back", "browser")        # held before the client connects
        task = asyncio.create_task(mon.serve())
        await asyncio.sleep(0.15)
        assert oct(os.stat(path).st_mode & 0o777) == "0o600"
        reader, writer = await asyncio.open_unix_connection(str(path))
        hello = json.loads(await asyncio.wait_for(reader.readline(), 2))
        assert hello["t"] == "hello" and hello["pad"] == "Test Pad" and hello["mode"] == "browser"
        assert hello["down"] == ["B"] and set(hello["axes"]) == set(AXES)
        mon.button("A", True, "select", "browser")
        mon.axes({"lx": 0.5, "ly": 0.25, "lt": 0.75})
        msgs = [json.loads(await asyncio.wait_for(reader.readline(), 2)) for _ in range(2)]
        button = next(m for m in msgs if m["t"] == "button")
        assert button["name"] == "A" and button["label"] == "Select / click" and button["pressed"] is True
        axes = next(m for m in msgs if m["t"] == "axes")
        assert axes["lx"] == 0.5 and axes["lt"] == 0.75
        mon.set_pad(None)                                # unplugged: status goes out, state resets
        status = json.loads(await asyncio.wait_for(reader.readline(), 2))
        while status["t"] != "status":
            status = json.loads(await asyncio.wait_for(reader.readline(), 2))
        assert status["pad"] is None
        writer.close()
        task.cancel()

    asyncio.run(scenario())


def test_monitor_without_a_socket_dir_does_not_crash_the_daemon(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    asyncio.run(Monitor(blocker / "cc.sock").serve())   # logs a warning and returns


def test_a_client_can_pause_the_pad_only_while_it_stays_connected(tmp_path):
    path = tmp_path / "cc.sock"
    calls = []

    async def scenario():
        mon = Monitor(path, interval=0.02)
        mon.on_pause = calls.append
        task = asyncio.create_task(mon.serve())
        await asyncio.sleep(0.15)
        r1, w1 = await asyncio.open_unix_connection(str(path))
        r2, w2 = await asyncio.open_unix_connection(str(path))
        w1.write(b'{"t":"pause","value":true}\n'); w2.write(b'{"t":"pause","value":true}\n')
        w2.write(b"garbage\n")                         # junk is ignored, not fatal
        await asyncio.sleep(0.1)
        assert calls[-1] is True
        w1.close(); await asyncio.sleep(0.1)
        assert calls[-1] is True                         # the other client still wants it paused
        w2.write(b'{"t":"pause","value":false}\n'); await asyncio.sleep(0.1)
        assert calls[-1] is False
        w2.write(b'{"t":"pause","value":true}\n'); await asyncio.sleep(0.1)
        assert calls[-1] is True
        w2.close(); await asyncio.sleep(0.1)             # closing the window (or a crash) un-pauses
        assert calls[-1] is False
        task.cancel()

    asyncio.run(scenario())


def test_dashboard_says_when_controls_are_paused():
    d = Dashboard()
    d.apply({"t": "hello", "pad": "P", "mode": "mouse", "extension": False, "paused": True, "axes": {}, "down": []})
    assert "Controls paused" in d.render(color=False)
    d.apply({"t": "status", "pad": "P", "mode": "mouse", "extension": False, "paused": False})
    assert "Controls paused" not in d.render(color=False)
