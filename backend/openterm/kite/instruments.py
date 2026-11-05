"""The Kite instruments dump (`GET /instruments`, CSV): cached 24 h in memory and in the `kv` table, looked up by Kite key
(`EXCHANGE:TRADINGSYMBOL`) or token. Parsing runs in a thread (the real dump has about 100,000 rows)."""

from __future__ import annotations

import asyncio
import csv
import io
import time
import zlib
from dataclasses import dataclass, field

TTL_S = 86400.0
KV_KEY = "kite:instruments"


@dataclass
class Dump:
    fetched_at: float
    by_key: dict[str, dict] = field(default_factory=dict)
    by_token: dict[int, dict] = field(default_factory=dict)
    derivs: dict[tuple[str, str], list[dict]] = field(default_factory=dict)  # (exchange, underlying name) -> FUT / CE / PE rows
    by_bse_code: dict[int, dict] = field(default_factory=dict)  # BSE scrip code (exchange_token) -> share row

    def find(self, key: str) -> dict | None:
        """The row for `EXCHANGE:TRADINGSYMBOL`. A BSE key may also carry the numeric scrip code Yahoo uses (`BSE:500325` is `BSE:RELIANCE`):
        Kite's trading symbol is the name, and the code is the row's exchange_token."""
        row = self.by_key.get(key)
        if row is None and key.startswith("BSE:") and key[4:].isdigit():
            row = self.by_bse_code.get(int(key[4:]))
        return row

    def chain_rows(self, exchange: str, name: str, kinds: tuple[str, ...]) -> list[dict]:
        return [r for r in self.derivs.get((exchange, name.upper()), []) if r["instrument_type"] in kinds]


def parse(text: str, fetched_at: float) -> Dump:
    d = Dump(fetched_at)
    for row in csv.DictReader(io.StringIO(text)):
        try:
            r = {
                "instrument_token": int(row["instrument_token"]), "exchange_token": int(row["exchange_token"] or 0),
                "tradingsymbol": row["tradingsymbol"], "name": row.get("name") or "", "expiry": row.get("expiry") or None,
                "strike": float(row.get("strike") or 0), "tick_size": float(row.get("tick_size") or 0),
                "lot_size": int(float(row.get("lot_size") or 0)), "instrument_type": row.get("instrument_type") or "",
                "segment": row.get("segment") or "", "exchange": row.get("exchange") or "",
            }
        except (KeyError, ValueError):
            continue  # one damaged line is dropped, never guessed
        d.by_key[f"{r['exchange']}:{r['tradingsymbol']}"] = r
        d.by_token[r["instrument_token"]] = r
        if r["exchange"] == "BSE" and r["segment"] == "BSE" and r["exchange_token"]:
            d.by_bse_code[r["exchange_token"]] = r
        if r["instrument_type"] in ("FUT", "CE", "PE") and r["name"]:
            d.derivs.setdefault((r["exchange"], r["name"].upper()), []).append(r)
    return d


class Instruments:
    def __init__(self, client, db=None):
        self.client = client
        self.db = db
        self._dump: Dump | None = None
        self._lock = asyncio.Lock()

    def forget(self) -> None:
        self._dump = None

    async def _from_kv(self) -> Dump | None:
        if self.db is None:
            return None
        async with self.db.execute("SELECT value FROM kv WHERE key=?", (KV_KEY,)) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        try:
            blob = await asyncio.to_thread(zlib.decompress, row[0])
            head, _, text = blob.decode("utf-8").partition("\n")
            at = float(head)
        except (zlib.error, ValueError):
            return None
        if time.time() - at >= TTL_S:
            return None
        return await asyncio.to_thread(parse, text, at)

    async def _to_kv(self, text: str, at: float) -> None:
        if self.db is None:
            return
        blob = await asyncio.to_thread(zlib.compress, f"{at}\n{text}".encode(), 3)
        await self.db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (KV_KEY, blob))
        await self.db.commit()

    async def get(self, force: bool = False) -> Dump:
        """The dump, from memory, else the kv table, else Kite (`force` skips both caches)."""
        async with self._lock:
            if not force and self._dump is not None and time.time() - self._dump.fetched_at < TTL_S:
                return self._dump
            if not force:
                self._dump = await self._from_kv()
                if self._dump is not None:
                    return self._dump
            text = await self.client.get_text("/instruments")
            at = time.time()
            self._dump = await asyncio.to_thread(parse, text, at)
            await self._to_kv(text, at)
            return self._dump

    async def resolve(self, key: str) -> dict | None:
        return (await self.get()).find(key)
