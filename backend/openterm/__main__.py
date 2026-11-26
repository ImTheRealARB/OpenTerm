import sys

import uvicorn

from . import remote
from .config import get_settings

if __name__ == "__main__":
    s = get_settings()
    try:
        remote.check_bind(s.openterm_host)
    except RuntimeError as e:
        raise SystemExit(f"REFUSED TO START: {e}") from None
    loop = "asyncio" if sys.platform == "win32" else "uvloop"
    uvicorn.run(
        "openterm.main:app",
        host=s.openterm_host,
        port=s.openterm_port,
        loop=loop,
        http="httptools",
        reload="--reload" in sys.argv,
        log_level="warning",
    )
