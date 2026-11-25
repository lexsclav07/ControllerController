"""Keybind settings window (GTK4 + libadwaita). Changes save instantly; the daemon reloads them."""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from .config import (  # noqa: E402
    ACTION_GROUPS, BUTTON_LABELS, DEFAULT_BINDINGS, SHORTCUTS, action_label, combo_from_event, combo_label,
    config_path, load_bindings, save_bindings,
)

APP_ID = "io.github.lexsclav07.ControllerController"
GROUPS = [
    ("Face buttons", ["A", "B", "X", "Y"]),
    ("Bumpers and triggers", ["LB", "RB", "LT", "RT"]),
    ("Centre buttons", ["START", "SELECT", "GUIDE"]),
    ("Stick clicks", ["L3", "R3"]),
    ("D-pad", ["DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"]),
]


class ActionPicker(Adw.PreferencesDialog):
    """Searchable list of everything a button can do, plus a recorder for any key combination."""

    def __init__(self, parent: Gtk.Widget, button: str, current: str, on_pick) -> None:
        super().__init__(title=BUTTON_LABELS[button], search_enabled=True, content_width=480, content_height=720)
        self._parent, self._on_pick = parent, on_pick
        page = Adw.PreferencesPage()
        for title, actions in ACTION_GROUPS:
            group = Adw.PreferencesGroup(title=title)
            for action in actions:
                group.add(self._row(action, current))
            page.add(group)
        other = Adw.PreferencesGroup(title="Other")
        record = Adw.ActionRow(title="Record a key\u2026", activatable=True,
                               subtitle="Press any key or combination, like Ctrl+Shift+T")
        record.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        record.connect("activated", lambda _row: self._record())
        if current.startswith("key:"):   # a recorded key is not in the list; show it as the current choice
            other.add(self._row(current, current))
        other.add(record)
        other.add(self._row("none", current))
        page.add(other)
        self.add(page)

    def _row(self, action: str, current: str) -> Adw.ActionRow:
        hint = combo_label(SHORTCUTS[action][1]) if action in SHORTCUTS else ""
        row = Adw.ActionRow(title=action_label(action), subtitle=hint, activatable=True)
        if action == current:
            row.add_suffix(Gtk.Image.new_from_icon_name("object-select-symbolic"))
        row.connect("activated", lambda _row: self._pick(action))
        return row

    def _pick(self, action: str) -> None:
        self.force_close()
        self._on_pick(action)

    def _record(self) -> None:
        dialog = Adw.AlertDialog(heading="Press a key", body="Press the key or combination you want, "
                                                          "for example Ctrl+Shift+T.")
        dialog.add_response("cancel", "Cancel")
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key, dialog)
        dialog.add_controller(keys)
        dialog.present(self._parent)

    def _on_key(self, _ctl, _keyval: int, keycode: int, state: Gdk.ModifierType, dialog: Adw.AlertDialog) -> bool:
        # GTK hands us the XKB keycode, which is the Linux evdev code + 8 (independent of keyboard layout).
        combo = combo_from_event(
            keycode - 8,
            ctrl=bool(state & Gdk.ModifierType.CONTROL_MASK), shift=bool(state & Gdk.ModifierType.SHIFT_MASK),
            alt=bool(state & Gdk.ModifierType.ALT_MASK), sup=bool(state & Gdk.ModifierType.SUPER_MASK))
        if combo is None:   # a bare modifier: keep waiting for the real key
            return True
        dialog.force_close()
        self._pick("key:" + combo)
        return True


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, path: Path | None = None) -> None:
        super().__init__(application=app, title="ControllerController", default_width=560, default_height=760)
        self.path = path or config_path()
        self.bindings = load_bindings(self.path)
        self._rows: dict[str, Adw.ActionRow] = {}

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        reset = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Restore default controls")
        reset.connect("clicked", self._confirm_reset)
        header.pack_start(reset)
        view.add_top_bar(header)

        page = Adw.PreferencesPage()
        intro = Adw.PreferencesGroup(
            title="Controls", description="Pick a button to choose what it does. Changes apply immediately.")
        page.add(intro)
        for title, buttons in GROUPS:
            group = Adw.PreferencesGroup(title=title)
            for button in buttons:
                row = Adw.ActionRow(title=BUTTON_LABELS[button], activatable=True)
                row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
                row.connect("activated", self._open_picker, button)
                self._rows[button] = row
                group.add(row)
            page.add(group)
        fixed = Adw.PreferencesGroup(title="Sticks (fixed)")
        for name, what in (("Left stick", "Moves the focus box, or the mouse pointer in mouse mode"),
                           ("Right stick", "Scrolls")):
            fixed.add(Adw.ActionRow(title=name, subtitle=what))
        page.add(fixed)
        self._refresh()

        view.set_content(page)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

    def _refresh(self) -> None:
        for button, row in self._rows.items():
            row.set_subtitle(action_label(self.bindings.get(button, "none")))

    def _open_picker(self, _row: Adw.ActionRow, button: str) -> None:
        current = self.bindings.get(button, "none")
        ActionPicker(self, button, current, lambda action: self._set(button, action)).present(self)

    def _set(self, button: str, action: str) -> None:
        self.bindings[button] = action
        self._rows[button].set_subtitle(action_label(action))
        try:
            save_bindings(self.bindings, self.path)
            self.toasts.add_toast(Adw.Toast(title="Saved", timeout=1))
        except OSError as exc:
            self.toasts.add_toast(Adw.Toast(title=f"Could not save: {exc}"))

    def _confirm_reset(self, _button: Gtk.Button) -> None:
        dialog = Adw.AlertDialog(heading="Restore default controls?",
                                 body="All of your changes will be lost.")
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reset", "Restore")
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.connect("response", self._on_reset_response)
        dialog.present(self)

    def _on_reset_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        if response != "reset":
            return
        self.bindings = dict(DEFAULT_BINDINGS)
        save_bindings(self.bindings, self.path)
        self._refresh()
        self.toasts.add_toast(Adw.Toast(title="Defaults restored", timeout=2))


class App(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)

    def do_activate(self) -> None:
        (self.props.active_window or SettingsWindow(self)).present()


def main() -> int:
    return App().run(sys.argv[:1])
