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

    def combo(self, modifier, code):
        self.events.append(("combo", modifier, code))

    def chord(self, codes):
        self.events.append(("chord", tuple(codes)))

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
        self.active, self.sent, self.typing = active, [], False

    def send(self, msg):
        self.sent.append(msg)


def make_browser(active=True):
    out, media, bridge = FakeOut(), FakeMedia(), FakeBridge(active)
    eng = Engine(out, dict(config.DEFAULT_BINDINGS), media, bg=lambda f, *a: f(*a), bridge=bridge)
    return eng, out, bridge


def test_browser_mode_routes_select_back_osk_to_extension():
    eng, out, bridge = make_browser()
    eng.bindings["X"] = "osk"   # X is "help" by default
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


# ---- audit regressions -------------------------------------------------

def test_bluetooth_xbox_layout_is_remapped_to_xpad():
    from controllercontroller.controller import axis_remap
    bt = {e.ABS_X, e.ABS_Y, e.ABS_Z, e.ABS_RZ, e.ABS_GAS, e.ABS_BRAKE, e.ABS_HAT0X, e.ABS_HAT0Y}
    usb = {e.ABS_X, e.ABS_Y, e.ABS_RX, e.ABS_RY, e.ABS_Z, e.ABS_RZ, e.ABS_HAT0X}
    m = axis_remap(bt)
    assert m[e.ABS_Z] == e.ABS_RX and m[e.ABS_RZ] == e.ABS_RY
    assert m[e.ABS_GAS] == e.ABS_RZ and m[e.ABS_BRAKE] == e.ABS_Z
    assert axis_remap(usb) == {}

    eng, out, _ = make()   # right stick fully down on the BT pad, then RT squeezed
    eng.abs_event(m[e.ABS_RZ], 65535, 0, 65535)
    eng.tick(0.1)
    assert out.events and out.events[0][0] == "scroll" and out.events[0][2] < 0
    eng.abs_event(m[e.ABS_GAS], 1023, 0, 1023)
    assert ("key", e.KEY_VOLUMEUP, True) in out.events


def test_typing_blocks_stray_keys_but_not_media_calls():
    eng, out, bridge = make_browser()
    bridge.typing = True
    eng.button("SELECT", True)   # fullscreen -> "f" would be typed into the field
    assert out.events == []
    eng.media.ok = False
    eng.button("START", True)    # play/pause fallback is a space key: also suppressed
    assert out.events == []
    bridge.typing = False
    eng.button("SELECT", True)
    assert out.events == [("tap", e.KEY_F)]


def test_daemon_key_presses_are_announced_to_the_extension_first():
    # The page can't tell the pad's injected keys from the real keyboard; "ctl" lets it keep the focus box.
    eng, out, bridge = make_browser()
    eng.button("SELECT", True)   # fullscreen -> "f"
    assert bridge.sent == [{"type": "ctl"}] and out.events == [("tap", e.KEY_F)]
    bridge.sent.clear()
    bridge.typing = True         # suppressed key: nothing injected, nothing announced
    eng.button("SELECT", True)
    assert bridge.sent == []


def test_search_goes_to_extension_in_browser_mode_and_slash_otherwise():
    eng, out, bridge = make_browser()
    eng.button("Y", True)
    assert bridge.sent == [{"type": "search"}] and out.events == []
    eng, out, _ = make_browser(active=False)
    eng.button("Y", True)
    assert out.events == [("tap", e.KEY_SLASH)]


def test_guide_tells_extension_about_mode():
    eng, _, bridge = make_browser()
    eng.button("GUIDE", True)
    assert bridge.sent == [{"type": "mode", "mouse": True}]


def test_extension_may_press_enter_and_slash():
    eng, out, _ = make_browser()
    eng.ext_key("enter"); eng.ext_key("slash")
    assert out.events == [("tap", e.KEY_ENTER), ("tap", e.KEY_SLASH)]


def test_stick_clicks_switch_tabs_in_both_modes():
    for eng, out in (make()[:2], make_browser()[:2]):
        eng.button("R3", True); eng.button("R3", False)
        eng.button("L3", True)
        assert out.events == [("combo", e.KEY_LEFTCTRL, e.KEY_PAGEDOWN),
                              ("combo", e.KEY_LEFTCTRL, e.KEY_PAGEUP)]


def test_help_sends_live_bindings_to_extension_and_is_silent_in_mouse_mode():
    eng, out, bridge = make_browser()
    eng.bindings["R3"] = "fullscreen"          # remapped bindings must show up in the overlay
    eng.button("X", True)
    msg = bridge.sent[0]
    assert msg["type"] == "help" and msg["bindings"]["R3"] == "fullscreen" and msg["bindings"]["X"] == "help"
    eng, out, bridge = make_browser(active=False)
    eng.button("X", True)
    assert bridge.sent == [] and out.events == []


# ---- config save / hot reload -----------------------------------------

def test_save_writes_only_overrides_and_roundtrips(tmp_path):
    p = tmp_path / "c.toml"
    b = dict(config.DEFAULT_BINDINGS)
    b["X"] = "osk"
    b["R3"] = "none"
    config.save_bindings(b, p)
    text = p.read_text()
    assert 'X = "osk"' in text and 'R3 = "none"' in text and 'A = "select"' not in text
    assert config.load_bindings(p) == b
    config.save_bindings(dict(config.DEFAULT_BINDINGS), p)
    assert "[bindings]\n" in p.read_text() and config.load_bindings(p) == config.DEFAULT_BINDINGS


def test_every_button_and_action_has_a_label():
    assert set(config.BUTTON_LABELS) == set(config.BUTTONS)
    assert set(config.ACTION_LABELS) == set(config.ACTIONS)


def test_daemon_reloads_keybinds_in_place_when_file_changes(tmp_path):
    import asyncio
    p = tmp_path / "c.toml"
    bindings = config.load_bindings(p)

    async def scenario():
        task = asyncio.create_task(config.watch(bindings, p, interval=0.05))
        await asyncio.sleep(0.15)
        cfg = dict(config.DEFAULT_BINDINGS); cfg["A"] = "back"
        config.save_bindings(cfg, p)
        await asyncio.sleep(0.3)
        task.cancel()

    same_dict = bindings
    asyncio.run(scenario())
    assert bindings is same_dict and bindings["A"] == "back"


# ---- extra bindable actions: keys, shortcuts, features ---------------------

def test_new_actions_are_all_unbound_by_default_and_groups_cover_every_action():
    new = set(config.ACTIONS) - {"select", "context", "back", "up", "down", "left", "right", "seek_back",
                                 "seek_fwd", "vol_up", "vol_down", "play_pause", "fullscreen", "search",
                                 "osk", "help", "toggle_mode", "tab_prev", "tab_next", "none"}
    assert new and not new & set(config.DEFAULT_BINDINGS.values())
    grouped = [a for _, actions in config.ACTION_GROUPS for a in actions]
    assert sorted(grouped + ["none"]) == sorted(config.ACTIONS) and len(grouped) == len(set(grouped))
    assert set(config.SHORTCUTS) <= set(config.ACTIONS)
    for name, (_label, combo) in config.SHORTCUTS.items():
        assert config.combo_codes(combo), (name, combo)


def test_key_combos_parse_and_reject_bad_or_dangerous_keys():
    assert config.key_codes("key:ctrl+shift+t") == (e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT, e.KEY_T)
    assert config.key_codes("key:Control+PgDn") == (e.KEY_LEFTCTRL, e.KEY_PAGEDOWN)
    assert config.key_codes("key:f5") == (e.KEY_F5,)
    assert config.key_codes("overview") == (e.KEY_LEFTMETA,)
    for bad in ("key:", "key:ctrl+", "key:nonsense", "key:power", "key:sleep", "key:ctrl+alt+bogus", "refresh_typo"):
        assert config.key_codes(bad) is None, bad
    assert config.action_label("key:ctrl+shift+t") == "Key: Ctrl+Shift+T"
    assert config.action_label("zoom_in") == "Zoom in"
    assert config.combo_from_event(e.KEY_T, ctrl=True, shift=True) == "ctrl+shift+t"
    assert config.combo_from_event(e.KEY_LEFTSHIFT) is None and config.combo_from_event(e.KEY_POWER) is None


def test_config_accepts_custom_keys_and_drops_bad_ones(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[bindings]\nX = "key:ctrl+t"\nY = "key:bogus"\nLB = "refresh"\n')
    b = config.load_bindings(p)
    assert b["X"] == "key:ctrl+t" and b["Y"] == "search" and b["LB"] == "refresh"
    config.save_bindings(b, p)
    assert config.load_bindings(p) == b


def test_bound_key_taps_and_modifier_combos_chord():
    eng, out, bridge = make_browser()
    eng.bindings.update(X="key:ctrl+shift+t", Y="refresh", LB="captions")
    for b in ("X", "Y", "LB"):
        eng.button(b, True); eng.button(b, False)
    assert out.events == [("chord", (e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT, e.KEY_T)),
                          ("chord", (e.KEY_F5,)), ("chord", (e.KEY_C,))]
    assert [m for m in bridge.sent if m["type"] != "ctl"] == []
    assert bridge.sent.count({"type": "ctl"}) == 3   # every key we press is announced to the page


def test_navigation_keys_hold_and_repeat_until_released():
    eng, out, _ = make_browser()
    eng.bindings["X"] = "page_down"
    eng.button("X", True)
    assert out.events == [("key", e.KEY_PAGEDOWN, True)]
    eng.button("X", False)
    assert out.events[-1] == ("key", e.KEY_PAGEDOWN, False)
    eng.bindings["Y"] = "key:shift+tab"       # held modifier is released after the key
    out.events.clear()
    eng.button("Y", True); eng.button("Y", False)
    assert out.events == [("key", e.KEY_LEFTSHIFT, True), ("key", e.KEY_TAB, True),
                          ("key", e.KEY_TAB, False), ("key", e.KEY_LEFTSHIFT, False)]
    out.events.clear()
    eng.button("Y", True); eng.release_all()   # pad drops off mid-press: nothing stays stuck down
    assert out.events[-2:] == [("key", e.KEY_TAB, False), ("key", e.KEY_LEFTSHIFT, False)]


def test_site_hotkeys_are_skipped_while_typing_but_explicit_keys_are_not():
    eng, out, bridge = make_browser()
    bridge.typing = True
    eng.bindings.update(X="captions", Y="space", LB="key:a")
    for b in ("X", "Y", "LB"):
        eng.button(b, True); eng.button(b, False)
    assert out.events == [("chord", (e.KEY_SPACE,)), ("chord", (e.KEY_A,))]


def test_scroll_buttons_and_skip():
    eng, out, bridge = make_browser()
    eng.bindings.update(X="scroll_down", Y="scroll_up", LB="skip")
    eng.button("X", True); eng.button("Y", True); eng.button("LB", True)
    assert out.events == [("scroll", 0, -360), ("scroll", 0, 360)]
    assert {"type": "skip"} in bridge.sent
    eng, out, bridge = make_browser(active=False)   # skip is a page feature: nothing to do in mouse mode
    eng.bindings["LB"] = "skip"
    eng.button("LB", True)
    assert out.events == [] and bridge.sent == []


def test_help_message_carries_labels_for_custom_keys():
    eng, _, bridge = make_browser()
    eng.bindings["X"] = "help"; eng.bindings["Y"] = "key:ctrl+t"
    eng.button("X", True)
    assert bridge.sent[0]["labels"]["key:ctrl+t"] == "Key: Ctrl+T" and bridge.sent[0]["labels"]["help"] == "Show controls"


# ---- pause (settings window in front) ------------------------------------

def test_paused_pad_does_nothing_but_the_live_view_still_sees_it():
    class FakeMonitor:
        buttons, axes_seen = [], []

        def button(self, *args): self.buttons.append(args)
        def axes(self, values): self.axes_seen.append(dict(values))

    eng, out, bridge = make_browser()
    eng.monitor = FakeMonitor()
    eng.set_paused(True)
    eng.button("RT", True)                      # volume up
    eng.button("A", True); eng.button("A", False)
    eng.button("GUIDE", True)                   # must not flip mouse mode either
    eng.abs_event(e.ABS_X, 32767, -32768, 32767)
    eng.abs_event(e.ABS_RY, 32767, -32768, 32767)
    eng.tick(0.5)
    eng.ext_key("left")
    assert out.events == [] and bridge.sent == [] and not eng.force_mouse
    assert [m[3] for m in eng.monitor.buttons] == ["paused"] * 4
    assert eng.monitor.axes_seen[-1]["lx"] == 1.0   # sticks are still reported raw


def test_resuming_works_again_and_pausing_lets_go_of_held_keys():
    eng, out, bridge = make_browser(active=False)    # mouse mode: A is a held mouse button
    eng.button("A", True)
    eng.set_paused(True)
    assert out.events == [("key", e.BTN_LEFT, True), ("key", e.BTN_LEFT, False)]
    out.events.clear()
    eng.button("A", False)                           # the release that arrives while paused is a no-op
    assert out.events == []
    eng.set_paused(False)
    eng.button("RT", True)
    assert ("key", e.KEY_VOLUMEUP, True) in out.events


def test_stick_held_through_a_pause_does_not_fire_a_fresh_nav_step():
    eng, out, bridge = make_browser()
    eng.set_paused(True)
    eng.abs_event(e.ABS_X, 32767, -32768, 32767)
    eng.tick(0.1)
    eng.set_paused(False)
    eng.tick(0.05)
    assert bridge.sent == []
