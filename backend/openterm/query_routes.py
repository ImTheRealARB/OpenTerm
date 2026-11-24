"""Phase 31 routes.

`/api/query?q=...`         QRY: the table payload the QRY panel draws (and the SDK reads)
`/api/query/fields?q=...`  FLD: the field catalog, searched by words
`/api/xl/...`              the Excel bridge: plain text for Excel's WEBSERVICE() and CSV for Power Query / Data > From Web.
                           GET only and LOOPBACK ONLY (Excel runs on this machine; in remote mode the bridge is off), so a
                           spreadsheet can read quotes but nothing can write through it.
"""

import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response

from .errors import DataError
from .http_util import data_errors, loopback, svc
from .query import engine
from .query import lang as L
from .responses import OrjsonRoute
from .symbols import resolve

router = APIRouter(route_class=OrjsonRoute)


@router.get("/api/query")
@data_errors
async def query(request: Request, q: str = Query(..., min_length=3, max_length=600)):
    """QRY: run one query (snapshot or DATES series)."""
    return await engine.run(request.app, q)


@router.get("/api/query/fields")
@data_errors
async def fields(q: str = Query("", max_length=80)):
    """FLD: the field catalog (every field names its source, unit, update frequency and key)."""
    return engine.fields_payload(q)


# --- Excel bridge ---------------------------------------------------------------------------------------------------------------


def _local(request: Request) -> None:
    if not loopback(request):
        raise HTTPException(403, "THE EXCEL BRIDGE ANSWERS ONLY ON THIS COMPUTER (LOOPBACK)")


def _text(v: object) -> PlainTextResponse:
    """One cell for WEBSERVICE(): a bare number with a dot decimal (wrap it in VALUE() in Excel), or the text. Empty = no value."""
    if v is None:
        return PlainTextResponse("")
    if isinstance(v, float):
        return PlainTextResponse(repr(round(v, 10)))
    return PlainTextResponse(str(v))


def _csv(rows: list[list[object]], name: str) -> Response:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'inline; filename="{name}.csv"'})


@router.get("/api/xl/last")
@data_errors
async def xl_last(request: Request, s: str = Query(..., min_length=1, max_length=24)):
    """=VALUE(WEBSERVICE("http://127.0.0.1:8000/api/xl/last?s=AAPL")): the last price as plain text."""
    _local(request)
    sym = resolve(s)
    got = (await svc(request).quotes([sym])).get(sym) or {}
    q = got.get("data")
    q = q.model_dump() if hasattr(q, "model_dump") else q
    if not isinstance(q, dict) or q.get("price") is None:
        raise DataError("not_found", f"NO QUOTE FOR {sym}")
    return _text(float(q["price"]))


@router.get("/api/xl/field")
@data_errors
async def xl_field(request: Request, s: str = Query(..., min_length=1, max_length=24), f: str = Query(..., min_length=1, max_length=20)):
    """=WEBSERVICE(".../api/xl/field?s=AAPL&f=pe"): one snapshot field (FLD lists them) as plain text."""
    _local(request)
    name = f.strip().lower()
    if name not in L.FIELDS or L.FIELDS[name].group not in L.SNAPSHOT_GROUPS:
        raise DataError("bad_request", f"FIELD {name[:20].upper()}: USE A SNAPSHOT FIELD FROM FLD")
    env = await engine.run(request.app, f"QRY {name} FOR {resolve(s)}")
    rows = env["data"]["sections"][0]["rows"]
    return _text(rows[0].get(name) if rows else None)


@router.get("/api/xl/history.csv")
@data_errors
async def xl_history(request: Request, s: str = Query(..., min_length=1, max_length=24), range: str = Query("1Y", max_length=4),
                     interval: str = Query("1d", max_length=4)):
    """Power Query / Data > From Web: date, open, high, low, close, adjusted close, volume."""
    _local(request)
    d = (await svc(request).history(s, range, interval))["data"]
    d = d.model_dump() if hasattr(d, "model_dump") else d
    adj = d.get("adj") or [None] * len(d["t"])
    rows: list[list[object]] = [["date", "open", "high", "low", "close", "adj_close", "volume"]]
    for i, t in enumerate(d["t"]):
        rows.append([datetime.fromtimestamp(t, UTC).isoformat(timespec="minutes").replace("+00:00", "Z"),
                     d["o"][i], d["h"][i], d["l"][i], d["c"][i], adj[i], d["v"][i]])
    return _csv(rows, f"{resolve(s)}_{range}_{interval}")


@router.get("/api/xl/query.csv")
@data_errors
async def xl_query(request: Request, q: str = Query(..., min_length=3, max_length=600)):
    """Any QRY as CSV (the same rows the QRY panel shows)."""
    _local(request)
    data = (await engine.run(request.app, q))["data"]
    sec = data["sections"][0]
    cols = sec["columns"]
    rows: list[list[object]] = [[c["title"] for c in cols]]
    rows += [[r.get(c["key"]) for c in cols] for r in sec["rows"]]
    return _csv(rows, "openterm_query")


# --- NB: local JupyterLab ------------------------------------------------------------------------------------------------------


@router.get("/api/nb")
@data_errors
async def nb_status(request: Request):
    """NB: is the notebook server running; the URL (with its token) only to this computer."""
    return {"data": request.app.state.nb.status(loopback(request))}


@router.post("/api/nb/start")
@data_errors
async def nb_start(request: Request):
    """Start JupyterLab (loopback only: it runs Python on this computer)."""
    _local(request)
    from .query.notebook import NotebookError

    try:
        return {"data": request.app.state.nb.start()}
    except NotebookError as e:
        raise DataError("unavailable", str(e)) from e


@router.post("/api/nb/stop")
@data_errors
async def nb_stop(request: Request):
    _local(request)
    return {"data": request.app.state.nb.stop()}
