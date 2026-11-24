import asyncio
import logging

from .config import load_bindings
from .controller import run
from .engine import Engine
from .uinput_out import Output


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    out = Output()
    try:
        asyncio.run(run(Engine(out, load_bindings())))
    except KeyboardInterrupt:
        pass
    finally:
        out.close()


if __name__ == "__main__":
    main()
