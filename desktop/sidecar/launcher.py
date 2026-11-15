"""Entry point of the frozen backend (the Tauri "sidecar").

PyInstaller turns this file plus the whole `openterm` package into ONE executable. The desktop shell
(desktop/src-tauri/src/main.rs) starts that executable and passes everything through environment variables, the same
ones the normal backend already reads (backend/openterm/config.py):

    OPENTERM_HOST / OPENTERM_PORT      where to listen (the shell passes a free port)
    OPENTERM_STATIC_DIR                the built frontend (a bundle resource)
    OPENTERM_CONFIG_PATH               config.yaml (a bundle resource)
    OPENTERM_DB_PATH                   the SQLite file, in the per-user app data folder
    OPENTERM_DOTENV_PATH               where API keys are stored when no OS keyring exists
    OPENTERM_PARENT_PID                (launcher only) exit when this process is gone, see watch_parent()

Run by hand to try it:  openterm-backend.exe   (listens on 127.0.0.1:8000 like `python -m openterm`)
"""

import multiprocessing
import os
import sys
import threading
import time


def watch_parent(pid: int, server) -> None:
    """Stop the server shortly after process `pid` (the desktop shell) disappears.

    Why: the shell kills the sidecar on exit, but a PyInstaller one-file executable is TWO processes on Windows (a tiny
    bootloader and the real Python process under it). Killing the bootloader leaves the Python process running and holding
    the port. Polling the parent's pid makes the real process end on its own, and `should_exit` lets uvicorn run the app's
    normal shutdown (job workers are stopped, the database is closed) instead of being cut off.
    """
    import psutil

    while not server.should_exit:
        if not psutil.pid_exists(pid):
            server.should_exit = True
            return
        time.sleep(2)


def main() -> None:
    # MUST be first. The job runner starts worker processes with the "spawn" method (backend/openterm/jobs/runner.py).
    # A spawned child of a frozen program is this same executable started with `--multiprocessing-fork ...`;
    # freeze_support() notices that, runs the worker's code and exits. Without it every child would start a second
    # server (and then a third, and so on). In a normal run (no such argument) it does nothing.
    multiprocessing.freeze_support()

    # Imported only now so that a worker child (which exits inside freeze_support above) never pays for FastAPI & co.
    # The server process must not import pandas / numpy at startup (a backend test guards that); importing
    # openterm.main does not.
    import uvicorn

    from openterm.config import get_settings
    from openterm.main import app

    s = get_settings()
    # Same server settings as backend/openterm/__main__.py. uvloop has no Windows build; asyncio's loop is used there.
    config = uvicorn.Config(
        app,
        host=s.openterm_host,
        port=s.openterm_port,
        loop="asyncio" if sys.platform == "win32" else "uvloop",
        http="httptools",
        log_level="warning",
    )
    server = uvicorn.Server(config)

    parent = os.environ.get("OPENTERM_PARENT_PID")
    if parent:
        threading.Thread(target=watch_parent, args=(int(parent), server), daemon=True, name="parent-watch").start()

    server.run()


if __name__ == "__main__":
    main()
