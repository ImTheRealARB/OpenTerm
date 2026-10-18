"""Phase 19 step 9, pure code for the non-US zero-key data: NSE cash-market bhavcopy day files and the AMFI NAV file.

No network and no database here. `providers/nse_archive.py` fetches and caches the day files, `providers/amfi.py` fetches NAVAll.txt;
both hand their bytes to these parsers. The two source formats are the ones recorded in backend/tests/fixtures (scripts/record_phase19.py 9).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..ranges import range_days

IST = timezone(timedelta(hours=5, minutes=30))
BHAVCOPY_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d}_F_0000.csv.zip"
SERIES = ("EQ", "BE")  # EQ = normal rolling settlement, BE = trade-for-trade. Every other series (bonds, ETFs, SME, ...) is left out.
MAX_SESSIONS = 250
MAX_WEEKDAYS = 275  # the walk back: 250 sessions plus the weekday holidays of a year, with slack
MAX_ZIP_BYTES = 25_000_000  # a day file is ~3.7k rows, ~0.9 MB of CSV; anything far above that is not one
SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")
NEEDED = ("TradDt", "TckrSymb", "SctySrs", "OpnPric", "HghPric", "LwPric", "ClsPric", "TtlTradgVol")


# --- NSE ------------------------------------------------------------------------------------------------------------
def nse_symbol(symbol: str) -> str | None:
    """`RELIANCE.NS` -> `RELIANCE`. `.BO` (BSE), indices (`^NSEI`) and anything not shaped like an NSE symbol -> None."""
    s = (symbol or "").strip().upper()
    if not s.endswith(".NS"):
        return None
    base = s[:-3]
    return base if SYMBOL_RE.match(base) else None


def bhavcopy_url(day: date) -> str:
    return BHAVCOPY_URL.format(d=day.strftime("%Y%m%d"))


def unzip_bhavcopy(content: bytes) -> str:
    """The CSV text inside the day zip. Anything else (an HTML bot-check page, a truncated file) is a ValueError."""
    try:
        z = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise ValueError("NOT A ZIP FILE (BOT CHECK OR ERROR PAGE?)") from e
    names = [i for i in z.infolist() if i.filename.lower().endswith(".csv")]
    if len(names) != 1:
        raise ValueError("EXPECTED ONE CSV IN THE BHAVCOPY ZIP")
    if names[0].file_size > MAX_ZIP_BYTES:
        raise ValueError("BHAVCOPY CSV IS FAR LARGER THAN A DAY FILE")
    return z.read(names[0]).decode("utf-8", "replace")


def parse_bhavcopy(text: str) -> tuple[date, dict[str, list[float | int]]]:
    """-> (trade date, {symbol: [open, high, low, close, volume]}) for series EQ and BE only. EQ wins when a symbol has both.

    Prices are the day's raw prices: NSE does not adjust them for splits or bonus issues afterwards."""
    reader = csv.reader(io.StringIO(text))
    try:
        head = next(reader)
    except StopIteration as e:
        raise ValueError("EMPTY BHAVCOPY") from e
    idx = {h.strip(): i for i, h in enumerate(head)}
    if any(n not in idx for n in NEEDED):
        raise ValueError("UNEXPECTED BHAVCOPY FORMAT: COLUMNS " + ",".join(n for n in NEEDED if n not in idx) + " MISSING")
    rows: dict[str, list[float | int]] = {}
    series: dict[str, str] = {}
    trade: date | None = None
    top = max(idx[n] for n in NEEDED)
    for r in reader:
        if len(r) <= top:
            continue
        ser = r[idx["SctySrs"]].strip()
        if ser not in SERIES:
            continue
        sym = r[idx["TckrSymb"]].strip()
        try:
            o, h, lo, c = (float(r[idx[k]]) for k in ("OpnPric", "HghPric", "LwPric", "ClsPric"))
            v = int(float(r[idx["TtlTradgVol"]] or 0))
            d = date.fromisoformat(r[idx["TradDt"]].strip())
        except ValueError:
            continue
        if not sym or c <= 0:
            continue
        if sym in series and not (series[sym] == "BE" and ser == "EQ"):
            continue
        series[sym] = ser
        rows[sym] = [o, h, lo, c, v]
        trade = trade or d
    if trade is None:
        raise ValueError("NO EQ/BE ROWS IN THE BHAVCOPY")
    return trade, rows


def session_ts(day: date) -> int:
    """Epoch seconds of 09:15 IST on `day` (the NSE open, which is what Yahoo stamps its daily bars with)."""
    return int(datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST).timestamp())


def walk_days(today: date, limit: int = MAX_WEEKDAYS) -> list[date]:
    """The weekdays from `today` back, newest first. Saturdays and Sundays are never requested."""
    out: list[date] = []
    d = today
    while len(out) < limit:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def plan(today: date, known: dict[date, bool]) -> tuple[list[date], list[date]]:
    """known[day] = True (a file with data) or False (a gap: the exchange was closed). -> (days with data, newest first, at most
    250; days not yet known inside the window, newest first). Gaps are skipped; they never count as sessions."""
    used: list[date] = []
    missing: list[date] = []
    for d in walk_days(today):
        k = known.get(d)
        if k:
            used.append(d)
            if len(used) >= MAX_SESSIONS:
                break
        elif k is None:
            missing.append(d)
    return used, missing


def label(files: int, partial: bool = False) -> str:
    """The text that names this source wherever the series is shown."""
    return f"NSE ARCHIVE, EOD, built from {files} daily file{'' if files == 1 else 's'}" + (" (INCOMPLETE)" if partial else "")


def is_partial(source_label: str) -> bool:
    return source_label.startswith("NSE ARCHIVE") and source_label.endswith("(INCOMPLETE)")


def build_columns(days: dict[date, dict[str, list[float | int]]], nsym: str, range_: str) -> dict[str, list] | None:
    """Columnar bars for one symbol from the loaded day files, oldest first, cut to `range_` counted back from the last bar."""
    t: list[int] = []
    o: list[float] = []
    h: list[float] = []
    lo: list[float] = []
    c: list[float] = []
    v: list[int] = []
    for d in sorted(days):
        row = days[d].get(nsym)
        if row is None:
            continue
        t.append(session_ts(d))
        o.append(row[0])
        h.append(row[1])
        lo.append(row[2])
        c.append(row[3])
        v.append(int(row[4]))
    if not t:
        return None
    keep = 0
    if range_ in ("1d", "5d"):
        keep = max(0, len(t) - (1 if range_ == "1d" else 5))
    elif range_ == "ytd":
        jan1 = session_ts(datetime.fromtimestamp(t[-1], IST).date().replace(month=1, day=1))
        keep = next((i for i, x in enumerate(t) if x >= jan1 - 86400), 0)
    elif range_ != "max":
        cutoff = t[-1] - range_days(range_) * 86400
        keep = next((i for i, x in enumerate(t) if x >= cutoff), 0)
    return {"t": t[keep:], "o": o[keep:], "h": h[keep:], "l": lo[keep:], "c": c[keep:], "v": v[keep:]}


# --- AMFI -------------------------------------------------------------------------------------------------------------
COLS = ["code", "isin", "isin_reinv", "name", "plan", "option", "nav", "date", "category", "amc"]
CATEGORY_START = ("open ended", "close ended", "closed ended", "interval fund")
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}
DEFAULT_LAYOUT = ("scheme code", "isin div payout/ isin growth", "isin div reinvestment", "scheme name", "plan", "option", "net asset value", "date")


def amfi_date(text: str) -> str | None:
    """`16-Oct-2026` -> `2026-10-16`; anything else -> None."""
    m = re.fullmatch(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", text.strip())
    if not m or m.group(2).lower() not in MONTHS:
        return None
    try:
        return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
    except ValueError:
        return None


def _is_category(line: str) -> bool:
    low = line.lower()
    return low.startswith(CATEGORY_START) or re.search(r"schemes?\s*\(", low) is not None


def _layout(header: list[str]) -> dict[str, int]:
    names = [h.strip().lower() for h in header]

    def find(*starts: str) -> int:
        return next((i for i, n in enumerate(names) if n.startswith(starts)), -1)

    return {"code": find("scheme code"), "isin": find("isin div payout"), "isin_reinv": find("isin div reinvestment"),
            "name": find("scheme name"), "plan": find("plan"), "option": find("option"), "nav": find("net asset value"), "date": find("date")}


def parse_amfi(text: str) -> dict[str, Any]:
    """NAVAll.txt -> {"cols", "cats", "amcs", "rows", "nav_date", "skipped"}.

    Lines are `;`-separated scheme rows, a category header (`Open Ended Schemes(...)`), an AMC header (`Axis Mutual Fund`) or blank
    (the file's blank lines hold one space). A row is skipped, and counted in `skipped`, when its NAV is `N.A.`/`-`/not a number or its
    date does not parse. ISINs of `-` become None. The column order comes from the file's own header line, so the older layout without
    Plan and Option columns parses too."""
    layout = _layout(list(DEFAULT_LAYOUT))
    cats: list[str] = []
    amcs: list[str] = []
    rows: list[list[Any]] = []
    cat = amc = -1
    skipped = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ";" not in line:
            if _is_category(line):
                if line not in cats:
                    cats.append(line)
                cat = cats.index(line)
            else:
                if line not in amcs:
                    amcs.append(line)
                amc = amcs.index(line)
            continue
        parts = [p.strip() for p in line.split(";")]
        if parts[0].lower().startswith("scheme code"):
            layout = _layout(parts)
            continue
        need = max(layout["code"], layout["name"], layout["nav"], layout["date"])
        if len(parts) <= need or not parts[layout["code"]].isdigit():
            skipped += 1
            continue
        try:
            nav = float(parts[layout["nav"]])
        except ValueError:
            skipped += 1
            continue
        when = amfi_date(parts[layout["date"]])
        if when is None:
            skipped += 1
            continue

        def cell(key: str, parts: list[str] = parts, layout: dict[str, int] = layout) -> str | None:
            i = layout[key]
            v = parts[i] if 0 <= i < len(parts) else ""
            return None if v in ("", "-") else v

        rows.append([parts[layout["code"]], cell("isin"), cell("isin_reinv"), parts[layout["name"]], cell("plan"), cell("option"), nav, when, cat, amc])
    return {"cols": COLS, "cats": cats, "amcs": amcs, "rows": rows, "nav_date": max((r[7] for r in rows), default=None), "skipped": skipped}


def search_amfi(table: dict[str, Any], query: str, limit: int = 50) -> tuple[list[dict[str, Any]], int]:
    """Scheme lookup by AMFI scheme code (digits), ISIN (`INF...`) or name words (every word must appear in the scheme or AMC name).
    -> (at most `limit` items, total matches). Direct plans and growth options sort first within a fund."""
    q = query.strip()
    if not q:
        return [], 0
    rows = table["rows"]
    up = q.upper()
    if re.fullmatch(r"\d{4,7}", q):
        hit = [r for r in rows if r[0] == q]
    elif re.fullmatch(r"IN[A-Z0-9]{10}", up):
        hit = [r for r in rows if up in (r[1], r[2])]
    else:
        words = q.lower().split()
        amcs = [a.lower() for a in table["amcs"]]
        hit = [r for r in rows if all(w in r[3].lower() or w in (amcs[r[9]] if r[9] >= 0 else "") for w in words)] if words else []
        first = words[0] if words else ""
        hit.sort(key=lambda r: (not r[3].lower().startswith(first), r[3].lower(), (r[4] or "").lower().startswith("regular"),
                                "growth" not in (r[5] or "").lower(), r[0]))
    out = [{"code": r[0], "isin": r[1], "isin_reinv": r[2], "name": r[3], "plan": r[4], "option": r[5], "nav": r[6], "date": r[7],
            "category": table["cats"][r[8]] if r[8] >= 0 else None, "amc": table["amcs"][r[9]] if r[9] >= 0 else None} for r in hit[:limit]]
    return out, len(hit)
