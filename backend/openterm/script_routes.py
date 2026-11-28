"""OpenTerm Script storage routes (Phase 25, spec docs/specs/PHASE_25.md section 4).

A script is plain text kept in the `scripts` table (migration 22). These routes only store, list and read it. They do NOT
run or compile the script: the editor checks it in the browser with the TypeScript engine, and the Python port (another
module) runs it on the server in part 2. The only thing read from the text here is the title in the first
`indicator("...")` line, so the list can show a readable name.

  GET    /api/scripts            -> {"scripts": [{name, title, updated_at}]}
  GET    /api/scripts/examples   -> {"examples": [{name, title, about, source}]}   (the starter library, read-only)
  GET    /api/scripts/{name}     -> {name, source, title, created_at, updated_at}
  PUT    /api/scripts/{name}     body {"source": "..."} -> {name, title, updated_at}
  DELETE /api/scripts/{name}     -> {"deleted": name}

  GET    /api/scripts/alerts     -> {"alerts": [{id, symbol, script, cond, created_at}]}   (live script alerts, see below)
  POST   /api/scripts/alerts     body {symbol, script, cond?} -> the new alert
  DELETE /api/scripts/alerts/{id} -> {"deleted": id}

Script alerts (`ALRT AAPL SCRIPT=NAME [COND="title"]`) are only STORED here (kv key `scriptalerts`: `{"v": 1, "next": n,
"alerts": [...]}`). They run in the browser while OpenTerm is open (`frontend/src/script/liveAlerts.ts`); nothing on the
server evaluates them yet (part 2). `cond` is the title of one of the script's `alertcondition(...)` calls, or null = fire
on the script's own `alert(...)` calls.

The `examples` route is declared BEFORE `{name}` on purpose: a path is matched in declaration order, so otherwise the word
"examples" would be taken as a script name.
"""

from __future__ import annotations

import asyncio
import functools
import re
import time
from pathlib import Path

import orjson
from fastapi import APIRouter, Request

from . import errkinds as K
from .http_util import error, json_object, user
from .idents import STORED_SYMBOL_RE
from .responses import OrjsonRoute
from .userdata import UserDataError, layout_name

router = APIRouter(prefix="/api/scripts", route_class=OrjsonRoute)

MAX_SOURCE = 20_000  # characters; the engines refuse longer sources too (spec 1.7)
MAX_ALERTS = 50  # live script alerts; each one keeps a socket subscription and a script run going in the browser
MAX_COND = 80  # characters of an alertcondition title
ALERTS_KEY = "scriptalerts"  # kv key of the whole alert list
# Names a script may not take: `GET /api/scripts/<name>` is matched after these fixed paths, so a script with one of these
# names could be saved but never read back.
RESERVED_NAMES = ("ALERTS", "EXAMPLES")
# `indicator("Title", ...)` or `indicator('Title', ...)`: group 2 is the title. Only the first match counts.
_TITLE_RE = re.compile(r"""\bindicator\(\s*(["'])(.*?)\1""")
EXAMPLES_DIR = Path(__file__).parent / "script" / "examples"


def title_of(source: str) -> str:
    """The title written in the script's `indicator(...)` line, or "" when there is none (a script that does not compile yet)."""
    m = _TITLE_RE.search(source)
    return m.group(2) if m else ""


def about_of(source: str) -> str:
    """The one-sentence `//` comment an example starts with, without the slashes."""
    for line in source.splitlines():
        line = line.strip()
        if not line:
            continue
        return line[2:].strip() if line.startswith("//") else ""
    return ""


@functools.cache
def _examples() -> tuple[dict, ...]:
    """The starter scripts, read once (the files never change while the server runs). Sorted by name so the list is stable."""
    out = []
    for path in sorted(EXAMPLES_DIR.glob("*.ots")):
        source = path.read_text(encoding="utf-8")
        out.append({"name": path.stem.upper(), "title": title_of(source), "about": about_of(source), "source": source})
    return tuple(out)


def _check_source(body: dict) -> str:
    source = body.get("source")
    if not isinstance(source, str) or not source.strip():
        raise UserDataError(K.BAD_REQUEST, "BODY NEEDS source: THE SCRIPT TEXT")
    if len(source) > MAX_SOURCE:
        raise UserDataError(K.TOO_LARGE, f"SCRIPT OVER {MAX_SOURCE:,} CHARACTERS")
    return source


@router.get("")
async def list_scripts(request: Request):
    async with user(request).db.execute("SELECT name, source, updated_at FROM scripts ORDER BY name") as cur:
        rows = await cur.fetchall()
    return {"scripts": [{"name": n, "title": title_of(s), "updated_at": u} for n, s, u in rows]}


@router.get("/examples")
async def examples():
    return {"examples": list(_examples())}


# --- live script alerts (declared BEFORE `/{name}`: see the module docstring) ---------------------------------------------


async def _read_alerts(db) -> dict:
    """The stored document, or an empty one. A damaged value is an error, never silently replaced (the user would lose alerts)."""
    async with db.execute("SELECT value FROM kv WHERE key=?", (ALERTS_KEY,)) as cur:
        row = await cur.fetchone()
    if not row:
        return {"v": 1, "next": 1, "alerts": []}
    return orjson.loads(row[0])


async def _write_alerts(db, doc: dict) -> None:
    await db.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (ALERTS_KEY, orjson.dumps(doc)),
    )
    await db.commit()


def _alerts_lock(request: Request) -> asyncio.Lock:
    """One lock per app: the list is read, changed and written back, and two requests must not interleave doing that."""
    state = request.app.state
    lock = getattr(state, "script_alerts_lock", None)
    if lock is None:
        lock = state.script_alerts_lock = asyncio.Lock()
    return lock


def _check_alert(body: dict) -> tuple[str, str, str | None]:
    """symbol, script name and condition title of a new alert, or UserDataError saying which part is wrong."""
    symbol = body.get("symbol")
    if not isinstance(symbol, str) or not STORED_SYMBOL_RE.match(symbol.strip().upper()):
        raise UserDataError(K.BAD_REQUEST, "BODY NEEDS symbol: THE SECURITY (A-Z 0-9 ^ = . & -, UP TO 24)")
    script = body.get("script")
    if not isinstance(script, str):
        raise UserDataError(K.BAD_REQUEST, "BODY NEEDS script: THE SCRIPT NAME")
    name = layout_name(script, "SCRIPT")
    cond = body.get("cond")
    if cond is not None:
        # A title is the text of an alertcondition(...) call: printable, one line, short.
        if not isinstance(cond, str) or not cond.strip() or len(cond.strip()) > MAX_COND or not cond.isprintable():
            raise UserDataError(K.BAD_REQUEST, f"cond MUST BE A CONDITION TITLE OF 1-{MAX_COND} PRINTABLE CHARACTERS (OR null)")
        cond = cond.strip()
    return symbol.strip().upper(), name, cond


@router.get("/alerts")
async def list_script_alerts(request: Request):
    return {"alerts": (await _read_alerts(user(request).db))["alerts"]}


@router.post("/alerts")
async def add_script_alert(request: Request):
    try:
        symbol, script, cond = _check_alert(await json_object(request))
    except UserDataError as e:
        return error(e)
    db = user(request).db
    async with db.execute("SELECT 1 FROM scripts WHERE name=?", (script,)) as cur:
        if await cur.fetchone() is None:
            return error(UserDataError(K.NOT_FOUND, f"NO SCRIPT {script}"))
    async with _alerts_lock(request):
        doc = await _read_alerts(db)
        alerts = doc["alerts"]
        if any(a["symbol"] == symbol and a["script"] == script and a["cond"] == cond for a in alerts):
            return error(UserDataError(K.BAD_REQUEST, "THAT SCRIPT ALERT ALREADY EXISTS"))
        if len(alerts) >= MAX_ALERTS:
            return error(UserDataError(K.TOO_LARGE, f"AT MOST {MAX_ALERTS} SCRIPT ALERTS: DELETE ONE FIRST (ALRT DEL SC<ID>)"))
        alert = {"id": doc["next"], "symbol": symbol, "script": script, "cond": cond, "created_at": time.time()}
        alerts.append(alert)
        doc["next"] += 1  # ids are never reused, so a stale ALRT DEL can not delete a newer alert
        await _write_alerts(db, doc)
    return alert


@router.delete("/alerts/{alert_id}")
async def delete_script_alert(request: Request, alert_id: int):
    db = user(request).db
    async with _alerts_lock(request):
        doc = await _read_alerts(db)
        kept = [a for a in doc["alerts"] if a["id"] != alert_id]
        if len(kept) == len(doc["alerts"]):
            return error(UserDataError(K.NOT_FOUND, f"NO SCRIPT ALERT SC{alert_id}"))
        doc["alerts"] = kept
        await _write_alerts(db, doc)
    return {"deleted": alert_id}


@router.get("/{name}")
async def get_script(request: Request, name: str):
    try:
        key = layout_name(name, "SCRIPT")
    except UserDataError as e:
        return error(e)
    async with user(request).db.execute("SELECT source, created_at, updated_at FROM scripts WHERE name=?", (key,)) as cur:
        row = await cur.fetchone()
    if row is None:
        return error(UserDataError(K.NOT_FOUND, f"NO SCRIPT {key}"))
    return {"name": key, "source": row[0], "title": title_of(row[0]), "created_at": row[1], "updated_at": row[2]}


@router.put("/{name}")
async def put_script(request: Request, name: str):
    try:
        key = layout_name(name, "SCRIPT")
        if key in RESERVED_NAMES:
            raise UserDataError(K.BAD_REQUEST, f"SCRIPT NAME {key} IS TAKEN BY OPENTERM: PICK ANOTHER")
        source = _check_source(await json_object(request))
    except UserDataError as e:
        return error(e)
    now = time.time()
    db = user(request).db
    # Upsert: a new name is inserted, an existing one keeps its created_at and gets the new text.
    await db.execute(
        "INSERT INTO scripts (name, source, created_at, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET source=excluded.source, updated_at=excluded.updated_at",
        (key, source, now, now),
    )
    await db.commit()
    return {"name": key, "title": title_of(source), "updated_at": now}


@router.delete("/{name}")
async def delete_script(request: Request, name: str):
    try:
        key = layout_name(name, "SCRIPT")
    except UserDataError as e:
        return error(e)
    db = user(request).db
    cur = await db.execute("DELETE FROM scripts WHERE name=?", (key,))
    await db.commit()
    if cur.rowcount == 0:
        return error(UserDataError(K.NOT_FOUND, f"NO SCRIPT {key}"))
    return {"deleted": key}
