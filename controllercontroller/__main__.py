import asyncio
import logging
import sys

from .bridge import Bridge
from .config import load_bindings, watch
from .controller import run
from .engine import Engine
from .uinput_out import Output


async def _main(out: Output) -> None:
    bridge = Bridge()
    bindings = load_bindings()
    engine = Engine(out, bindings, bridge=bridge)
    bridge.on_key = engine.ext_key
    await asyncio.gather(run(engine), bridge.serve(), watch(bindings))


def main() -> None:
    if sys.argv[1:2] == ["settings"]:
        from .settings import main as settings_main   # needs GTK; the daemon itself does not
        sys.exit(settings_main())
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
