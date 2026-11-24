"""Phase 27 smart alerts: indicator alerts (`ALRT AAPL RSI14<30`) and drawing alerts (`ALRT AAPL LINE`).

Indicator alerts use the backtester's rule grammar (`bt/rules.py`) on DAILY bars, checked by the server every
`CHECK_EVERY_MIN` minutes (and right after one is created), with the browser closed too. Only COMPLETE bars count: today's
bar is dropped until the market's day is over (`drop_forming`), so an alert fires "at the bar close", never on a half-made
bar. The rule is evaluated in a job worker (`alerts.ind`, the scanner's evaluator), because pandas never loads in the server.

Drawing alerts watch a line drawn on GP (TREND / RAY / XLINE / HLINE: the price CROSSES it; PCHAN: the price LEAVES the
channel). They are checked on every live tick by the alerts engine (`AlertsEngine.on_tick` calls `check_tick`). The line is
extended to the right through its two anchors, so it keeps working after its second anchor.

Both kinds fire ONCE (status becomes `triggered`), send through DELIVERY like price alerts and never fire in fixture mode or
on a synthetic or stale tick (the reason is kept and shown in ALRT). Stored in `kv` (`indalert:<id>`, `drawalert:<id>`).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
import uuid
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import orjson
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .errors import DataError
from .http_util import error, error_response
from .redact import redact
from .responses import Orjson, OrjsonRoute
from .symbols import resolve

log = logging.getLogger("openterm.smartalerts")
router = APIRouter(prefix="/api/smartalerts", route_class=OrjsonRoute)

CHECK_EVERY_MIN = 15
DAY_DONE_LOCAL = (16, 30)  # after this local time an exchange's daily bar counts as complete (every equity market here closes earlier)
LINE_KINDS = {"TREND", "RAY", "XLINE", "HLINE"}  # the price crossing the line
CHANNEL_KINDS = {"PCHAN"}  # the price leaving the channel
IND, DRAW = "indalert:", "drawalert:"


# --- pure helpers ------------------------------------------------------------------------------------------------------

def drop_forming(bars: dict, now: float) -> dict:
    """Columnar daily bars without today's still-forming bar. A bar is complete when a newer one exists, or when its local day
    is over: for a 24-hour market (zone UTC, crypto) at midnight, otherwise after 16:30 in the exchange's zone."""
    t = bars.get("t") or []
    if not t:
        return bars
    tz = bars.get("tz") or "UTC"
    zone = ZoneInfo(tz)
    last_day = dt.datetime.fromtimestamp(t[-1], zone).date()
    local_now = dt.datetime.fromtimestamp(now, zone)
    done = local_now.date() > last_day or (tz != "UTC" and local_now.date() == last_day
                                          and (local_now.hour, local_now.minute) >= DAY_DONE_LOCAL)
    if done:
        return bars
    return {k: (v[:-1] if isinstance(v, list) and len(v) == len(t) else v) for k, v in bars.items()}


def line_value(pts: list[dict], at: float) -> float:
    """Price of the line through the first two anchors ({t: epoch seconds, p: price}) at time `at`; one anchor = a level."""
    t1, p1 = float(pts[0]["t"]), float(pts[0]["p"])
    if len(pts) < 2:
        return p1
    t2, p2 = float(pts[1]["t"]), float(pts[1]["p"])
    if t2 == t1:
        return p2
    return p1 + (p2 - p1) * (at - t1) / (t2 - t1)


def channel(pts: list[dict], at: float) -> tuple[float, float]:
    """(lower, upper) of a parallel channel: the line through anchors 1-2 and the same line shifted to anchor 3."""
    base = line_value(pts[:2], at)
    shift = float(pts[2]["p"]) - line_value(pts[:2], float(pts[2]["t"]))
    a, b = base, base + shift
    return (min(a, b), max(a, b))


def where(alert: dict, price: float, at: float) -> int:
    """-1 below / +1 above the line; for a channel 0 inside, -1 below, +1 above."""
    if alert["kind"] in CHANNEL_KINDS:
        lo, hi = channel(alert["pts"], at)
        return -1 if price < lo else (1 if price > hi else 0)
    return 1 if price >= line_value(alert["pts"] if alert["kind"] != "HLINE" else alert["pts"][:1], at) else -1


def fired(alert: dict, price: float, at: float) -> bool:
    """A line alert fires when the side differs from the side at creation; a channel alert when the price is outside."""
    w = where(alert, price, at)
    return w != 0 if alert["kind"] in CHANNEL_KINDS else w != alert["side"]


def describe(a: dict) -> str:
    if a["type"] == "ind":
        return f"{a['symbol']} {a['rule']}"
    verb = "LEAVES" if a["kind"] in CHANNEL_KINDS else "CROSSES"
    return f"{a['symbol']} {verb} {a['kind']} {a['drawing_id'][:8]}"


# --- storage -----------------------------------------------------------------------------------------------------------

async def _all(db, prefix: str) -> list[dict]:
    async with db.execute("SELECT value FROM kv WHERE key LIKE ? ORDER BY key", (prefix + "%",)) as cur:
        return [orjson.loads(r[0]) for r in await cur.fetchall()]


async def _save(db, prefix: str, a: dict) -> None:
    await db.execute("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (prefix + a["id"], orjson.dumps(a)))
    await db.commit()


async def drawing_alerts(db) -> list[dict]:
    return await _all(db, DRAW)


async def _fire(app, prefix: str, a: dict, detail: str) -> None:
    """Marks the alert triggered (once), tells open tabs and sends it through DELIVERY."""
    from . import delivery

    db = app.state.userdata.db
    current = next((x for x in await _all(db, prefix) if x["id"] == a["id"]), None)
    if current is None or current["status"] != "active":
        return  # deleted, or another path fired it first: never twice
    current.update(status="triggered", triggered_at=time.time(), note=detail)
    await _save(db, prefix, current)
    hub = getattr(app.state, "hub", None)
    if hub is not None:
        hub.broadcast(["A", "smart", a["id"]])
    subject = f"ALERT {describe(current)}"
    delivery.spawn(app, "alert", a["id"], subject, f"{subject}\n{detail}\nChecked by the OpenTerm server.", {"kind": "smart"})


# --- indicator alerts: the periodic check ------------------------------------------------------------------------------

def _hook(app) -> None:
    jobs = app.state.jobs
    if "alerts.ind" in jobs.on_done:
        return

    async def on_done(job: dict, result: dict) -> dict:
        aid = job["params"]["alert_id"]
        db = app.state.userdata.db
        a = next((x for x in await _all(db, IND) if x["id"] == aid), None)
        row = (result.get("rows") or [{}])[0]
        if a is None or a["status"] != "active":
            return {"applied": False}
        vals = ", ".join(f"{k} {v:.2f}" for k, v in (row.get("values") or {}).items() if v is not None)
        a.update(checked=time.time(), bar=row.get("date"), values=row.get("values") or {}, note=row.get("note") or "")
        if row.get("matched"):
            if app.state.settings.openterm_fixtures:
                a["note"] = f"MATCHED ON {row.get('date')} BUT FIXTURE MODE: NOT FIRED"
            else:
                await _save(db, IND, a)
                await _fire(app, IND, a, f"{a['rule']} held on the daily bar of {row.get('date')} ({vals}).")
                return {"applied": True, "fired": True}
        await _save(db, IND, a)
        return {"applied": True, "fired": False}

    jobs.on_done["alerts.ind"] = on_done


async def check_one(app, a: dict) -> dict:
    """Fetch the symbol's daily bars, drop the forming bar, and submit the rule check (the hook applies the answer)."""
    from .api import bt_of
    from .bt import rules
    from .scanner.universe import range_for

    _hook(app)
    env = await app.state.service.history(a["symbol"], range_for(rules.max_period(rules.parse(a["rule"]))), "1d")
    bars = drop_forming(env["data"], time.time())
    sha, path = await asyncio.to_thread(bt_of(SimpleNamespace(app=app)).write_data, {"bars": {a["symbol"]: bars}})
    return await app.state.jobs.submit("alerts.ind", {"data_path": str(path), "data_sha": sha, "rule": a["rule"],
                                                      "alert_id": a["id"]}, internal=True)


async def check_all(app) -> None:
    """The scheduler's job: check every active indicator alert. One failure is noted on that alert, never stops the rest."""
    db = app.state.userdata.db
    for a in await _all(db, IND):
        if a["status"] != "active":
            continue
        try:
            await check_one(app, a)
        except Exception as e:  # noqa: BLE001 - shown in ALRT next to the alert
            a["note"] = f"CHECK FAILED: {redact(str(e))}"
            await _save(db, IND, a)


# --- drawing alerts: called by the alerts engine on every tick of a watched symbol ------------------------------------------

def check_tick(engine, alerts: list[dict], tick) -> None:
    """Synchronous and cheap (the hub calls it per tick). A hit is fired in the background; bad ticks are refused with a reason."""
    at = tick.time_ms / 1000
    for a in alerts:
        key = ("draw", a["id"])
        if key in engine._firing or not fired(a, tick.price, at):
            continue
        reason = engine.refusal(tick)
        if reason:
            engine._skip(f"draw:{a['id']}", describe(a), reason)
            continue
        engine._firing.add(key)
        engine._spawn(_fire_draw(engine, a, tick.price))


async def _fire_draw(engine, a: dict, price: float) -> None:
    try:
        verb = "left the channel" if a["kind"] in CHANNEL_KINDS else "crossed the line"
        await _fire(engine.app, DRAW, a, f"Price {price:g} {verb} ({a['kind']} drawn on GP).")
    finally:
        engine._firing.discard(("draw", a["id"]))
        if not engine._stopping:
            await engine.sync()


# --- routes ------------------------------------------------------------------------------------------------------------

class IndBody(BaseModel):
    symbol: str = Field(..., max_length=24)
    rule: str = Field(..., max_length=500)


class DrawBody(BaseModel):
    symbol: str = Field(..., max_length=24)
    n: int | None = Field(None, ge=1, le=200)  # the n-th alertable drawing in GP's object tree order; None = the newest


@router.get("")
async def list_all(request: Request):
    db = request.app.state.userdata.db
    return {"indicator": await _all(db, IND), "drawing": await _all(db, DRAW), "every_min": CHECK_EVERY_MIN}


@router.post("/indicator")
async def add_indicator(request: Request, body: IndBody):
    from .bt import rules

    try:
        rules.parse(body.rule)
    except rules.RuleError as e:
        return error_response(400, "bad_request", str(e))
    a = {"id": uuid.uuid4().hex[:8], "type": "ind", "symbol": resolve(body.symbol.strip().upper()), "rule": body.rule.upper(),
         "status": "active", "created": time.time(), "checked": None, "note": "FIRST CHECK RUNNING", "values": {}}
    await _save(request.app.state.userdata.db, IND, a)
    try:
        job = await check_one(request.app, a)
    except DataError as e:
        return error(e)
    return Orjson({"alert": a, "job": job})


@router.post("/drawing")
async def add_drawing(request: Request, body: DrawBody):
    sym = resolve(body.symbol.strip().upper())
    db = request.app.state.userdata.db
    async with db.execute("SELECT value FROM kv WHERE key=?", (f"drawings:{sym}",)) as cur:
        row = await cur.fetchone()
    doc = orjson.loads(row[0]) if row else {}
    usable = [d for d in (doc.get("drawings") or []) if d.get("kind") in LINE_KINDS | CHANNEL_KINDS and not d.get("hidden")]
    if not usable:
        return error_response(400, "bad_request", f"{sym} HAS NO TREND, RAY, XLINE, HLINE OR PCHAN DRAWING: DRAW ONE ON GP FIRST")
    pick = usable[-1] if body.n is None else (usable[body.n - 1] if body.n <= len(usable) else None)
    if pick is None:
        names = ", ".join(f"{i + 1} {d['kind']}" for i, d in enumerate(usable))
        return error_response(400, "bad_request", f"{sym} HAS {len(usable)} ALERTABLE DRAWINGS: {names}")
    env = (await request.app.state.service.quotes([sym])).get(sym) or {}
    price = (env.get("data") or {}).get("price")
    if not isinstance(price, int | float):
        return error_response(503, "unavailable", f"NO PRICE FOR {sym} NOW ({redact(str(env.get('error') or 'NO QUOTE'))}): THE SIDE OF THE LINE IS MEASURED FROM IT")
    a = {"id": uuid.uuid4().hex[:8], "type": "draw", "symbol": sym, "drawing_id": pick["id"], "kind": pick["kind"],
         "pts": pick["pts"], "status": "active", "created": time.time(), "note": f"CREATED AT {price:g}"}
    a["side"] = where(a, float(price), time.time())
    if a["kind"] in CHANNEL_KINDS and a["side"] != 0:
        return error_response(400, "bad_request", "THE PRICE IS ALREADY OUTSIDE THAT CHANNEL")
    await _save(db, DRAW, a)
    engine = getattr(request.app.state, "alerts_engine", None)
    if engine is not None:
        await engine.sync()
    return Orjson({"alert": a})


@router.delete("/{alert_id}")
async def delete(request: Request, alert_id: str):
    db = request.app.state.userdata.db
    for prefix in (IND, DRAW):
        await db.execute("DELETE FROM kv WHERE key=?", (prefix + alert_id,))
    await db.commit()
    engine = getattr(request.app.state, "alerts_engine", None)
    if engine is not None:
        await engine.sync()
    return {"deleted": alert_id}
