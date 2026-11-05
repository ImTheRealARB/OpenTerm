"""Server-side alerts (Phase 20): price, percent and news-keyword alerts that fire with the browser closed.

Before this, alerts were checked inside the browser tab (frontend/src/command/alerts.ts), so a closed tab meant a silent alert.
Now the backend owns firing:
  - it subscribes to the symbols of active price alerts through the same refcounted hub a panel uses, and checks every tick
    (the hub calls `on_tick` for each tick through `Hub.tick_listeners`);
  - every `NEWS_POLL_S` seconds it fetches the headlines each active news alert watches and checks them;
  - a match marks the alert triggered ONCE with the SAME store code the HTTP trigger routes use (`Alerts.trigger` /
    `NewsAlerts.trigger`, which refuse a second trigger), pushes a WebSocket frame so open tabs refresh, and hands the message
    to Phase 17 delivery (`delivery.spawn`, which sends to the channels switched on in DELIVERY).

Honest limits, shown in the ALRT panel: it runs only while OpenTerm's backend runs (a sleeping machine fires nothing), and it
never fires on a SYNTHETIC tick, a STALE tick (older than `STALE_S`), a fixture-mode tick or a stale news answer. Every match it
refuses to act on is remembered with its reason, so ALRT can show "why did my alert not fire".
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable

from .delivery import format as dfmt
from .news_alerts import NewsAlerts
from .portfolio import Alerts

log = logging.getLogger("openterm.alerts")

STALE_S = 120.0  # a tick older than this is not "now": no alert on it
NEWS_POLL_S = 120.0  # how often active news alerts look at the headlines (same as the old browser poll)
FIRST_NEWS_POLL_S = 10.0  # first look shortly after start (not at once: startup stays free of network calls)
STALE_NEWS_RETRY_S = 5.0  # the news cache lives about as long as the poll gap, so a "stale" answer is retried once after this
# Source codes on a Tick (see streaming/tick.py) -> words used in the message sent out.
SOURCE_NAMES = {"y": "yahoo stream", "p": "yahoo poll", "a": "alpaca iex", "k": "kite", "s": "synthetic"}


def tick_pct(price: float, pct: float | None, change: float | None) -> float | None:
    """Percent change vs the previous close from a tick: its own pct, else derived from the absolute change."""
    if pct is not None:
        return pct
    if change is None:
        return None
    prev = price - change
    return change / prev * 100 if prev > 0 else None


def rule_met(op: str, unit: str, value: float, price: float, pct: float | None, change: float | None) -> bool:
    """True when the rule holds (levels are inclusive: '> 200' fires at 200.00). Same maths as the browser's `alertMet`."""
    if math.isnan(price):  # NaN never satisfies a rule
        return False
    x = price if unit == "price" else tick_pct(price, pct, change)
    if x is None:
        return False
    return x >= value if op == ">" else x <= value


def news_match(word: str, title: str) -> bool:
    """True when `title` contains `word` as a whole word (case-insensitive, optional plural s). Same as the browser's `newsMatch`."""
    w = word.strip()
    return bool(w) and re.search(rf"(?<![A-Za-z0-9]){re.escape(w)}s?(?![A-Za-z0-9])", title, re.IGNORECASE) is not None


def describe(a: dict) -> str:
    """Short label for the ALRT panel, e.g. 'AAPL > 200' or 'MSFT < -3%'."""
    if a["unit"] == "price":
        return f"{a['symbol']} {a['op']} {a['value']:g}"
    return f"{a['symbol']} {a['op']} {a['value']:+g}%"


class _HubClient:
    """The engine's seat on the hub. The hub only needs a `symbols` set to count subscriptions per symbol."""

    def __init__(self) -> None:
        self.symbols: set[str] = set()


class AlertsEngine:
    """`deliver(kind, ref, subject, text, extra[, channels=...])` is `alert_channels.spawn(app, ...)` in the app; tests pass a recorder.

    `channels` is passed only for an alert created with `VIA`; without it the hook gets 5 arguments (all enabled channels).
    """

    def __init__(self, db, hub, deliver: Callable[..., object], news_fetch: Callable[[str | None], Awaitable[dict]], *,
                 fixtures: bool, now: Callable[[], float] = time.time):
        self.db, self.hub, self.deliver, self.news_fetch = db, hub, deliver, news_fetch
        self.fixtures, self.now = fixtures, now
        self.alerts, self.news = Alerts(db), NewsAlerts(db)
        self._seat = _HubClient()
        self._rules: dict[str, list[dict]] = {}  # symbol -> active price rules
        self._firing: set[tuple[str, int]] = set()  # (kind, id) being fired right now: never twice
        self._tasks: set[asyncio.Task] = set()
        self._news_task: asyncio.Task | None = None
        self._skipped: dict[str, dict] = {}  # "price:3" -> matches we refused to act on, with the reason
        self.last_tick_at: float | None = None
        self.last_news_poll_at: float | None = None
        self.running = False

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self.running = True
        self.hub.tick_listeners.append(self.on_tick)
        await self.sync()
        self._news_task = asyncio.create_task(self._news_loop())

    async def stop(self) -> None:
        self.running = False
        if self.on_tick in self.hub.tick_listeners:
            self.hub.tick_listeners.remove(self.on_tick)
        if self._news_task:
            self._news_task.cancel()
        for t in list(self._tasks):
            t.cancel()
        await self.hub.unsubscribe(self._seat, list(self._seat.symbols))

    async def sync(self) -> None:
        """Reloads the active price rules and makes the hub subscription match their symbols (add first, then drop).

        Called at start and by every route that creates, deletes, triggers or rearms an alert.
        """
        rules: dict[str, list[dict]] = {}
        live: set[str] = set()
        for a in await self.alerts.all():
            if a["status"] == "active":
                rules.setdefault(a["symbol"], []).append(a)
                live.add(f"price:{a['id']}")
        self._rules = rules
        for a in await self.news.all():
            if a["status"] == "active":
                live.add(f"news:{a['id']}")
        for key in [k for k in self._skipped if k not in live]:
            del self._skipped[key]  # a deleted or already-triggered alert has nothing left to explain
        want, have = set(rules), set(self._seat.symbols)
        if want - have:
            await self.hub.subscribe(self._seat, sorted(want - have))
        if have - want:
            await self.hub.unsubscribe(self._seat, sorted(have - want))

    # ------------------------------------------------------------ price alerts (the hub calls this for every tick)
    def on_tick(self, tick) -> None:
        """Synchronous and cheap: one dict lookup for symbols nobody watches. It must never raise into the hub."""
        rules = self._rules.get(tick.symbol)
        if not rules:
            return
        try:
            self.last_tick_at = self.now()
            for a in rules:
                key = ("price", a["id"])
                if key in self._firing or not rule_met(a["op"], a["unit"], a["value"], tick.price, tick.change_pct, tick.change):
                    continue
                reason = self.refusal(tick)
                if reason:
                    self._skip(f"price:{a['id']}", describe(a), reason)
                    continue
                self._skipped.pop(f"price:{a['id']}", None)
                self._firing.add(key)
                self._spawn(self._fire_price(a, tick))
        except Exception:  # a bug here must not stop the price stream the hub is delivering
            log.exception("alert check failed for %s", tick.symbol)

    def refusal(self, tick) -> str | None:
        """Why this tick must not fire an alert (None = fine). Bad data never alerts (spec rule 2)."""
        if self.fixtures:
            return "FIXTURE MODE"
        if tick.source == "s":
            return "SYNTHETIC TICK"
        age = self.now() - tick.time_ms / 1000
        if age > STALE_S:
            return f"STALE TICK {age:.0f}s OLD"
        return None

    def _skip(self, key: str, label: str, reason: str) -> None:
        self._skipped[key] = {"label": label, "reason": reason, "at": self.now()}

    def _deliver(self, kind: str, ref: int, subject: str, text: str, extra: dict, channels: list[str] | None) -> None:
        """Hands a fired alert to delivery. `channels` is the alert's `VIA` list; None (no VIA) calls the hook with the plain
        5 arguments, so it means "every enabled channel" exactly as before."""
        if channels is None:
            self.deliver(kind, ref, subject, text, extra)
        else:
            self.deliver(kind, ref, subject, text, extra, channels=channels)

    def _spawn(self, coro) -> None:
        t = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _fire_price(self, a: dict, tick) -> None:
        try:
            # Same store call (and so the same DB write) as POST /api/alerts/{id}/trigger. `changed` is False when the
            # alert was already triggered (a second path got there first): then nothing is sent, so nothing repeats.
            res = await self.alerts.trigger(a["id"], tick.price, self.now())
            if res["changed"]:
                self.hub.broadcast(["A", "price", a["id"]])  # open tabs refresh their list from this
                age = max(0.0, self.now() - tick.time_ms / 1000)
                where = f"by the OpenTerm server (source {SOURCE_NAMES.get(tick.source, tick.source)}, {age:.0f} s old)"
                subject, text = dfmt.alert_message(res["alert"], checked=where)
                self._deliver("alert", a["id"], subject, text, {"kind": "alert", "symbol": a["symbol"]}, res["alert"]["channels"])
        except Exception as e:  # shown in ALRT and the log; the next tick is not blocked
            log.exception("price alert %s could not be fired", a["id"])  # the log filter redacts secrets
            self._skip(f"price:{a['id']}", describe(a), f"FIRE FAILED: {type(e).__name__}")
        finally:
            self._firing.discard(("price", a["id"]))
            try:
                await self.sync()  # it is triggered now: drop it from the rules and maybe from the subscription
            except Exception:  # e.g. the database closing at shutdown
                log.exception("alert engine sync failed")

    # ------------------------------------------------------------ news alerts
    async def _news_loop(self) -> None:
        await asyncio.sleep(FIRST_NEWS_POLL_S)
        while True:
            try:
                await self.poll_news()
            except Exception:  # one bad poll must not end the loop
                log.exception("news alert poll failed")
            await asyncio.sleep(NEWS_POLL_S)

    async def _fetch_news(self, symbol: str | None) -> dict:
        env = await self.news_fetch(symbol)
        if env.get("stale"):
            # A stale answer was just served and a refresh started in the background: look once more shortly after.
            await asyncio.sleep(STALE_NEWS_RETRY_S)
            env = await self.news_fetch(symbol)
        return env

    async def poll_news(self) -> int:
        """Fetches the headlines every active news alert watches and fires the ones that match. Returns how many fired."""
        active = [a for a in await self.news.all() if a["status"] == "active"]
        self.last_news_poll_at = self.now()
        fired = 0
        for symbol in {a["symbol"] for a in active}:
            watching = [a for a in active if a["symbol"] == symbol]
            if self.fixtures:
                for a in watching:
                    self._skip(f"news:{a['id']}", self._news_label(a), "FIXTURE MODE")
                continue
            try:
                env = await self._fetch_news(symbol)
            except Exception as e:  # noqa: BLE001 - a news outage: the alert waits for the next poll and ALRT says why
                for a in watching:
                    self._skip(f"news:{a['id']}", self._news_label(a), f"NEWS UNAVAILABLE: {type(e).__name__}")
                continue
            items = (env.get("data") or {}).get("items") or []
            for a in watching:
                # only headlines published AFTER the alert was created or rearmed count, so old news never fires
                hit = next((i for i in items if i.get("published") and i["published"] > a["created_at"]
                            and news_match(a["word"], i.get("title") or "")), None)
                if hit is None:
                    self._skipped.pop(f"news:{a['id']}", None)
                    continue
                if env.get("stale"):
                    self._skip(f"news:{a['id']}", self._news_label(a), "STALE NEWS ANSWER")
                    continue
                self._skipped.pop(f"news:{a['id']}", None)
                res = await self.news.trigger(a["id"], hit.get("title"), hit.get("url"), self.now())
                if res["changed"]:
                    fired += 1
                    self.hub.broadcast(["A", "news", a["id"]])
                    subject, text = dfmt.news_alert_message(res["alert"])
                    self._deliver("news", a["id"], subject, text, {"kind": "news", "word": a["word"]}, res["alert"]["channels"])
        await self.sync()  # triggered news alerts leave the skip list
        return fired

    @staticmethod
    def _news_label(a: dict) -> str:
        return f'NEWS {a["symbol"] or "MARKET"} "{a["word"]}"'

    # ------------------------------------------------------------ for GET /api/alerts/engine (the ALRT panel)
    def state(self) -> dict:
        now = self.now()
        return {
            "running": self.running,
            "note": "ACTIVE WHILE OPENTERM RUNNING",
            "watching": sorted(self._rules),
            "last_tick_age_s": None if self.last_tick_at is None else round(now - self.last_tick_at, 1),
            "last_news_poll_age_s": None if self.last_news_poll_at is None else round(now - self.last_news_poll_at, 1),
            "fixtures": self.fixtures,
            "skipped": [
                {"key": k, "label": v["label"], "reason": v["reason"], "age_s": round(now - v["at"], 1)}
                for k, v in sorted(self._skipped.items())
            ],
        }
