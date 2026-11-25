"""Notice running games, so the pad can be left to them.

GNOME doesn't tell ordinary apps which window is in front, but Steam starts every game (native or
Proton) under `reaper SteamLaunch AppId=<n> -- ...`, which stays alive exactly as long as the game does.
"""

from __future__ import annotations

import asyncio
import os
from typing import Callable

POLL = 2.0


def steam_app_id(argv: list[bytes]) -> str | None:
    if len(argv) < 3 or os.path.basename(argv[0]) != b"reaper" or argv[1] != b"SteamLaunch":
        return None
    return next((a[6:].decode(errors="replace") for a in argv[2:] if a.startswith(b"AppId=")), None)


def running_game(proc: str = "/proc") -> str | None:
    """The Steam AppId of a running game, or None."""
    for entry in os.listdir(proc):
        if not entry.isdigit():
            continue
        try:
            with open(f"{proc}/{entry}/cmdline", "rb") as fh:
                argv = fh.read().split(b"\0")
        except OSError:   # the process has just exited
            continue
        if app := steam_app_id(argv):
            return app
    return None


async def watch_games(on_change: Callable[[str | None], None]) -> None:
    last = None
    while True:
        app = await asyncio.to_thread(running_game)
        if app != last:
            last = app
            on_change(app)
        await asyncio.sleep(POLL)
