"""User settings (SETTINGS panel): one versioned JSON document in the `kv` table, key `settings`.

The frontend owns the defaults and applies settings from its localStorage mirror at cold start; this module only
validates and persists. Every field is optional (a missing field means "use the default"); unknown fields are
rejected so typos never get stored silently.
"""

import re
import time

import aiosqlite
import orjson

from .userdata import UserDataError

KEY = "settings"
VERSION = 1
MAX_BYTES = 16_000

MODES = ("terminal", "gui")  # which shell the frontend shows; a saved object with no `mode` means "terminal"
THEMES = ("amber", "green", "white", "light")
CHART_RANGES = ("1D", "5D", "1M", "3M", "6M", "YTD", "1Y", "2Y", "5Y", "10Y", "MAX")
CHART_TYPES = ("CANDLE", "OHLC", "LINE", "AREA")
THOUSANDS = (",", ".", " ", "'", "")
DECIMALS = (".", ",")
# Poll intervals in seconds: (min, max). The floors keep free providers inside their rate limits.
POLL_BOUNDS = {"news": (30, 600), "movers": (30, 600), "crypto": (15, 600), "sources": (5, 120)}
MAX_CLOCKS = 3
ZONE_RE = re.compile(r"^(LOCAL|UTC|[A-Za-z]+(?:/[A-Za-z0-9_+-]+){1,2})\Z")  # \Z, not `$`: no trailing newline
ACTION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,39}\Z")
CHORD_RE = re.compile(r"^(?:(?:Ctrl|Alt|Shift)\+){0,3}[^\s+]{1,12}\Z|^(?:(?:Ctrl|Alt|Shift)\+){1,3}\+\Z")
MAX_ACTIONS = 64
MAX_CHORDS = 4


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


AI_PROVIDERS = ("openrouter", "openai", "anthropic", "ollama")
AI_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/\-]{1,80}\Z")


def _ai(raw) -> dict:
    if not isinstance(raw, dict):
        raise _bad("ai MUST BE AN OBJECT")
    extra = sorted(set(raw) - {"model", "visionModel", "provider"})
    if extra:
        raise _bad(f"ai KEYS: model visionModel provider (NOT {extra[0][:20]!r})")
    out = {}
    for k in ("model", "visionModel"):
        if k in raw:
            if not isinstance(raw[k], str) or not AI_MODEL_RE.match(raw[k]):
                raise _bad(f"ai.{k} MUST BE A MODEL ID LIKE vendor/name")
            out[k] = raw[k]
    if "provider" in raw:
        out["provider"] = _choice(raw["provider"], AI_PROVIDERS, "ai.provider")
    return out


def _vim(raw) -> bool:
    if not isinstance(raw, bool):
        raise _bad("vim MUST BE true OR false")
    return raw


FIELDS = {
    "mode": lambda v: _choice(v, MODES, "mode"),
    "theme": lambda v: _choice(v, THEMES, "theme"),
    "vim": _vim,
    "numberFormat": _number_format,
    "clocks": _clocks,
    "chart": _chart,
    "poll": _poll,
    "keys": _keys,
    "ai": _ai,
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


class SettingsStore:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get(self) -> dict:
        async with self.db.execute("SELECT value FROM kv WHERE key=?", (KEY,)) as cur:
            row = await cur.fetchone()
        if not row:
            return {"version": VERSION, "settings": None, "updated_at": None}
        doc = migrate(orjson.loads(row[0]))
        return {"version": VERSION, "settings": doc.get("settings") or {}, "updated_at": doc.get("updated_at")}

    async def put(self, settings, version=VERSION) -> dict:
        clean = validate(settings, version)
        now = time.time()
        doc = {"version": VERSION, "settings": clean, "updated_at": now}
        await self.db.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (KEY, orjson.dumps(doc)),
        )
        await self.db.commit()
        return doc
