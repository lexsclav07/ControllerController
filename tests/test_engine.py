from evdev import ecodes as e

from controllercontroller import config
from controllercontroller.engine import Engine, axis


class FakeOut:
    def __init__(self):
        self.events = []

    def key(self, code, pressed):
        self.events.append(("key", code, pressed))

    def tap(self, code):
        self.events.append(("tap", code))

    def move(self, dx, dy):
        if dx or dy:
            self.events.append(("move", dx, dy))

    def scroll(self, dx, dy):
        if dx or dy:
            self.events.append(("scroll", dx, dy))


class FakeMedia:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def play_pause(self):
        self.calls.append("pp")
        return self.ok

    def seek(self, s):
        self.calls.append(("seek", s))
        return self.ok


def make(ok=True, bindings=None):
    out, media = FakeOut(), FakeMedia(ok)
    eng = Engine(out, bindings or dict(config.DEFAULT_BINDINGS), media, bg=lambda f, *a: f(*a))
    return eng, out, media


def test_axis_deadzone_and_extremes():
    assert axis(0, -32768, 32767) == 0.0
    assert axis(1000, -32768, 32767) == 0.0
    assert axis(32767, -32768, 32767) == 1.0
    assert axis(-32768, -32768, 32767) == -1.0


def test_select_is_held_so_drag_works():
    eng, out, _ = make()
    eng.button("A", True)
    eng.button("A", False)
    assert out.events == [("key", e.BTN_LEFT, True), ("key", e.BTN_LEFT, False)]


def test_back_taps_mouse_side_button_only_on_press():
    eng, out, _ = make()
    eng.button("B", True)
    eng.button("B", False)
    assert out.events == [("tap", e.BTN_SIDE)]


def test_seek_uses_mpris_then_falls_back_to_arrow_keys():
    eng, out, media = make(ok=True)
    eng.button("RB", True)
    assert media.calls == [("seek", 10)] and out.events == []
    eng, out, media = make(ok=False)
    eng.button("LB", True)
    assert out.events == [("tap", e.KEY_LEFT)]


def test_triggers_become_buttons_with_threshold():
    eng, out, _ = make()
    eng.abs_event(e.ABS_RZ, 255, 0, 255)
    eng.abs_event(e.ABS_RZ, 255, 0, 255)  # no duplicate press
    eng.abs_event(e.ABS_RZ, 0, 0, 255)
    assert out.events == [("key", e.KEY_VOLUMEUP, True), ("key", e.KEY_VOLUMEUP, False)]


def test_dpad_holds_arrow_keys():
    eng, out, _ = make()
    eng.abs_event(e.ABS_HAT0Y, -1, -1, 1)
    eng.abs_event(e.ABS_HAT0Y, 0, -1, 1)
    assert out.events == [("key", e.KEY_UP, True), ("key", e.KEY_UP, False)]


def test_stick_moves_pointer_with_subpixel_accumulation():
    eng, out, _ = make()
    eng.abs_event(e.ABS_X, 32767, -32768, 32767)
    for _ in range(120):
        eng.tick(1 / 120)
    total = sum(ev[1] for ev in out.events if ev[0] == "move")
    assert 1380 <= total <= 1400


def test_right_stick_up_scrolls_up():
    eng, out, _ = make()
    eng.abs_event(e.ABS_RY, -32768, -32768, 32767)
    eng.tick(0.1)
    assert out.events[0][0] == "scroll" and out.events[0][2] > 0


def test_release_all_lets_go_of_held_keys():
    eng, out, _ = make()
    eng.button("A", True)
    eng.release_all()
    assert out.events[-1] == ("key", e.BTN_LEFT, False)


def test_bad_config_falls_back_to_defaults(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[bindings]\nA = "nonsense"\nZZ = "back"\nB = "select"\n')
    b = config.load_bindings(p)
    assert b["A"] == "select" and b["B"] == "select"
    p.write_text("not [valid toml")
    assert config.load_bindings(p) == config.DEFAULT_BINDINGS


def test_default_config_written_on_first_run(tmp_path):
    p = tmp_path / "sub" / "c.toml"
    config.load_bindings(p)
    assert config.load_bindings(p) == config.DEFAULT_BINDINGS and p.exists()


class FakeBridge:
    def __init__(self, active=True):
        self.active, self.sent = active, []

    def send(self, msg):
        self.sent.append(msg)


def make_browser(active=True):
    out, media, bridge = FakeOut(), FakeMedia(), FakeBridge(active)
    eng = Engine(out, dict(config.DEFAULT_BINDINGS), media, bg=lambda f, *a: f(*a), bridge=bridge)
    return eng, out, bridge


def test_browser_mode_routes_select_back_osk_to_extension():
    eng, out, bridge = make_browser()
    for b in ("A", "B", "X"):
        eng.button(b, True)
        eng.button(b, False)
    assert [m["type"] for m in bridge.sent] == ["select", "back", "osk"]
    assert out.events == []


def test_browser_mode_stick_navigates_instead_of_moving_pointer():
    eng, out, bridge = make_browser()
    eng.abs_event(e.ABS_X, 32767, -32768, 32767)
    eng.tick(1 / 120)
    assert bridge.sent == [{"type": "nav", "dir": "right"}]
    assert not [ev for ev in out.events if ev[0] == "move"]


def test_nav_repeats_while_held_then_stops():
    eng, _, bridge = make_browser()
    eng.abs_event(e.ABS_Y, -32768, -32768, 32767)   # push up
    for _ in range(120):                              # 1 second
        eng.tick(1 / 120)
    assert len(bridge.sent) in (5, 6)   # at 0s, 0.4s, then every 0.15s
    assert all(m == {"type": "nav", "dir": "up"} for m in bridge.sent)
    eng.abs_event(e.ABS_Y, 0, -32768, 32767)
    n = len(bridge.sent)
    eng.tick(1.0)
    assert len(bridge.sent) == n


def test_dpad_navigates_once_per_press_in_browser_mode():
    eng, out, bridge = make_browser()
    eng.abs_event(e.ABS_HAT0X, 1, -1, 1)
    eng.tick(1 / 120)
    eng.abs_event(e.ABS_HAT0X, 0, -1, 1)
    eng.tick(1 / 120)
    assert bridge.sent == [{"type": "nav", "dir": "right"}]
    assert out.events == []


def test_inactive_browser_falls_back_to_mouse_mode():
    eng, out, bridge = make_browser(active=False)
    eng.button("A", True)
    assert out.events == [("key", e.BTN_LEFT, True)] and bridge.sent == []


def test_guide_forces_mouse_mode_and_back():
    eng, out, bridge = make_browser()
    eng.button("GUIDE", True)
    assert eng.force_mouse and not eng.browser_mode
    eng.button("GUIDE", True)
    assert eng.browser_mode


def test_extension_keys_are_whitelisted():
    eng, out, _ = make_browser()
    eng.ext_key("left")
    eng.ext_key("rm -rf")
    assert out.events == [("tap", e.KEY_LEFT)]
