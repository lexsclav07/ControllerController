import asyncio
import logging

from .bridge import Bridge
from .config import load_bindings
from .controller import run
from .engine import Engine
from .uinput_out import Output


async def _main(out: Output) -> None:
    bridge = Bridge()
    engine = Engine(out, load_bindings(), bridge=bridge)
    bridge.on_key = engine.ext_key
    await asyncio.gather(run(engine), bridge.serve())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    out = Output()
    try:
        asyncio.run(_main(out))
    except KeyboardInterrupt:
        pass
    finally:
        out.close()


if __name__ == "__main__":
    main()
