"""NB (Phase 31): start and stop a local JupyterLab with openterm-sdk, from a source checkout.

Why a local JupyterLab and not an in-browser Python: Pyodide would add about 10 MB to the app and run pandas several times slower; a
real Python on this computer reads the running OpenTerm through openterm-sdk at full speed (owner decision: local JupyterLab).

How: `uv run --extra notebook jupyter lab` in backend/ (the `notebook` extra pins jupyterlab and the SDK from ../sdk/python), bound to
127.0.0.1 with a random token, no browser. The notebooks live in `<data dir>/notebooks` (next to the database), so your own notebooks
never dirty the repository; the examples in repo `notebooks/` are copied there once (an existing file is never overwritten).
The token is a secret: it is in the URL the panel opens and nowhere else (never logged, never in /api/log).
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
EXAMPLES = BACKEND.parent / "notebooks"
PORTS = range(8888, 8899)


class NotebookError(RuntimeError):
    """Shown to the user as is."""


def _free_port() -> int:
    for p in PORTS:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    raise NotebookError(f"NO FREE PORT IN {PORTS.start}-{PORTS.stop - 1} FOR JUPYTERLAB")


def copy_examples(dest: Path) -> list[str]:
    """Copy repo notebooks/*.ipynb into `dest` when missing. Returns the names copied."""
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for f in sorted(EXAMPLES.glob("*.ipynb")):
        if not (dest / f.name).exists():
            shutil.copyfile(f, dest / f.name)
            copied.append(f.name)
    return copied


class NotebookServer:
    def __init__(self, db_path: str, api_port: int):
        self.dir = Path(db_path).resolve().parent / "notebooks"
        self.api_port = api_port
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.token: str | None = None
        self.started_at: float | None = None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def status(self) -> dict[str, Any]:
        """Running or not, and (when up) the URL with its token: every NB route is loopback-only, so only this computer sees it."""
        up = self.running()
        out: dict[str, Any] = {"running": up, "dir": str(self.dir), "port": self.port if up else None,
                               "since": self.started_at if up else None, "examples": sorted(f.name for f in EXAMPLES.glob("*.ipynb"))}
        if self.proc is not None and not up:
            out["exit_code"] = self.proc.returncode
        if up:
            out["url"] = f"http://127.0.0.1:{self.port}/lab?token={self.token}"
        return out

    def start(self) -> dict[str, Any]:
        if self.running():
            return self.status()
        if getattr(sys, "frozen", False):
            raise NotebookError("NB NEEDS A SOURCE CHECKOUT WITH uv: THE DESKTOP APP CANNOT START JUPYTERLAB (pip install ./sdk/python jupyterlab INSTEAD)")
        uv = shutil.which("uv")
        if uv is None:
            raise NotebookError("uv NOT FOUND ON PATH: INSTALL uv (https://docs.astral.sh/uv/) OR RUN JUPYTER YOURSELF WITH pip install ./sdk/python")
        copy_examples(self.dir)
        self.port, self.token = _free_port(), secrets.token_hex(16)
        env = {**os.environ, "OPENTERM_URL": f"http://127.0.0.1:{self.api_port}"}
        cmd = [uv, "run", "--project", str(BACKEND), "--extra", "notebook", "jupyter", "lab", "--no-browser", "--ip", "127.0.0.1",
               f"--port={self.port}", f"--ServerApp.root_dir={self.dir}", f"--IdentityProvider.token={self.token}"]
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.proc = subprocess.Popen(cmd, cwd=str(self.dir), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=flags)
        self.started_at = time.time()
        return self.status()

    def stop(self) -> dict[str, Any]:
        if self.running():
            assert self.proc is not None
            if os.name == "nt":  # uv starts jupyter as a child: kill the whole tree
                subprocess.run(["taskkill", "/pid", str(self.proc.pid), "/T", "/F"], capture_output=True, check=False)
            else:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return self.status()
