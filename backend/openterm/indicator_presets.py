"""Named indicator presets for the chart: one kv row (`ind_presets`) holding name -> {name, items, updated_at}.

An item is a library indicator (`id` + numeric `params`) or a formula (`formula` text); formulas are only stored here and
evaluated in the browser's indicator worker, never on the server. Strict validation: unknown fields are refused.
"""

import math
import re
import time

import aiosqlite
import orjson

from .userdata import UserDataError

KEY = "ind_presets"
MAX_PRESETS = 50
MAX_ITEMS = 20
MAX_FORMULA = 500
MAX_LABEL = 40
MAX_PARAMS = 12
NAME_MAX = 40
ID_RE = re.compile(r"^[A-Z0-9_]{1,24}$")


def _bad(msg: str) -> UserDataError:
    return UserDataError("bad_request", f"PRESETS: {msg}")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def clean_name(raw) -> str:
    if not isinstance(raw, str):
        raise _bad("NAME MUST BE TEXT")
    name = raw.strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise _bad(f"NAME MUST BE 1-{NAME_MAX} CHARACTERS")
    if any(ord(ch) < 32 for ch in name):
        raise _bad("NAME HAS CONTROL CHARACTERS")
    return name


def validate_items(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise _bad("items MUST BE A LIST")
    if len(raw) > MAX_ITEMS:
        raise UserDataError("too_large", f"PRESETS: OVER {MAX_ITEMS} ITEMS")
    out: list[dict] = []
    for it in raw:
        if not isinstance(it, dict) or not set(it) <= {"id", "formula", "params", "label"}:
            raise _bad("EACH ITEM NEEDS id OR formula, plus optional params AND label")
        if ("id" in it) == ("formula" in it):
            raise _bad("EACH ITEM NEEDS EXACTLY ONE OF id OR formula")
        clean: dict = {}
        if "id" in it:
            if not isinstance(it["id"], str) or not ID_RE.match(it["id"]):
                raise _bad("id MUST BE 1-24 CHARACTERS A-Z 0-9 _")
            clean["id"] = it["id"]
        else:
            f = it["formula"]
            if not isinstance(f, str) or not f.strip():
                raise _bad("formula MUST BE TEXT")
            if len(f) > MAX_FORMULA:
                raise _bad(f"formula LONGER THAN {MAX_FORMULA} CHARACTERS")
            clean["formula"] = f
        params = it.get("params", [])
        if not isinstance(params, list) or len(params) > MAX_PARAMS or not all(_num(p) for p in params):
            raise _bad(f"params MUST BE UP TO {MAX_PARAMS} FINITE NUMBERS")
        clean["params"] = list(params)
        label = it.get("label", "")
        if not isinstance(label, str) or len(label) > MAX_LABEL:
            raise _bad(f"label MUST BE TEXT OF AT MOST {MAX_LABEL} CHARACTERS")
        clean["label"] = label
        out.append(clean)
    return out


class PresetStore:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def _load(self) -> dict:
        async with self.db.execute("SELECT value FROM kv WHERE key=?", (KEY,)) as cur:
            row = await cur.fetchone()
        return orjson.loads(row[0]) if row else {}

    async def _save(self, doc: dict) -> None:
        await self.db.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (KEY, orjson.dumps(doc)),
        )
        await self.db.commit()

    async def list(self) -> list[dict]:
        doc = await self._load()
        return sorted(doc.values(), key=lambda p: p["name"].lower())

    async def get(self, raw_name: str) -> dict:
        name = clean_name(raw_name)
        doc = await self._load()
        if name not in doc:
            raise UserDataError("not_found", f"PRESET NOT FOUND: {name}")
        return doc[name]

    async def put(self, raw_name: str, items) -> dict:
        name = clean_name(raw_name)
        clean = validate_items(items)
        doc = await self._load()
        if name not in doc and len(doc) >= MAX_PRESETS:
            raise UserDataError("too_large", f"PRESETS: OVER {MAX_PRESETS} SAVED")
        doc[name] = {"name": name, "items": clean, "updated_at": time.time()}
        await self._save(doc)
        return doc[name]

    async def delete(self, raw_name: str) -> dict:
        name = clean_name(raw_name)
        doc = await self._load()
        if name not in doc:
            raise UserDataError("not_found", f"PRESET NOT FOUND: {name}")
        del doc[name]
        await self._save(doc)
        return {"deleted": name}
