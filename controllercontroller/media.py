"""Playback control through MPRIS (Firefox/Chrome expose YouTube/Netflix as players)."""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)
_PATH = "/org/mpris/MediaPlayer2"
_IFACE = "org.mpris.MediaPlayer2.Player"


def _busctl(*args: str) -> str:
    out = subprocess.run(
        ["busctl", "--user", *args], capture_output=True, text=True, timeout=2, check=False
    )
    return out.stdout


def find_player() -> str | None:
    """Return the bus name of a playing MPRIS player, else any player, else None."""
    names = [
        line.split()[0]
        for line in _busctl("list", "--no-legend", "--no-pager").splitlines()
        if line.startswith("org.mpris.MediaPlayer2.")
    ]
    for name in names:
        status = _busctl("get-property", name, _PATH, _IFACE, "PlaybackStatus")
        if '"Playing"' in status:
            return name
    return names[0] if names else None


def play_pause() -> bool:
    name = find_player()
    if not name:
        return False
    _busctl("call", name, _PATH, _IFACE, "PlayPause")
    return True


def seek(seconds: int) -> bool:
    name = find_player()
    if not name:
        return False
    _busctl("call", name, _PATH, _IFACE, "Seek", "x", str(seconds * 1_000_000))
    return True
