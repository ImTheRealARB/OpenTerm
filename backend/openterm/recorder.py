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

Indian symbols (`REC RELIANCE.NS ON`, needs a Kite login) are recorded from the Kite ticker instead of polled: the symbol is held
in full mode and every print and every CHANGE of the best-five book is appended (buffered, flushed every `poll_s`):
  {"k":"meta","v":1,"symbol":"RELIANCE.NS","started":..,"venue":"KITE","kite":true}
  {"k":"kt","t":<ms>,"p":<last price>,"q":<volume gained since the previous packet>}      q = 0 is the reference print (first packet)
  {"k":"kd","t":<ms>,"buy":[[qty,price,orders]*5],"sell":[[qty,price,orders]*5]}            only when the book changed
The side of a Kite print is never stored (the feed has none): replay guesses it with the tick rule and says ESTIMATED.
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
from .kite.symbols import to_kite
from .router import AllFailed
from .world import cryptodepth as cd
from .world import kiteflow
from .world import orderflow as of

log = logging.getLogger("openterm.recorder")

DEFAULT_CAP_MB = 500
DEFAULT_RETENTION_DAYS = 14
DEFAULT_POLL_S = 5.0
SESSION_NAME_MAX = 30
SESSION_RE = re.compile(rf"^([A-Z0-9]{{2,{SESSION_NAME_MAX}}})/(\d{{4}}-\d{{2}}-\d{{2}}-\d{{6}})$")  # a session id: SYMBOL/YYYY-MM-DD-HHMMSS
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
        self.kite: str | None = None  # the Yahoo-style symbol when this is a Kite recording
        self.buffer: list[dict[str, Any]] = []  # Kite lines waiting for the next flush
        self.last_book: Any = None  # the last depth written (a book is written only when it changed)

    @property
    def session_id(self) -> str:
        return f"{self.symbol}/{self.path.stem}"


class Recorder:
    def __init__(self, root: Path | None, svc: Any, settings_get: Any, poll_s: float = DEFAULT_POLL_S, kite: Any = None):
        """`root` = `<db dir>/recordings` (None for an in-memory database: recording is then refused).
        `settings_get` = async callable returning the stored settings dict (so the cap and retention are read fresh each time).
        `poll_s` is a plain attribute on purpose: tests set it to a few milliseconds."""
        self.root = root
        self.svc = svc
        self.settings_get = settings_get
        self.poll_s = poll_s
        self.kite = kite  # the Kite ticker (None in fixture mode): Indian symbols are recorded from it
        self.active: dict[str, _Active] = {}
        self._starting: set[str] = set()  # symbols whose start is awaiting the network or settings: a second start must not slip in (H-07)
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
        if to_kite(symbol):
            return await self._start_kite(symbol.strip().upper())
        try:
            base, quote = cd.parse_pair(symbol)
        except ValueError as e:
            raise RecorderError("bad_request", "RECORDER: CRYPTO ONLY (BINANCE SPOT PAIRS LIKE BTCUSDT)") from e
        sym = f"{base}{'USDT' if quote == 'USD' else quote}"
        self._reserve(sym)  # no await between the check and the reservation: a double click cannot start two tasks (audit H-07)
        try:
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
        finally:
            self._starting.discard(sym)

    def _reserve(self, key: str) -> None:
        """Claims `key` for a start in progress, or says it is already recording or being started."""
        if key in self.active or key in self._starting:
            raise RecorderError("conflict", f"ALREADY RECORDING {key}")
        self._starting.add(key)

    async def _start_kite(self, symbol: str) -> dict[str, Any]:
        """Records an Indian symbol from the Kite ticker (read-only): prints and book changes, no polling."""
        assert self.root is not None
        key = _clean(symbol)
        # The session route accepts folder names of 2-30 letters and digits (SESSION_RE): a longer or shorter one would record fine and
        # then never be readable, so refuse it now (audit L-02).
        if not 2 <= len(key) <= SESSION_NAME_MAX:
            raise RecorderError("bad_request", f"RECORDER NAME {key[:12]}... MUST BE 2-{SESSION_NAME_MAX} LETTERS AND DIGITS")
        try:
            kiteflow.need_ticker(self.kite)
        except DataError as e:
            raise RecorderError("bad_request", f"RECORDING {symbol} NEEDS THE KITE TICKER: {e}") from e
        self._reserve(key)  # audit H-07, as in the crypto path
        try:
            return await self._start_kite_reserved(symbol, key)
        finally:
            self._starting.discard(key)

    async def _start_kite_reserved(self, symbol: str, key: str) -> dict[str, Any]:
        cap, retention = await self._limits()
        self.delete_old(retention)
        if self.total_bytes() >= cap:
            raise RecorderError("conflict", f"RECORDER STOPPED: DISK CAP {cap // 1_000_000} MB (DELETE OLD SESSIONS IN REC)")
        (self.root / key).mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y-%m-%d-%H%M%S")
        rec = _Active(key, self.root / key / f"{stamp}.jsonl")
        rec.kite = symbol
        self._write(rec, [{"k": "meta", "v": 1, "symbol": symbol, "started": rec.started, "venue": "KITE", "kite": True}])
        self.stopped_notes.pop(key, None)
        self.active[key] = rec

        def on_event(sym: str, kind: str, data: dict[str, Any]) -> None:
            if sym != symbol:
                return
            if kind == "t":
                rec.buffer.append({"k": "kt", "t": data["t"], "p": data["p"], "q": data["q"]})
                if data["q"] > 0:
                    rec.trades += 1
            else:
                book = (data["buy"], data["sell"])
                if book != rec.last_book:  # a packet that repeats the same book adds nothing
                    rec.last_book = book
                    rec.buffer.append({"k": "kd", "t": data["t"], "buy": data["buy"], "sell": data["sell"]})
                    rec.snapshots += 1

        rec.listener = on_event  # type: ignore[attr-defined]
        self.kite.listeners.append(on_event)
        self.kite.hold(symbol)  # subscribed in full mode until `_finish`
        rec.task = asyncio.create_task(self._run_kite(rec), name=f"recorder:{key}")
        return self._active_row(rec)

    async def _run_kite(self, rec: _Active) -> None:
        """Flushes the buffered Kite lines every `poll_s` and ends the recording at the disk cap or when the Kite login ends."""
        try:
            while True:
                await asyncio.sleep(self.poll_s)
                self._flush(rec)
                cap, _ = await self._limits()
                if self.total_bytes() >= cap:
                    await self._finish(rec, f"DISK CAP {cap // 1_000_000} MB")
                    log.warning("recorder %s: RECORDER STOPPED: DISK CAP %d MB", rec.symbol, cap // 1_000_000)
                    return
                if not self.kite.session.logged_in:  # the daily login ended: nothing more will arrive, say so instead of idling
                    await self._finish(rec, "KITE LOGIN ENDED")
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("recorder %s crashed", rec.symbol)
            await self._finish(rec, "CRASHED (SEE LOG)")

    def _flush(self, rec: _Active) -> None:
        if rec.buffer:
            lines, rec.buffer = rec.buffer, []
            self._write(rec, lines)

    async def stop(self, symbol: str) -> dict[str, Any]:
        if to_kite(symbol):
            sym = _clean(symbol)
        else:
            try:
                base, quote = cd.parse_pair(symbol)
            except ValueError as e:
                raise RecorderError("bad_request", "RECORDER: CRYPTO ONLY (BINANCE SPOT PAIRS LIKE BTCUSDT) OR KITE-SERVED INDIAN SYMBOLS") from e
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
        if rec.kite is not None and self.kite is not None:
            listener = getattr(rec, "listener", None)
            if listener in self.kite.listeners:
                self.kite.listeners.remove(listener)
            self.kite.release(rec.kite)
            self._flush(rec)
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
        kticks: list[dict[str, Any]] = []  # Kite sessions: prints and book changes (see the module note)
        kdepth: list[dict[str, Any]] = []
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
            elif k == "kt":
                kticks.append(row)
            elif k == "kd":
                kdepth.append(row)
            elif k == "end":
                end = row
        if len(trades) > MAX_SESSION_LINES:
            trades, truncated = trades[-MAX_SESSION_LINES:], True
        if len(depth) > MAX_SESSION_LINES // 10:
            depth, truncated = depth[-(MAX_SESSION_LINES // 10):], True
        if len(kticks) > MAX_SESSION_LINES:
            kticks, truncated = kticks[-MAX_SESSION_LINES:], True
        if len(kdepth) > MAX_SESSION_LINES // 5:
            kdepth, truncated = kdepth[-(MAX_SESSION_LINES // 5):], True
        return {"id": sid, "meta": meta, "trades": trades, "depth": depth, "kticks": kticks, "kdepth": kdepth, "end": end, "truncated": truncated,
                "bytes": size}

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

    @staticmethod
    def _is_kite(s: dict[str, Any]) -> bool:
        return bool((s.get("meta") or {}).get("kite"))

    @staticmethod
    def _kite_recorded(s: dict[str, Any], count: int) -> dict[str, Any]:
        started = (s["meta"] or {}).get("started") or _stamp_to_epoch(s["id"].split("/")[1])
        return {"id": s["id"], "started": started, "ended": (s["end"] or {}).get("t"), "reason": (s["end"] or {}).get("reason"),
                "truncated": s["truncated"], "snapshots": count}

    def replay_tas(self, sid: str, limit: int) -> dict[str, Any]:
        s = self.read_session(sid)
        if self._is_kite(s):  # a Kite session: the tick rule guesses the sides, exactly as the live Kite TAS does
            prints = [(i, t["t"], t["p"], t["q"]) for i, t in enumerate(s["kticks"], 1)]
            if not any(p[3] > 0 for p in prints):
                raise RecorderError("not_found", f"SESSION {sid} HAS NO PRINTS YET")
            data = kiteflow.tas_payload(s["meta"]["symbol"], prints, limit, venue="KITE (RECORDED)")
            return self._replay_envelope({**data, "recorded": self._kite_recorded(s, len(s["kdepth"]))})
        trades, head = self._replay_head(s)
        return self._replay_envelope({**head, "rows": of.recent(trades, limit)})

    def replay_footprint(self, sid: str, interval: str, bars: int, step: float | None) -> dict[str, Any]:
        iv = of.INTERVAL_MS.get(interval)
        if iv is None:
            raise RecorderError("bad_request", f"INTERVAL: {', '.join(of.INTERVAL_MS)}")
        s = self.read_session(sid)
        if self._is_kite(s):
            raise RecorderError("bad_request", "FOOT NEEDS EXACT TRADES: A KITE SESSION HAS ONLY PRICE AND VOLUME PRINTS (USE TAS OR DOM)")
        trades, head = self._replay_head(s)
        try:
            # truncated=True marks the OLDEST bar partial: a recording starts mid-bar, so that bar lacks its first trades.
            fp = of.footprint(trades, iv, bars, step, True)
        except ValueError as e:
            raise RecorderError("bad_request", str(e)) from e
        return self._replay_envelope({**head, "interval": interval, "bars_asked": bars, "truncated": False, **fp})

    def replay_depth(self, sid: str, index: int) -> dict[str, Any]:
        """Snapshot number `index` (0 = oldest; negative counts from the newest, so -1 = the last one) in the CDEP / DOM payload shape."""
        s = self.read_session(sid)
        snaps = s["kdepth"] if self._is_kite(s) else s["depth"]
        if not snaps:
            raise RecorderError("not_found", f"SESSION {sid} HAS NO ORDER-BOOK SNAPSHOTS YET")
        if not -len(snaps) <= index < len(snaps):
            raise RecorderError("bad_request", f"SNAPSHOT {index} OUT OF RANGE (0 TO {len(snaps) - 1})")
        snap = dict(snaps[index])
        recorded_t = snap.pop("t")
        if self._is_kite(s):
            data = kiteflow.depth_payload(s["meta"]["symbol"], {"t": recorded_t, "buy": snap["buy"], "sell": snap["sell"]})
            data["venue"] = "KITE (RECORDED) · BEST 5 LEVELS A SIDE"
            started = (s["meta"] or {}).get("started") or _stamp_to_epoch(sid.split("/")[1])
            return self._replay_envelope({**data, "recorded": {"id": sid, "started": started, "at": recorded_t, "index": index % len(snaps),
                                                               "count": len(snaps), "ended": (s["end"] or {}).get("t"), "truncated": s["truncated"]}})
        started = (s["meta"] or {}).get("started") or _stamp_to_epoch(sid.split("/")[1])
        return self._replay_envelope({**snap, "recorded": {"id": sid, "started": started, "at": recorded_t, "index": index % len(snaps),
                                                           "count": len(snaps), "ended": (s["end"] or {}).get("t"), "truncated": s["truncated"]}})


def _clean(symbol: str) -> str:
    """The folder / session name of a symbol: letters and digits only (`RELIANCE.NS` -> `RELIANCENS`), the rule `recArgs.sessionId` uses."""
    return re.sub(r"[^A-Z0-9]", "", symbol.upper())


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
