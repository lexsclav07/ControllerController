"""Keybind settings window (GTK4 + libadwaita). Changes save instantly; the daemon reloads them."""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .config import (  # noqa: E402
    ACTION_LABELS, ACTIONS, BUTTON_LABELS, DEFAULT_BINDINGS, config_path, load_bindings, save_bindings,
)

APP_ID = "io.github.lexsclav07.ControllerController"
GROUPS = [
    ("Face buttons", ["A", "B", "X", "Y"]),
    ("Bumpers and triggers", ["LB", "RB", "LT", "RT"]),
    ("Centre buttons", ["START", "SELECT", "GUIDE"]),
    ("Stick clicks", ["L3", "R3"]),
    ("D-pad", ["DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"]),
]
CHOICES = [a for a in ACTIONS if a != "none"] + ["none"]


class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, path: Path | None = None) -> None:
        super().__init__(application=app, title="ControllerController", default_width=560, default_height=760)
        self.path = path or config_path()
        self.bindings = load_bindings(self.path)
        self._rows: dict[str, Adw.ComboRow] = {}
        self._loading = False

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        reset = Gtk.Button(icon_name="edit-undo-symbolic", tooltip_text="Restore default controls")
        reset.connect("clicked", self._confirm_reset)
        header.pack_start(reset)
        view.add_top_bar(header)

        page = Adw.PreferencesPage()
        intro = Adw.PreferencesGroup(
            title="Controls", description="Choose what each button does. Changes apply immediately.")
        page.add(intro)
        for title, buttons in GROUPS:
            group = Adw.PreferencesGroup(title=title)
            for button in buttons:
                row = Adw.ComboRow(title=BUTTON_LABELS[button], use_subtitle=True,
                                   model=Gtk.StringList.new([ACTION_LABELS[a] for a in CHOICES]))
                row.connect("notify::selected", self._on_changed, button)
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
        self._loading = True
        for button, row in self._rows.items():
            row.set_selected(CHOICES.index(self.bindings.get(button, "none")))
        self._loading = False

    def _on_changed(self, row: Adw.ComboRow, _pspec, button: str) -> None:
        if self._loading:
            return
        self.bindings[button] = CHOICES[row.get_selected()]
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
