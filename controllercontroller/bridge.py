"""Local WebSocket link to the browser extension.

daemon -> extension: {"type": "nav", "dir": ...} | select | back | osk | search | {"type": "mode", "mouse": bool}
                     (delivered only to the focused browser), plus "report" and "ping" (to everyone)
extension -> daemon: {"type": "active", "value": bool}   browser window focused
                     {"type": "typing", "value": bool}   a text field has focus
                     {"type": "key", "key": "up|down|left|right|space|enter|slash"}
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Callable

from websockets.asyncio.server import ServerConnection, serve

log = logging.getLogger(__name__)
HOST, PORT = "127.0.0.1", 8765
ALLOWED_ORIGIN_PREFIXES = ("moz-extension://", "chrome-extension://")
# Messages that act on the page; they must only reach the browser the user is looking at.
ACTION_TYPES = {"nav", "select", "back", "osk", "search", "mode"}


class Bridge:
    def __init__(self, on_key: Callable[[str], None] | None = None,
                 host: str = HOST, port: int = PORT) -> None:
        self.host, self.port = host, port
        self.on_key = on_key or (lambda _k: None)
        self._clients: dict[ServerConnection, bool] = {}   # connection -> browser focused
        self._typing: dict[ServerConnection, bool] = {}    # connection -> text field focused

    @property
    def active(self) -> bool:
        """True when a browser window with the extension is focused."""
        return any(self._clients.values())

    @property
    def typing(self) -> bool:
        """True when the focused browser has a text field focused (so stray keys would be typed)."""
        return any(self._typing.get(ws) for ws, focused in self._clients.items() if focused)

    def send(self, msg: dict) -> None:
        data = json.dumps(msg)
        action = msg.get("type") in ACTION_TYPES
        for ws, focused in list(self._clients.items()):
            if focused or not action:
                asyncio.ensure_future(self._safe_send(ws, data))

    @staticmethod
    async def _safe_send(ws: ServerConnection, data: str) -> None:
        try:
            await ws.send(data)
        except Exception:  # connection already closing
            pass

    async def _handler(self, ws: ServerConnection) -> None:
        # Web pages may open ws://127.0.0.1 too; only browser extensions may drive us.
        origin = ws.request.headers.get("Origin", "") if ws.request else ""
        if not origin.startswith(ALLOWED_ORIGIN_PREFIXES):
            await ws.close(1008, "forbidden")
            return
        self._clients[ws] = False
        log.info("extension connected")
        try:
            await self._safe_send(ws, json.dumps({"type": "report"}))
            async for raw in ws:
                self._handle(ws, raw)
        finally:
            self._clients.pop(ws, None)
            self._typing.pop(ws, None)
            log.info("extension disconnected")

    def _handle(self, ws: ServerConnection, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
            kind = msg.get("type")
        except (ValueError, AttributeError):
            return
        if kind == "active":
            self._clients[ws] = bool(msg.get("value"))
        elif kind == "typing":
            self._typing[ws] = bool(msg.get("value"))
        elif kind == "key" and isinstance(msg.get("key"), str):
            self.on_key(msg["key"])

    async def serve(self) -> None:
        async with serve(self._handler, self.host, self.port):
            while True:
                await asyncio.sleep(20)
                self.send({"type": "ping"})   # keeps Chrome's service worker awake (Firefox relies on the alarm + reconnect)
