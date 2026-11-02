"""The `deliveries` table: one row per channel attempt, newest 500 kept (Phase 17 B)."""

from __future__ import annotations

import time

from .. import redact

KEEP = 500
DETAIL_MAX = 300
KINDS = ("alert", "news", "brief", "test")
STATUSES = ("sent", "failed", "skipped")


def clean(detail) -> str | None:
    """Every detail is redacted (keys, passwords) and cut to 300 characters before it is stored or shown."""
    if detail is None:
        return None
    return redact.redact(" ".join(str(detail).split()))[:DETAIL_MAX]


async def add(db, kind: str, ref: str, channel: str, status: str, detail=None) -> None:
    await db.execute(
        "INSERT INTO deliveries (at, kind, ref, channel, status, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (time.time(), kind, str(ref), channel, status, clean(detail)))
    # Keep only the newest KEEP rows: delete everything at or below the id of the (KEEP+1)-th newest row.
    await db.execute(
        "DELETE FROM deliveries WHERE id <= (SELECT id FROM deliveries ORDER BY id DESC LIMIT 1 OFFSET ?)", (KEEP,))
    await db.commit()


async def recent(db, limit: int = 100) -> list[dict]:
    cols = ("id", "at", "kind", "ref", "channel", "status", "detail")
    async with db.execute(f"SELECT {', '.join(cols)} FROM deliveries ORDER BY id DESC LIMIT ?", (limit,)) as cur:
        return [dict(zip(cols, r, strict=True)) for r in await cur.fetchall()]
