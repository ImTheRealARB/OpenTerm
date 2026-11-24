"""User settings (SETTINGS panel): one versioned JSON document in the `kv` table, key `settings`.

The frontend owns the defaults and applies settings from its localStorage mirror at cold start; this module only
validates and persists. Every field is optional (a missing field means "use the default"); unknown fields are
rejected so typos never get stored silently.

Sync between devices is a per-field merge, not "newest whole document wins": the document carries `field_times`
({top-level field: epoch seconds of its last change}) and a PUT keeps, per field, whichever side changed it later. So two
browsers editing different fields both keep their edit. A field's time also covers "reset to default" (the field is
absent from `settings` but has a time: a tombstone), so a reset on one device is not undone by a stale copy on another.
"""

import asyncio
import math
import re
import time
import weakref

import aiosqlite
import orjson

from .userdata import UserDataError

KEY = "settings"
VERSION = 1
MAX_BYTES = 16_000

MODES = ("terminal", "gui")  # which shell the frontend shows; a saved object with no `mode` means "terminal"
STARTUPS = ("home", "layout")  # what a new session opens: the HOME page, or the saved workspace
ROW_NUMBERS = ("auto", "on", "off")  # gutter of 1) 2) 3) on the quote grids; auto = on in Terminal, off in GUI
TAPE_MAX = 30  # ticker tape symbols
TAPE_SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^&]{0,19}\Z")  # same rule as frontend settings/schema.ts
THEMES = ("amber", "green", "white", "light")
CHART_RANGES = ("1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "2Y", "5Y", "10Y", "MAX")
# Same list as frontend chart/chartTypes.ts (test_ts_mirrors.py keeps them equal): SETTINGS CHART HEIKIN used to be refused here.
CHART_TYPES = (
    "CANDLE", "HOLLOW", "OHLC", "LINE", "AREA", "BASELINE", "HEIKIN",
    "RENKO", "KAGI", "PNF", "LINEBREAK", "RANGE",
    "COLUMNS", "HIGHLOW", "STEP", "VOLCANDLE",
)
THOUSANDS = (",", ".", " ", "'", "")
DECIMALS = (".", ",")
# Poll intervals in seconds: (min, max). The floors keep free providers inside their rate limits.
POLL_BOUNDS = {"news": (30, 600), "movers": (30, 600), "crypto": (15, 600), "sources": (5, 120)}
MAX_CLOCKS = 3
ZONE_RE = re.compile(r"^(LOCAL|UTC|[A-Za-z]+(?:/[A-Za-z0-9_+-]+){1,2})\Z")  # \Z, not `$`: no trailing newline
FONT_RE = re.compile(r"^[\w][\w .+-]{0,59}\Z")  # \w = letters, digits, underscore (any script); \Z: no trailing newline
ACTION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,39}\Z")
CHORD_RE = re.compile(r"^(?:(?:Ctrl|Alt|Shift)\+){0,3}[^\s+]{1,12}\Z|^(?:(?:Ctrl|Alt|Shift)\+){1,3}\+\Z")
MAX_ACTIONS = 64
MAX_CHORDS = 4
# A field time may run ahead of this server's clock by at most this much (a device with a wrong clock would otherwise win
# every field for good). Beyond it the PUT is refused with a message, so the owner learns about the bad clock.
MAX_CLOCK_SKEW_S = 86_400


def _bad(msg: str) -> UserDataError:
    return UserDataError("bad_request", f"SETTINGS: {msg}")


def _choice(value, allowed: tuple, field: str):
    if value not in allowed:
        raise _bad(f"{field} MUST BE ONE OF {' '.join(repr(a) for a in allowed)}")
    return value


def _number_format(raw) -> dict:
    if not isinstance(raw, dict) or set(raw) - {"thousands", "decimal"}:
        raise _bad("numberFormat NEEDS thousands AND/OR decimal")
    out = {}
    if "thousands" in raw:
        out["thousands"] = _choice(raw["thousands"], THOUSANDS, "numberFormat.thousands")
    if "decimal" in raw:
        out["decimal"] = _choice(raw["decimal"], DECIMALS, "numberFormat.decimal")
    if out.get("thousands", ",") == out.get("decimal", "."):
        raise _bad("THOUSANDS SEPARATOR AND DECIMAL MARK MUST DIFFER")
    return out


def _clocks(raw) -> list[str]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CLOCKS:
        raise _bad(f"clocks MUST BE A LIST OF 1-{MAX_CLOCKS} TIME ZONES")
    for z in raw:
        if not isinstance(z, str) or not ZONE_RE.match(z):
            raise _bad(f"BAD TIME ZONE {str(z)[:40]!r} (USE LOCAL, UTC OR AREA/CITY)")
    return list(raw)


def _chart(raw) -> dict:
    if not isinstance(raw, dict) or set(raw) - {"range", "type"}:
        raise _bad("chart NEEDS range AND/OR type")
    out = {}
    if "range" in raw:
        out["range"] = _choice(raw["range"], CHART_RANGES, "chart.range")
    if "type" in raw:
        out["type"] = _choice(raw["type"], CHART_TYPES, "chart.type")
    return out


def _poll(raw) -> dict:
    if not isinstance(raw, dict) or set(raw) - set(POLL_BOUNDS):
        raise _bad(f"poll KEYS: {' '.join(POLL_BOUNDS)}")
    out = {}
    for k, v in raw.items():
        lo, hi = POLL_BOUNDS[k]
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise _bad(f"poll.{k} MUST BE {lo}-{hi} SECONDS")
        out[k] = v
    return out


def _keys(raw) -> dict:
    if not isinstance(raw, dict) or len(raw) > MAX_ACTIONS:
        raise _bad(f"keys MUST MAP UP TO {MAX_ACTIONS} ACTIONS TO CHORD LISTS")
    out = {}
    for action, chords in raw.items():
        if not ACTION_RE.match(action):
            raise _bad(f"BAD ACTION NAME {action[:40]!r}")
        if not isinstance(chords, list) or len(chords) > MAX_CHORDS:
            raise _bad(f"keys.{action} MUST BE A LIST OF UP TO {MAX_CHORDS} CHORDS")
        for c in chords:
            if not isinstance(c, str) or not CHORD_RE.match(c):
                raise _bad(f"BAD CHORD {str(c)[:32]!r} FOR {action}")
        out[action] = list(dict.fromkeys(chords))
    return out


AI_PROVIDERS = ("openrouter", "openai", "anthropic", "opencodego", "deepseek", "groq", "mistral", "xai", "together", "fireworks",
                "gemini", "ollama")  # keep equal to llm.client.PROVIDERS (not imported: the gateway loads on first use)
AI_WEB_PROVIDERS = ("brave", "tavily", "searxng")  # keep equal to ai.web.PROVIDERS
AI_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/\-]{1,80}\Z")


def _ai(raw) -> dict:
    if not isinstance(raw, dict):
        raise _bad("ai MUST BE AN OBJECT")
    extra = sorted(set(raw) - {"model", "visionModel", "provider", "storeText", "web", "webProvider"})
    if extra:
        raise _bad(f"ai KEYS: model visionModel provider storeText web webProvider (NOT {extra[0][:20]!r})")
    out = {}
    for k in ("model", "visionModel"):
        if k in raw:
            if not isinstance(raw[k], str) or not AI_MODEL_RE.match(raw[k]):
                raise _bad(f"ai.{k} MUST BE A MODEL ID LIKE vendor/name")
            out[k] = raw[k]
    if "provider" in raw:
        out["provider"] = _choice(raw["provider"], AI_PROVIDERS, "ai.provider")
    if "storeText" in raw:
        if not isinstance(raw["storeText"], bool):
            raise _bad("ai.storeText MUST BE true OR false")
        out["storeText"] = raw["storeText"]
    if "web" in raw:  # opt-in web access for the AI (off unless true); see ai/web.py
        if not isinstance(raw["web"], bool):
            raise _bad("ai.web MUST BE true OR false")
        out["web"] = raw["web"]
    if "webProvider" in raw:
        out["webProvider"] = _choice(raw["webProvider"], AI_WEB_PROVIDERS, "ai.webProvider")
    return out


def _font(raw) -> str:
    """Name of an installed font ("" = built-in). Same rule as frontend/src/settings/font.ts."""
    if not isinstance(raw, str) or (raw and not FONT_RE.match(raw)):
        raise _bad("font MUST BE AN INSTALLED FONT NAME (LETTERS, DIGITS, SPACES AND . _ + -, 60 MAX)")
    return raw


def _tape(raw) -> bool:
    if not isinstance(raw, bool):
        raise _bad("tape MUST BE true OR false")
    return raw


def _tape_symbols(raw) -> list[str]:
    if not isinstance(raw, list) or len(raw) > TAPE_MAX:
        raise _bad(f"tapeSymbols MUST BE A LIST OF AT MOST {TAPE_MAX} SYMBOLS")
    for sym in raw:
        if not isinstance(sym, str) or not TAPE_SYMBOL_RE.match(sym):
            raise _bad(f"BAD TAPE SYMBOL {str(sym)[:40]!r}")
    if len(set(raw)) != len(raw):
        raise _bad("tapeSymbols HAS A DUPLICATE")
    return list(raw)


def _vim(raw) -> bool:
    if not isinstance(raw, bool):
        raise _bad("vim MUST BE true OR false")
    return raw


def _sources(raw) -> dict:
    """{capability: provider}: the source tried first for that kind of data (SETTINGS SOURCE HISTORY NASDAQ). The default order backs it up."""
    from .pin import NAME_RE
    from .providers.hierarchy import DEFAULT_ORDER

    if not isinstance(raw, dict) or len(raw) > len(DEFAULT_ORDER):
        raise _bad("sources MUST MAP CAPABILITIES TO SOURCE NAMES")
    out = {}
    for cap, name in raw.items():
        if cap not in DEFAULT_ORDER:
            raise _bad(f"UNKNOWN CAPABILITY {str(cap)[:40]!r} IN sources")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise _bad(f"sources.{cap} MUST BE A SOURCE NAME LIKE nasdaq")
        out[cap] = name
    return out


def source_prefs(settings: dict | None) -> dict[str, str]:
    """The `sources` preferences of a stored settings object, for the router."""
    return dict((settings or {}).get("sources") or {})


FIELDS = {
    "sources": _sources,
    "mode": lambda v: _choice(v, MODES, "mode"),
    "theme": lambda v: _choice(v, THEMES, "theme"),
    "font": _font,
    "vim": _vim,
    "numberFormat": _number_format,
    "clocks": _clocks,
    "chart": _chart,
    "poll": _poll,
    "keys": _keys,
    "ai": _ai,
    "startup": lambda v: _choice(v, STARTUPS, "startup"),
    "rowNumbers": lambda v: _choice(v, ROW_NUMBERS, "rowNumbers"),
    "tape": _tape,
    "tapeSymbols": _tape_symbols,
}


def validate(raw, version=VERSION) -> dict:
    """Returns the normalized settings object or raises UserDataError(bad_request)."""
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _bad("version MUST BE A POSITIVE INTEGER")
    if version > VERSION:
        raise _bad(f"VERSION {version} IS NEWER THAN THIS SERVER ({VERSION})")
    if not isinstance(raw, dict):
        raise _bad("settings MUST BE A JSON OBJECT")
    unknown = sorted(set(raw) - set(FIELDS))
    if unknown:
        raise _bad(f"UNKNOWN FIELD {unknown[0][:40]!r}")
    out = {k: FIELDS[k](v) for k, v in raw.items()}
    if len(orjson.dumps(out)) > MAX_BYTES:
        raise UserDataError("too_large", f"SETTINGS OVER {MAX_BYTES // 1000} KB")
    return out


def migrate(doc: dict) -> dict:
    """Upgrades a stored document to VERSION. Only version 1 exists so far."""
    return doc


def validate_times(raw, settings: dict, now: float) -> dict[str, float]:
    """Checks the `field_times` of a PUT. Keys are settings fields; values are finite epoch seconds, not in the far future.

    Every field present in `settings` must have a time (it may be 0 = "never set"); extra times are tombstones for fields
    the client reset to their default, which is why `settings` may lack them.
    """
    if not isinstance(raw, dict):
        raise _bad("field_times MUST BE AN OBJECT {field: epoch seconds}")
    unknown = sorted(set(raw) - set(FIELDS))
    if unknown:
        raise _bad(f"UNKNOWN FIELD {unknown[0][:40]!r} IN field_times")
    out: dict[str, float] = {}
    for k, v in raw.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
            raise _bad(f"field_times.{k} MUST BE A TIME IN EPOCH SECONDS")
        if v > now + MAX_CLOCK_SKEW_S:
            raise _bad(f"field_times.{k} IS IN THE FUTURE (CHECK THIS DEVICE'S CLOCK)")
        out[k] = float(v)
    missing = sorted(set(settings) - set(out))
    if missing:
        raise _bad(f"field_times HAS NO TIME FOR {missing[0]!r}")
    return out


def effective_times(doc: dict) -> dict[str, float]:
    """The change time of every field of a stored document (0 = never set).

    A legacy document (saved before per-field times existed) has no `field_times`: all its fields, including the ones left
    out because they were at their default, count as changed when the document was saved. That is what whole-document
    last-write-wins meant, so old data behaves as before.
    """
    stored = doc.get("field_times")
    if stored is None:
        at = doc.get("updated_at") or 0
        return {f: float(at) for f in FIELDS}
    return {f: float(stored.get(f, 0)) for f in FIELDS}


def merge(cur_settings: dict, cur_times: dict[str, float], new_settings: dict, new_times: dict[str, float]):
    """Per field, the later change wins; the stored copy keeps a tie (so a never-set field, time 0, never overwrites anything).

    `new_*` is the incoming PUT, `cur_*` the stored document. A field the incoming side has no time for is untouched.
    Returns (settings, times) with times only for fields that were ever set.
    """
    settings: dict = {}
    times: dict[str, float] = {}
    for f in FIELDS:
        incoming_wins = new_times.get(f, 0) > cur_times.get(f, 0)
        src_settings, src_times = (new_settings, new_times) if incoming_wins else (cur_settings, cur_times)
        if f in src_settings:  # absent on the winning side = reset to default
            settings[f] = src_settings[f]
        if src_times.get(f, 0) > 0:
            times[f] = src_times[f]
    return settings, times


# One lock per database connection: put() reads the stored document, merges and writes it back, and two concurrent PUTs
# (two devices) must not interleave there or the later write would silently drop the earlier one's fields.
# SettingsStore is built per request, so the lock cannot live on it. Weak keys: a closed connection takes its lock with it.
_LOCKS: "weakref.WeakKeyDictionary[aiosqlite.Connection, asyncio.Lock]" = weakref.WeakKeyDictionary()


class SettingsStore:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def _load(self) -> dict | None:
        async with self.db.execute("SELECT value FROM kv WHERE key=?", (KEY,)) as cur:
            row = await cur.fetchone()
        return migrate(orjson.loads(row[0])) if row else None

    async def get(self) -> dict:
        doc = await self._load()
        if doc is None:
            return {"version": VERSION, "settings": None, "updated_at": None, "field_times": {}}
        return {
            "version": VERSION,
            "settings": doc.get("settings") or {},
            "updated_at": doc.get("updated_at"),
            "field_times": effective_times(doc),
        }

    async def put(self, settings, version=VERSION, field_times=None) -> dict:
        """Stores settings and returns the document that is now stored (callers must adopt it: it may hold fields the
        other side changed later).

        `field_times` given: a per-field merge into the stored document (see the module docstring).
        `field_times` None (an older client): the whole document is replaced, as before; every field counts as changed now.
        """
        clean = validate(settings, version)
        now = time.time()
        lock = _LOCKS.setdefault(self.db, asyncio.Lock())
        async with lock:
            if field_times is None:
                merged, times = clean, {f: now for f in FIELDS}
            else:
                incoming = validate_times(field_times, clean, now)
                cur = await self._load()
                cur_settings, cur_times = (cur.get("settings") or {}, effective_times(cur)) if cur else ({}, {})
                merged, times = merge(cur_settings, cur_times, clean, incoming)
            doc = {"version": VERSION, "settings": merged, "updated_at": now, "field_times": times}
            await self.db.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (KEY, orjson.dumps(doc)),
            )
            await self.db.commit()
        return doc
