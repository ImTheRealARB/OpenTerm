"""Daily brief (Phase 17 C): a plain data summary of the user's day. No AI is involved.

How it works: `build_brief(app)` calls the app's OWN routes in-process (httpx.ASGITransport, as a local
user, the same trick `ai/tools.ToolRunner` uses), so the brief shows exactly what the panels show and
reuses their caches, error handling and source/age meta. Each of the five sections is built on its own:
a failing one becomes `error="ERR <source>"` with no lines, and the brief still completes.

Contract (the frontend relies on it exactly):
  {"at": epoch seconds,
   "sections": [{"id": movers|alerts|earnings|eco|news, "title", "source", "age_s", "stale", "error", "lines"}],
   "watchlist": name | None}
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime

import httpx

from .redact import redact

KV_KEY = "brief:last"
DAY_S = 24 * 3600
TOP_N = 5  # movers and headlines shown


class _Section:
    """Mutable builder for one section; `.dict()` gives the contract shape."""

    def __init__(self, sid: str, title: str):
        self.id, self.title = sid, title
        self.source: str | None = None
        self.age_s: float | None = None
        self.stale = False
        self.error: str | None = None
        self.lines: list[str] = []

    def take_meta(self, env: dict) -> None:
        """Copies source/age/stale from a route envelope ({"data", "source", "age_s", "stale"}).
        Same idea as ai/tools._meta; for a multi-symbol quote answer we keep the OLDEST age."""
        if env.get("source") is not None:
            self.source = env.get("source")
        age = env.get("age_s")
        if isinstance(age, (int, float)) and (self.age_s is None or age > self.age_s):
            self.age_s = age
        self.stale = self.stale or bool(env.get("stale"))

    def fail(self, what: str) -> None:
        self.error = f"ERR {what}"
        self.lines = []

    def dict(self) -> dict:
        return {"id": self.id, "title": self.title, "source": self.source, "age_s": self.age_s,
                "stale": self.stale, "error": self.error, "lines": self.lines}


async def _get(http: httpx.AsyncClient, url: str):
    """GET -> parsed JSON. Raises on a non-200 so the caller's section turns into ERR."""
    r = await http.get(url)
    body = r.json()
    if r.status_code != 200:
        # the route's own error text is already redacted, but redact again: it goes to email/Telegram
        raise RuntimeError(redact(str(body.get("error") or r.status_code)) if isinstance(body, dict) else str(r.status_code))
    return body


def _pick_watchlist(lists: list[dict]) -> str | None:
    """"default" (any case) if it exists, otherwise the first list by name; None when there are none."""
    if not lists:
        return None
    for w in lists:
        if str(w.get("name", "")).lower() == "default":
            return w["name"]
    return lists[0]["name"]


async def _movers(http, name: str | None, sec: _Section) -> None:
    if name is None:
        sec.lines = ["NO WATCHLIST: create one with WL"]
        return
    wl = await _get(http, f"/api/watchlists/{name}")
    symbols = wl.get("symbols") or []
    if not symbols:
        sec.lines = [f"WATCHLIST {name} IS EMPTY"]
        return
    res = (await _get(http, "/api/quote?symbols=" + ",".join(symbols)))["results"]
    rows = []
    for sym, env in res.items():
        d = env.get("data") if isinstance(env, dict) else None
        if not d or d.get("change_pct") is None:
            continue  # this symbol failed or has no change; skipped, not invented
        sec.take_meta(env)
        rows.append((sym, d["price"], d["change_pct"]))
    if not rows:
        sec.fail("quote")
        return
    up = sum(1 for r in rows if r[2] > 0)
    down = sum(1 for r in rows if r[2] < 0)
    sec.lines = [f"{name}: {up} up, {down} down, {len(rows) - up - down} flat of {len(symbols)}"]
    for sym, price, pct in sorted(rows, key=lambda r: -abs(r[2]))[:TOP_N]:
        sec.lines.append(f"{sym} {price:,.2f} ({pct:+.2f}%)")


async def _alerts(http, sec: _Section, now: float) -> None:
    cutoff = now - DAY_S
    price = (await _get(http, "/api/alerts"))["alerts"]
    news = (await _get(http, "/api/newsalerts"))["alerts"]
    for a in price:
        if (a.get("triggered_at") or 0) >= cutoff:
            at = datetime.fromtimestamp(a["triggered_at"]).strftime("%H:%M")
            sec.lines.append(f"{at} {a['symbol']} {a['op']} {a['value']} (hit at {a.get('trigger_price')})")
    for a in news:
        if (a.get("triggered_at") or 0) >= cutoff:
            at = datetime.fromtimestamp(a["triggered_at"]).strftime("%H:%M")
            sec.lines.append(f"{at} news '{a['word']}': {a.get('headline') or ''}".rstrip())
    if not sec.lines:
        sec.lines = ["NO ALERTS TRIGGERED IN THE LAST 24 H"]
    sec.source = "local alerts"  # these two lists live in the user's own database


async def _earnings(http, watch: list[str], sec: _Section) -> None:
    env = await _get(http, "/api/earnings")
    sec.take_meta(env)
    rows = (env.get("data") or {}).get("rows") or []
    if not watch:
        sec.lines = ["NO WATCHLIST: cannot filter earnings to your names"]
        return
    mine = {s.upper() for s in watch}
    for r in rows:
        if r.get("symbol") in mine:
            when = {"PRE": " before open", "POST": " after close"}.get(r.get("time"), "")
            sec.lines.append(f"{r['symbol']}{when}")
    if not sec.lines:
        sec.lines = ["NONE OF YOUR WATCHLIST REPORTS TODAY"]


async def _eco(http, sec: _Section) -> None:
    env = await _get(http, f"/api/eco?start={date.today().isoformat()}&days=1")
    sec.take_meta(env)
    events = (env.get("data") or {}).get("events") or []
    for e in events:
        star = " *" if e.get("major") else ""
        sec.lines.append(f"{e.get('time') or '--:--'} {e.get('name')} ({e.get('agency')}){star}")
    if not sec.lines:
        sec.lines = ["NO ECONOMIC EVENTS TODAY"]


async def _news(http, sec: _Section) -> None:
    env = await _get(http, "/api/news")
    sec.take_meta(env)
    for it in ((env.get("data") or {}).get("items") or [])[:TOP_N]:
        pub = f" ({it['publisher']})" if it.get("publisher") else ""
        sec.lines.append(f"{it.get('title')}{pub}")
    if not sec.lines:
        sec.lines = ["NO HEADLINES"]


async def build_brief(app) -> dict:
    """Builds the brief now. Never raises for a section failure; each shows `ERR <source or route>`."""
    now = time.time()
    sections = {
        "movers": _Section("movers", "WATCHLIST MOVERS"),
        "alerts": _Section("alerts", "ALERTS (LAST 24 H)"),
        "earnings": _Section("earnings", "EARNINGS TODAY"),
        "eco": _Section("eco", "ECONOMIC EVENTS TODAY"),
        "news": _Section("news", "TOP HEADLINES"),
    }
    name: str | None = None
    symbols: list[str] = []
    # client ("127.0.0.1", ...) so loopback-only routes treat this as the local user
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 50000)),
                                 base_url="http://openterm.local", timeout=60.0) as http:
        try:
            name = _pick_watchlist((await _get(http, "/api/watchlists"))["watchlists"])
            if name:
                symbols = (await _get(http, f"/api/watchlists/{name}")).get("symbols") or []
        except Exception as e:  # noqa: BLE001 - becomes the movers/earnings section error below
            sections["movers"].fail(redact(f"watchlists {e}"))
            name = None
        steps = [("movers", lambda s: _movers(http, name, s) if not s.error else _noop()),
                 ("alerts", lambda s: _alerts(http, s, now)),
                 ("earnings", lambda s: _earnings(http, symbols, s)),
                 ("eco", lambda s: _eco(http, s)),
                 ("news", lambda s: _news(http, s))]
        routes = {"movers": "quote", "alerts": "alerts", "earnings": "earnings", "eco": "eco", "news": "news"}
        for sid, step in steps:
            sec = sections[sid]
            try:
                await step(sec)
            except Exception as e:  # noqa: BLE001 - one failed section must not stop the brief
                src = sec.source or routes[sid]
                sec.fail(src)
                sec.source = sec.source or None
                sec.error = redact(f"ERR {src}: {e}"[:200])
    return {"at": now, "sections": [s.dict() for s in sections.values()], "watchlist": name}


async def _noop() -> None:
    return None


def format_text(brief: dict) -> tuple[str, str]:
    """Plain text for email/Telegram/webhook: header line per section, then its lines. Not AI-written."""
    day = datetime.fromtimestamp(brief["at"]).strftime("%Y-%m-%d")
    out: list[str] = []
    for s in brief["sections"]:
        meta = ", ".join(x for x in (s.get("source"), f"{s['age_s']:.0f}s old" if s.get("age_s") is not None else None,
                                     "STALE" if s.get("stale") else None) if x)
        out.append(f"== {s['title']}" + (f" ({meta})" if meta else "") + " ==")
        out.extend([s["error"]] if s.get("error") else s["lines"])
        out.append("")
    return f"OpenTerm daily brief {day}", "\n".join(out).rstrip() + "\n"


async def store(app, brief: dict) -> None:
    db = app.state.userdata.db
    await db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (KV_KEY, json.dumps(brief)))
    await db.commit()


async def last(app) -> dict | None:
    async with app.state.userdata.db.execute("SELECT value FROM kv WHERE key=?", (KV_KEY,)) as cur:
        row = await cur.fetchone()
    return json.loads(row[0]) if row else None


async def run(app, send: bool) -> tuple[dict, list[dict] | None]:
    """Build + store; optionally deliver to the enabled push channels (kind "brief", ref = the date)."""
    brief = await build_brief(app)
    await store(app, brief)
    if not send:
        return brief, None
    from . import delivery

    subject, text = format_text(brief)
    day = subject.rsplit(" ", 1)[1]
    return brief, await delivery.dispatch(app, "brief", day, subject, text, {"kind": "brief"})


async def scheduled_run(app) -> None:
    """The cron job body. A failure is logged, never raised into apscheduler."""
    import logging

    try:
        await run(app, send=True)
    except Exception as e:  # noqa: BLE001
        logging.getLogger("openterm.brief").warning("scheduled brief failed: %s", redact(str(e)))
