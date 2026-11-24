"""Playback control through MPRIS (Firefox/Chrome expose YouTube/Netflix as players)."""

from __future__ import annotations

import logging
import subprocess

log = logging.getLogger(__name__)
_PATH = "/org/mpris/MediaPlayer2"
_IFACE = "org.mpris.MediaPlayer2.Player"


def _busctl(*args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["busctl", "--user", *args], capture_output=True, text=True, timeout=2, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("busctl failed: %s", exc)
        return None


def _ok(proc: subprocess.CompletedProcess | None) -> bool:
    return proc is not None and proc.returncode == 0


def find_player() -> str | None:
    """Return the bus name of a playing MPRIS player, else any player, else None."""
    listing = _busctl("list", "--no-legend", "--no-pager")
    if not _ok(listing):
        return None
    names = [
        line.split()[0]
        for line in listing.stdout.splitlines()
        if line.startswith("org.mpris.MediaPlayer2.")
    ]
    for name in names:
        status = _busctl("get-property", name, _PATH, _IFACE, "PlaybackStatus")
        if _ok(status) and '"Playing"' in status.stdout:
            return name
    return names[0] if names else None


def play_pause() -> bool:
    """True if a player handled it; False tells the caller to fall back to a key press."""
    name = find_player()
    return bool(name) and _ok(_busctl("call", name, _PATH, _IFACE, "PlayPause"))


def seek(seconds: int) -> bool:
    name = find_player()
    # "--" so busctl does not parse a negative offset as an option.
    return bool(name) and _ok(
        _busctl("call", name, _PATH, _IFACE, "Seek", "x", "--", str(seconds * 1_000_000))
    )
