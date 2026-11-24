"""Phase 24 recorder: an OPTIONAL, OFF-BY-DEFAULT local recorder for crypto trades and order-book snapshots.

What it does: while the user has started a recording for a symbol (`REC BTCUSDT ON`), a background task polls the same two
sources the live panels use (Binance aggTrades = router capability `crypto_trades`, and the depth book = `crypto_depth`),
and appends what it sees to a local file, one JSON object per line ("JSON lines"). FOOT / TAS / DOM can later replay that
file (`FOOT BTCUSDT REC=<id>`) instead of live data.

Why JSON lines: a crash or a power cut loses at most the last line, a reader can stream it, and appending is the cheapest
possible write. The alternative (SQLite) would put big volumes of rows into the same database as the user's settings.

Rules this file keeps:
  * Nothing records at startup. Only `start()` (a user's POST) creates a task.
  * Everything stays on this computer: files live in `<db dir>/recordings/<SYMBOL>/<YYYY-MM-DD>-<HHMMSS>.jsonl`.
  * A disk cap (`recorder.capMb`, default 500) stops the recording loudly; sessions older than `recorder.retentionDays`
    (default 14) are deleted whenever a recording starts.
  * No fake data: a trade is stored exactly as the provider gave it; a poll that fails is skipped (and counted), never filled in.

File format (every line has `k`):
  {"k":"meta","v":1,"symbol":"BTCUSDT","started":<epoch s>,"venue":"BINANCE SPOT"}
  {"k":"t","id":<aggregate id>,"t":<ms>,"p":<price>,"q":<coins>,"buy":true|false}      one per NEW trade (de-duplicated by id)
  {"k":"d","t":<epoch ms of the poll>, ...depth payload as `/api/world/cdep` returns it...}   one per poll
  {"k":"end","t":<epoch s>,"reason":"STOPPED"|"DISK CAP <n> MB"|...}                    written when the recording ends
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson

from . import errkinds as K
from .errors import DataError
from .router import AllFailed
from .world import cryptodepth as cd
from .world import orderflow as of

log = logging.getLogger("openterm.recorder")

DEFAULT_CAP_MB = 500
DEFAULT_RETENTION_DAYS = 14
DEFAULT_POLL_S = 5.0
SESSION_RE = re.compile(r"^([A-Z0-9]{2,20})/(\d{4}-\d{2}-\d{2}-\d{6})$")  # a session id: SYMBOL/YYYY-MM-DD-HHMMSS
MAX_SESSION_LINES = 50_000  # GET /session returns at most this many lines (a tail of the file): the response stays bounded
MAX_SESSION_BYTES = 12_000_000


class RecorderError(Exception):
    """A user-level problem (bad symbol, already recording, no db folder). `kind` maps to an HTTP status in the routes."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class _Active:
    """One running recording: its task, file and counters."""

    def __init__(self, symbol: str, path: Path):
        self.symbol = symbol
        self.path = path
        self.started = time.time()
        self.seen: set[int] = set()  # aggregate trade ids already written (the de-duplication)
        self.last_id = 0  # newest id written: older ones can never be new again, so `seen` only needs recent ids
        self.trades = 0
        self.snapshots = 0
        self.errors = 0
        self.last_error: str | None = None
        self.task: asyncio.Task | None = None

    @property
    def session_id(self) -> str:
        return f"{self.symbol}/{self.path.stem}"


class Recorder:
    def __init__(self, root: Path | None, svc: Any, settings_get: Any, poll_s: float = DEFAULT_POLL_S):
        """`root` = `<db dir>/recordings` (None for an in-memory database: recording is then refused).
        `settings_get` = async callable returning the stored settings dict (so the cap and retention are read fresh each time).
        `poll_s` is a plain attribute on purpose: tests set it to a few milliseconds."""
        self.root = root
        self.svc = svc
        self.settings_get = settings_get
        self.poll_s = poll_s
        self.active: dict[str, _Active] = {}
        self.stopped_notes: dict[str, str] = {}  # symbol -> why its last recording ended on its own (disk cap, errors)

    # ------------------------------------------------------------------ settings
    async def _limits(self) -> tuple[int, int]:
        """(cap in bytes, retention in days) from the synced `recorder` setting; defaults when the user never touched it."""
        s = ((await self.settings_get()) or {}).get("recorder") or {}
        return int(s.get("capMb", DEFAULT_CAP_MB)) * 1_000_000, int(s.get("retentionDays", DEFAULT_RETENTION_DAYS))

    # ------------------------------------------------------------------ disk
    def total_bytes(self) -> int:
        if self.root is None or not self.root.exists():
            return 0
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())

    def _files(self) -> list[Path]:
        if self.root is None or not self.root.exists():
            return []
        return sorted(self.root.glob("*/*.jsonl"))

    def delete_old(self, retention_days: int, now: float | None = None) -> list[str]:
        """Deletes sessions whose file was last written more than `retention_days` ago. Returns the ids removed."""
        cutoff = (now or time.time()) - retention_days * 86400
        gone = []
        running = {a.path for a in self.active.values()}
        for f in self._files():
            if f not in running and f.stat().st_mtime < cutoff:
                gone.append(f"{f.parent.name}/{f.stem}")
                f.unlink()
        return gone

    # ------------------------------------------------------------------ start / stop
    async def start(self, symbol: str) -> dict[str, Any]:
        if self.root is None:
            raise RecorderError("bad_request", "RECORDER NEEDS A DATABASE FILE (NOT :memory:)")
        try:
            base, quote = cd.parse_pair(symbol)
        except ValueError as e:
            raise RecorderError("bad_request", "RECORDER: CRYPTO ONLY (BINANCE SPOT PAIRS LIKE BTCUSDT)") from e
        sym = f"{base}{'USDT' if quote == 'USD' else quote}"
        if sym in self.active:
            raise RecorderError("conflict", f"ALREADY RECORDING {sym}")
        cap, retention = await self._limits()
        self.delete_old(retention)
        if self.total_bytes() >= cap:
            raise RecorderError("conflict", f"RECORDER STOPPED: DISK CAP {cap // 1_000_000} MB (DELETE OLD SESSIONS IN REC)")
        # One request to the sources first: a symbol Binance does not list fails here, loudly, not after a silent empty file.
        first = await self._poll_once(base, quote)
        (self.root / sym).mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
        rec = _Active(sym, self.root / sym / f"{stamp}.jsonl")
        self._write(rec, [{"k": "meta", "v": 1, "symbol": sym, "started": rec.started, "venue": first["venue"]}])
        self.stopped_notes.pop(sym, None)
        self.active[sym] = rec
        self._ingest(rec, first)  # the first poll is not wasted
        rec.task = asyncio.create_task(self._run(rec, base, quote), name=f"recorder:{sym}")
        return self._active_row(rec)

    async def stop(self, symbol: str) -> dict[str, Any]:
        try:
            base, quote = cd.parse_pair(symbol)
        except ValueError as e:
            raise RecorderError("bad_request", "RECORDER: CRYPTO ONLY (BINANCE SPOT PAIRS LIKE BTCUSDT)") from e
        sym = f"{base}{'USDT' if quote == 'USD' else quote}"
        rec = self.active.get(sym)
        if rec is None:
            raise RecorderError("not_found", f"NOT RECORDING {sym}")
        await self._finish(rec, "STOPPED")
        return {"id": rec.session_id, "trades": rec.trades, "snapshots": rec.snapshots}

    async def aclose(self) -> None:
        """Server shutdown: end every recording cleanly (its `end` line is written)."""
        for rec in list(self.active.values()):
            await self._finish(rec, "SERVER STOPPED")

    async def _finish(self, rec: _Active, reason: str) -> None:
        self.active.pop(rec.symbol, None)
        task, rec.task = rec.task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._write(rec, [{"k": "end", "t": time.time(), "reason": reason}])
        if reason not in ("STOPPED", "SERVER STOPPED"):
            self.stopped_notes[rec.symbol] = reason

    # ------------------------------------------------------------------ the poll loop
    async def _run(self, rec: _Active, base: str, quote: str) -> None:
        try:
            while True:
                await asyncio.sleep(self.poll_s)
                try:
                    self._ingest(rec, await self._poll_once(base, quote))
                except DataError as e:  # one failed poll is skipped and counted, never invented
                    rec.errors += 1
                    rec.last_error = str(e)[:200]
                    log.warning("recorder %s: poll failed: %s", rec.symbol, rec.last_error)
                cap, _ = await self._limits()
                if self.total_bytes() >= cap:
                    await self._finish(rec, f"DISK CAP {cap // 1_000_000} MB")
                    log.warning("recorder %s: RECORDER STOPPED: DISK CAP %d MB", rec.symbol, cap // 1_000_000)
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # a bug must not leave a recording that looks alive but writes nothing
            log.exception("recorder %s crashed", rec.symbol)
            await self._finish(rec, "CRASHED (SEE LOG)")

    async def _poll_once(self, base: str, quote: str) -> dict[str, Any]:
        """One look at the two sources, WITHOUT the panels' short cache (a cached answer would repeat the same trades)."""
        router = self.svc.router
        try:
            trades_out, _ = await router.call("crypto_trades", lambda p: p.crypto_trades(base, quote, None, 1), f"{base}{quote}")
            depth_out, _ = await router.call("crypto_depth", lambda p: p.crypto_depth(base, quote), f"{base}{quote}")
        except AllFailed as e:  # same translation `DataService.swr` does for the live panels
            if e.kind in (K.NOT_FOUND, K.UNSUPPORTED):  # a pair Binance does not list
                raise DataError(K.BAD_REQUEST, "RECORDER: CRYPTO ONLY (BINANCE SPOT PAIRS LIKE BTCUSDT)") from e
            detail = "; ".join(f"{name}: {err.kind} ({err})" for name, err in e.errors) or None
            raise DataError(e.kind, str(e), detail, e.key) from e
        return {"trades": trades_out["trades"], "venue": trades_out["venue"], "depth": {**depth_out, "base": base}}

    def _ingest(self, rec: _Active, got: dict[str, Any]) -> None:
        lines: list[dict[str, Any]] = []
        for tr in got["trades"]:  # oldest first
            if tr.id in rec.seen or tr.id <= rec.last_id:
                continue
            rec.seen.add(tr.id)
            lines.append({"k": "t", "id": tr.id, "t": tr.t, "p": tr.p, "q": tr.q, "buy": tr.buy})
        if lines:
            rec.last_id = max(rec.last_id, lines[-1]["id"])
            rec.trades += len(lines)
            if len(rec.seen) > 20_000:  # ids below `last_id` are rejected by the `<=` test above, so old ones can go
                rec.seen = {i for i in rec.seen if i > rec.last_id - 5_000}
        lines.append({"k": "d", "t": int(time.time() * 1000), **got["depth"]})
        rec.snapshots += 1
        self._write(rec, lines)

    @staticmethod
    def _write(rec: _Active, lines: list[dict[str, Any]]) -> None:
        with rec.path.open("ab") as f:
            f.write(b"".join(orjson.dumps(x) + b"\n" for x in lines))

    # ------------------------------------------------------------------ reading
    def _active_row(self, rec: _Active) -> dict[str, Any]:
        return {"symbol": rec.symbol, "id": rec.session_id, "started": rec.started, "trades": rec.trades, "snapshots": rec.snapshots,
                "errors": rec.errors, "last_error": rec.last_error, "bytes": rec.path.stat().st_size if rec.path.exists() else 0}

    async def listing(self) -> dict[str, Any]:
        cap, retention = await self._limits()
        running = {a.session_id for a in self.active.values()}
        sessions = []
        for f in self._files():
            st = f.stat()
            sid = f"{f.parent.name}/{f.stem}"
            sessions.append({"id": sid, "symbol": f.parent.name, "started": _stamp_to_epoch(f.stem), "bytes": st.st_size,
                             "modified": st.st_mtime, "recording": sid in running})
        sessions.sort(key=lambda s: s["started"], reverse=True)
        return {"active": [self._active_row(a) for a in self.active.values()], "sessions": sessions, "notes": dict(self.stopped_notes),
                "total_bytes": self.total_bytes(), "cap_mb": cap // 1_000_000, "retention_days": retention,
                "poll_s": self.poll_s, "label": "OFF BY DEFAULT · KEPT ON THIS COMPUTER ONLY"}

    def _path(self, sid: str) -> Path:
        m = SESSION_RE.match(sid)
        if not m or self.root is None:
            raise RecorderError("bad_request", "BAD SESSION ID (EXPECTED BTCUSDT/2026-11-24-101500)")
        p = self.root / m.group(1) / f"{m.group(2)}.jsonl"
        if not p.exists():
            raise RecorderError("not_found", f"NO RECORDED SESSION {sid}")
        return p

    def read_session(self, sid: str) -> dict[str, Any]:
        """The session as {meta, trades (oldest first), depth (snapshots oldest first), end, truncated}. A huge file returns its
        NEWEST part and says `truncated`: the caller shows that on screen."""
        p = self._path(sid)
        size = p.stat().st_size
        truncated = size > MAX_SESSION_BYTES
        with p.open("rb") as f:
            if truncated:
                f.seek(size - MAX_SESSION_BYTES)
                f.readline()  # drop the partial first line
            raw = f.read()
        meta: dict[str, Any] | None = None
        trades: list[dict[str, Any]] = []
        depth: list[dict[str, Any]] = []
        end: dict[str, Any] | None = None
        if truncated:  # the meta line is at the file head: read it separately
            with p.open("rb") as f:
                head = f.readline()
            meta = _loads(head)
        for line in raw.splitlines():
            row = _loads(line)
            if row is None:
                continue  # a half-written last line (a crash or a recording still running)
            k = row.pop("k", None)
            if k == "meta":
                meta = row
            elif k == "t":
                trades.append(row)
            elif k == "d":
                depth.append(row)
            elif k == "end":
                end = row
        if len(trades) > MAX_SESSION_LINES:
            trades, truncated = trades[-MAX_SESSION_LINES:], True
        if len(depth) > MAX_SESSION_LINES // 10:
            depth, truncated = depth[-(MAX_SESSION_LINES // 10):], True
        return {"id": sid, "meta": meta, "trades": trades, "depth": depth, "end": end, "truncated": truncated, "bytes": size}

    def delete_session(self, sid: str) -> None:
        p = self._path(sid)
        if any(a.path == p for a in self.active.values()):
            raise RecorderError("conflict", "THIS SESSION IS RECORDING: STOP IT FIRST (REC <SYMBOL> OFF)")
        p.unlink()
        if not any(p.parent.iterdir()):
            shutil.rmtree(p.parent, ignore_errors=True)

    # ------------------------------------------------------------------ replay: the same payload shapes the live panels get
    # FOOT / TAS / DOM draw `{data, source, as_of, ...}` envelopes. A recorded session is turned into the SAME shapes here (with
    # the live code `orderflow.footprint` / `orderflow.recent`), so the panels need no second drawing path. `data.recorded` tells
    # the panel it is a replay; it carries the facts the label `RECORDED BY OPENTERM <date>` needs.
    def _replay_head(self, s: dict[str, Any]) -> tuple[list[of.Trade], dict[str, Any]]:
        trades = [of.Trade(t["id"], t["t"], t["p"], t["q"], bool(t["buy"])) for t in s["trades"]]
        if not trades:
            raise RecorderError("not_found", f"SESSION {s['id']} HAS NO TRADES YET")
        sym = s["meta"]["symbol"] if s.get("meta") else s["id"].split("/")[0]
        base, quote = cd.parse_pair(sym)
        started = (s["meta"] or {}).get("started") or _stamp_to_epoch(s["id"].split("/")[1])
        head = {"symbol": sym, "pair": f"{base}/{quote}", "base": base, "quote": quote, "quote_is_usd": quote in cd.USD_QUOTES,
                "venue": (s["meta"] or {}).get("venue", "BINANCE SPOT"), "basis": of.LABEL_EXACT, "n": len(trades),
                "span_s": (trades[-1].t - trades[0].t) / 1000.0, "newest_t": trades[-1].t,
                "recorded": {"id": s["id"], "started": started, "ended": (s["end"] or {}).get("t"), "reason": (s["end"] or {}).get("reason"),
                             "truncated": s["truncated"], "snapshots": len(s["depth"])}}
        return trades, head

    @staticmethod
    def _replay_envelope(data: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        return {"data": data, "source": "recorder", "as_of": now, "age_s": 0.0, "stale": False, "fallback_from": []}

    def replay_tas(self, sid: str, limit: int) -> dict[str, Any]:
        trades, head = self._replay_head(self.read_session(sid))
        return self._replay_envelope({**head, "rows": of.recent(trades, limit)})

    def replay_footprint(self, sid: str, interval: str, bars: int, step: float | None) -> dict[str, Any]:
        iv = of.INTERVAL_MS.get(interval)
        if iv is None:
            raise RecorderError("bad_request", f"INTERVAL: {', '.join(of.INTERVAL_MS)}")
        trades, head = self._replay_head(self.read_session(sid))
        try:
            # truncated=True marks the OLDEST bar partial: a recording starts mid-bar, so that bar lacks its first trades.
            fp = of.footprint(trades, iv, bars, step, True)
        except ValueError as e:
            raise RecorderError("bad_request", str(e)) from e
        return self._replay_envelope({**head, "interval": interval, "bars_asked": bars, "truncated": False, **fp})

    def replay_depth(self, sid: str, index: int) -> dict[str, Any]:
        """Snapshot number `index` (0 = oldest; negative counts from the newest, so -1 = the last one) in the CDEP / DOM payload shape."""
        s = self.read_session(sid)
        snaps = s["depth"]
        if not snaps:
            raise RecorderError("not_found", f"SESSION {sid} HAS NO ORDER-BOOK SNAPSHOTS YET")
        if not -len(snaps) <= index < len(snaps):
            raise RecorderError("bad_request", f"SNAPSHOT {index} OUT OF RANGE (0 TO {len(snaps) - 1})")
        snap = dict(snaps[index])
        recorded_t = snap.pop("t")
        started = (s["meta"] or {}).get("started") or _stamp_to_epoch(sid.split("/")[1])
        return self._replay_envelope({**snap, "recorded": {"id": sid, "started": started, "at": recorded_t, "index": index % len(snaps),
                                                           "count": len(snaps), "ended": (s["end"] or {}).get("t"), "truncated": s["truncated"]}})


def _loads(line: bytes) -> dict[str, Any] | None:
    try:
        v = orjson.loads(line)
    except orjson.JSONDecodeError:
        return None
    return v if isinstance(v, dict) else None


def _stamp_to_epoch(stem: str) -> float:
    try:
        return datetime.strptime(stem, "%Y-%m-%d-%H%M%S").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return 0.0
