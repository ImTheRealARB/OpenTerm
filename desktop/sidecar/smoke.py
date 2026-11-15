"""Smoke test for the frozen backend: start it the way the desktop shell does and check that it really works.

    cd backend
    uv run python ../desktop/sidecar/smoke.py <path to openterm-backend[.exe]> [--mode fixtures|synthetic]

It needs no network: the backend answers from recordings (`fixtures`, only if the exe was built with --with-fixtures) or from
the built-in SYN instruments (`synthetic`, works in any build). Checks, in order:
  1. the exe starts on a free port and /api/health answers (time to first answer is printed),
  2. "/" serves the built frontend (OPENTERM_STATIC_DIR) and config.yaml was read (OPENTERM_CONFIG_PATH),
  3. a quote works,
  4. backtest and quant jobs run to the end: they need a worker PROCESS (multiprocessing "spawn" inside a frozen exe) and
     scipy / statsmodels / arch, plus the strategy sandbox,
  5. the AI desks (data files packed into the exe) are found,
  6. when the "parent" (the shell, played here by a throwaway process) disappears, the backend stops by itself.
Needs: frontend/dist built (cd frontend; npm run build). psutil comes from the backend's environment.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import psutil

REPO = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(base: str, path: str, body: dict | None = None, raw: bool = False):
    req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"} if body is not None else {})
    # Generous: the first request that needs a worker process unpacks and imports scipy / pandas in a fresh process (a cold
    # first run on a busy machine took more than 30 s once).
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read()
        return data.decode() if raw else json.loads(data)


def check(ok: bool, what: str) -> None:
    print(("PASS  " if ok else "FAIL  ") + what, flush=True)
    if not ok:
        raise SystemExit(1)


def kill_tree(pid: int) -> None:
    try:
        root = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    for p in [*root.children(recursive=True), root]:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("exe", type=Path)
    ap.add_argument("--mode", choices=["fixtures", "synthetic"], default="fixtures")
    ap.add_argument("--startup-timeout", type=float, default=120.0)
    args = ap.parse_args()
    dist = REPO / "frontend" / "dist"
    check((dist / "index.html").is_file(), f"frontend built at {dist}")

    work = Path(tempfile.mkdtemp(prefix="openterm-smoke-"))
    port = free_port()
    # Stand-in for the desktop shell: the backend must follow this process, not the smoke test itself.
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    env = {**os.environ,
           "OPENTERM_HOST": "127.0.0.1", "OPENTERM_PORT": str(port),
           "OPENTERM_STATIC_DIR": str(dist), "OPENTERM_CONFIG_PATH": str(REPO / "config.yaml"),
           "OPENTERM_DB_PATH": str(work / "openterm.db"), "OPENTERM_DOTENV_PATH": str(work / ".env"),
           "OPENTERM_PARENT_PID": str(parent.pid)}
    env.pop("OPENROUTER_API_KEY", None)
    env["OPENTERM_FIXTURES" if args.mode == "fixtures" else "OPENTERM_SYNTHETIC"] = "1"
    sym = "AAPL" if args.mode == "fixtures" else "SYN0001"
    log = (work / "backend.log").open("wb")
    proc = subprocess.Popen([str(args.exe)], env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        t0 = time.monotonic()
        while True:
            try:
                call(base, "/api/health")
                break
            except OSError:
                if proc.poll() is not None or time.monotonic() - t0 > args.startup_timeout:
                    print((work / "backend.log").read_text(errors="replace")[-2000:])
                    check(False, "backend answered /api/health")
                time.sleep(0.25)
        check(True, f"/api/health answered after {time.monotonic() - t0:.1f} s (exe {args.exe.stat().st_size / 1e6:.0f} MB, mode {args.mode})")

        check('id="root"' in call(base, "/", raw=True), "/ serves the built frontend")
        check(bool(call(base, "/api/sources")), "/api/sources answered (config.yaml read, providers built)")

        q = call(base, f"/api/quote?symbols={sym}")["results"].get(sym, {})  # {requested symbol: envelope | error}
        check("error" not in q and bool(q), f"quote {sym}: {json.dumps(q)[:110]}")

        def run_job(path: str, body: dict) -> dict:
            """Submit a job-based route, wait for the worker to finish, return the finished job."""
            j = call(base, path, body)
            end = time.monotonic() + 120
            while j["state"] not in ("done", "error", "cancelled") and time.monotonic() < end:
                time.sleep(0.2)
                j = call(base, f"/api/jobs/{j['id']}")
            return j

        # A backtest runs in a worker process (multiprocessing "spawn"). Fixture mode has AAPL daily bars for 10Y; SYN symbols make their own.
        bt = {"symbols": [sym], "interval": "1D", "range": "10Y"}
        j = run_job("/api/bt/run", {"rule": "SMA20>SMA50", "options": {}, **bt})
        check(j["state"] == "done", f"BT rule job finished in a worker process: state={j['state']} {str(j.get('error'))[:200]}")
        check(bool(call(base, f"/api/bt/runs/{j['result']['run_id']}")), "BT run stored and readable")

        # A Python strategy goes through the sandbox (backend/openterm/bt/sandbox.py) inside the worker.
        code = (
            "class SignalEngine:\n    def generate(self, data_map):\n"
            "        return {s: (d['close'] > d['close'].rolling(20).mean()).astype(float) for s, d in data_map.items()}\n"
        )
        urllib.request.urlopen(urllib.request.Request(base + "/api/bt/strategies/smoke", data=json.dumps({"code": code}).encode(),
                               method="PUT", headers={"Content-Type": "application/json"}), timeout=30).read()
        j = run_job("/api/bt/run", {"strategy": "smoke", **bt})
        check(j["state"] == "done", f"BT Python-strategy job (sandbox) finished: state={j['state']} {str(j.get('error'))[:200]}")

        # Quant jobs import scipy / statsmodels / arch inside the worker: PyInstaller must have packed them.
        for calc in ("ADF", "GARCH"):
            j = run_job("/api/quant/ql", {"calc": calc, "symbols": [sym], "range": "1y", "h": 5})
            check(j["state"] == "done", f"quant job ql {calc} finished: state={j['state']} {str(j.get('error'))[:200]}")
        j = run_job("/api/quant/ql", {"calc": "DSR", "sr": 0.1, "n": 100, "t": 1000, "skew": 0.0, "kurt": 3.0, "trial_sr_std": 0.05})
        check(j["state"] == "done", f"quant job ql DSR (scipy) finished: state={j['state']} {str(j.get('error'))[:200]}")

        # The key store looks for an OS keyring through package metadata, which a frozen app must carry along.
        check("keys" in call(base, "/api/keys") or bool(call(base, "/api/keys")), "/api/keys answered (key store built)")

        kids = psutil.Process(proc.pid).children(recursive=True)
        print(f"      child processes of the backend while it runs: {len(kids)}")

        # ai/presets/*.yaml are data files read from next to the module; they exist only if PyInstaller packed them.
        desks = call(base, "/api/ai/swarm/presets")
        check(len(desks["presets"]) >= 30 and not desks["errors"], f"{len(desks['presets'])} AI desks loaded from the packed data files")

        # The shell is gone: the backend must exit on its own within a few seconds.
        parent.kill()
        parent.wait()
        t1 = time.monotonic()
        while proc.poll() is None and time.monotonic() - t1 < 20:
            time.sleep(0.2)
        check(proc.poll() is not None, f"backend stopped {time.monotonic() - t1:.1f} s after its parent died")
        left = [p for p in psutil.process_iter(["pid", "name"]) if p.info["name"] == args.exe.name]
        check(not left, "no leftover backend or worker processes")
    finally:
        parent.kill()
        kill_tree(proc.pid)
        log.close()
    print("smoke OK")


if __name__ == "__main__":
    main()
