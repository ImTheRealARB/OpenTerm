"""News keyword alerts (`ALRT NEWS <WORD> [SYM]`, Phase 13 spec K). Stored here, evaluated in the browser on each news
refresh (like price alerts are evaluated on ticks): a headline published after the alert was created that contains the
word fires it once. `symbol` NULL watches the market top stories.
"""

import re
import time

import aiosqlite

from . import alert_channels
from .idents import STORED_SYMBOL_RE
from .symbols import resolve
from .userdata import UserDataError

MAX_NEWS_ALERTS = 50
WORD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .&'/-]{0,38}[A-Za-z0-9.]\Z|^[A-Za-z0-9]{2}\Z")
COLS = "id, word, symbol, status, created_at, triggered_at, headline, url, channels"


def _row(r) -> dict:
    d = dict(zip(COLS.split(", "), r, strict=True))
    d["channels"] = alert_channels.load(d["channels"])  # stored as JSON text; None = all enabled channels
    return d


def check(body: dict) -> tuple[str, str | None]:
    word = " ".join(str(body.get("word") or "").split())
    if not WORD_RE.match(word):
        raise UserDataError("bad_request", "NEWS ALERT WORD: 2-40 LETTERS, DIGITS OR . & ' / -")
    symbol = body.get("symbol")
    if symbol in (None, ""):
        return word.upper(), None
    symbol = str(symbol).strip().upper()
    if not STORED_SYMBOL_RE.match(symbol):
        raise UserDataError("bad_request", f"BAD SYMBOL: {symbol}")
    return word.upper(), resolve(symbol)


class NewsAlerts:
    """States: active -> triggered (headline, link and time recorded once) -> active again on rearm."""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def all(self) -> list[dict]:
        async with self.db.execute(f"SELECT {COLS} FROM news_alerts ORDER BY id") as cur:
            return [_row(r) for r in await cur.fetchall()]

    async def _one(self, alert_id: int) -> dict:
        async with self.db.execute(f"SELECT {COLS} FROM news_alerts WHERE id=?", (alert_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            raise UserDataError("not_found", f"NO NEWS ALERT {alert_id}")
        return _row(row)

    async def create(self, body: dict) -> dict:
        word, symbol = check(body)
        channels = alert_channels.parse(body.get("channels"))  # 400 on an unknown channel name
        async with self.db.execute("SELECT COUNT(*) FROM news_alerts") as cur:
            (n,) = await cur.fetchone()
        if n >= MAX_NEWS_ALERTS:
            raise UserDataError("too_large", f"OVER {MAX_NEWS_ALERTS} NEWS ALERTS. ALRT CLEAR REMOVES TRIGGERED ONES")
        cur = await self.db.execute(
            "INSERT INTO news_alerts (word, symbol, status, created_at, channels) VALUES (?, ?, 'active', ?, ?)",
            (word, symbol, time.time(), alert_channels.dump(channels)),
        )
        await self.db.commit()
        return await self._one(cur.lastrowid)

    async def trigger(self, alert_id: int, headline, url, at=None) -> dict:
        """Marks an active alert triggered with the headline that matched. A second report changes nothing."""
        head = " ".join(str(headline or "").split())[:300] or None
        link = str(url) if isinstance(url, str) and url.startswith(("https://", "http://")) and len(url) <= 2000 else None
        when = float(at) if isinstance(at, (int, float)) and not isinstance(at, bool) else time.time()
        cur = await self.db.execute(
            "UPDATE news_alerts SET status='triggered', headline=?, url=?, triggered_at=? WHERE id=? AND status='active'",
            (head, link, when, alert_id),
        )
        await self.db.commit()
        return {"alert": await self._one(alert_id), "changed": cur.rowcount == 1}

    async def rearm(self, alert_id: int) -> dict:
        await self._one(alert_id)
        # created_at moves up so the headline that fired it does not fire it again
        await self.db.execute(
            "UPDATE news_alerts SET status='active', headline=NULL, url=NULL, triggered_at=NULL, created_at=? WHERE id=?",
            (time.time(), alert_id),
        )
        await self.db.commit()
        return await self._one(alert_id)

    async def delete(self, alert_id: int) -> int:
        cur = await self.db.execute("DELETE FROM news_alerts WHERE id=?", (alert_id,))
        await self.db.commit()
        if cur.rowcount == 0:
            raise UserDataError("not_found", f"NO NEWS ALERT {alert_id}")
        return alert_id

    async def clear_triggered(self) -> int:
        cur = await self.db.execute("DELETE FROM news_alerts WHERE status='triggered'")
        await self.db.commit()
        return cur.rowcount
