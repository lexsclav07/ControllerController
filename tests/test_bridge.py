import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from controllercontroller.bridge import Bridge

import itertools

_ports = itertools.count(18765)


async def _with_bridge(coro, keys):
    global PORT
    PORT = next(_ports)
    b = Bridge(on_key=keys.append, port=PORT)
    task = asyncio.create_task(b.serve())
    await asyncio.sleep(0.1)
    try:
        await coro(b)
    finally:
        task.cancel()


def test_extension_can_connect_report_focus_and_press_keys():
    keys = []

    async def scenario(b):
        async with connect(f"ws://127.0.0.1:{PORT}", origin="chrome-extension://abc") as ws:
            assert json.loads(await ws.recv()) == {"type": "report"}
            assert not b.active
            await ws.send(json.dumps({"type": "active", "value": True}))
            await ws.send(json.dumps({"type": "key", "key": "left"}))
            await ws.send("garbage")
            await asyncio.sleep(0.1)
            assert b.active and keys == ["left"]
            b.send({"type": "nav", "dir": "up"})
            assert json.loads(await ws.recv()) == {"type": "nav", "dir": "up"}
        await asyncio.sleep(0.1)
        assert not b.active

    asyncio.run(_with_bridge(scenario, keys))


@pytest.mark.parametrize("origin", ["https://evil.example", None])
def test_web_pages_are_rejected(origin):
    keys = []

    async def scenario(b):
        async with connect(f"ws://127.0.0.1:{PORT}", origin=origin) as ws:
            with pytest.raises(ConnectionClosed):
                await ws.send(json.dumps({"type": "key", "key": "left"}))
                await asyncio.wait_for(ws.recv(), 1)
        assert keys == [] and not b.active

    asyncio.run(_with_bridge(scenario, keys))
