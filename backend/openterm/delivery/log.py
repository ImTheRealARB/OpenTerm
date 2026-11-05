"""The `deliveries` table: one row per channel attempt, newest 500 kept (Phase 17 B)."""

from __future__ import annotations

import time

from .. import redact

KEEP = 500
DETAIL_MAX = 300
MIN_SECRET = 4  # shorter values would mangle ordinary words in an error text
KINDS = ("alert", "news", "brief", "test")
# "retrying" = a temporary failure (429 / 5xx / network); a background task retries after 30 s, 2 min, 10 min,
# then rewrites the SAME row to sent or failed (Phase 20).
STATUSES = ("sent", "failed", "skipped", "retrying")


def clean(detail, secrets=()) -> str | None:
    """Every detail is redacted (keys, passwords) and cut to 300 characters before it is stored or shown.

    `secrets` are values this module cannot know about globally (the configured recipient address, the Telegram
    chat id, the SMTP user): an SMTP server often echoes the recipient back in its error text, so they are
    blanked here too. `redact.redact` is called AFTER, for the keys it already tracks.
    """
    if detail is None:
        return None
    text = " ".join(str(detail).split())
    for s in sorted({s for s in secrets if s and len(s) >= MIN_SECRET}, key=len, reverse=True):
        text = text.replace(s, "***")
    return redact.redact(text)[:DETAIL_MAX]


async def add(db, kind: str, ref: str, channel: str, status: str, detail=None, secrets=()) -> int:
    """Inserts one row and returns its id (a retrying row is rewritten later with `update`)."""
    cur = await db.execute(
        "INSERT INTO deliveries (at, kind, ref, channel, status, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (time.time(), kind, str(ref), channel, status, clean(detail, secrets)))
    # Keep only the newest KEEP rows: delete everything at or below the id of the (KEEP+1)-th newest row.
    await db.execute(
        "DELETE FROM deliveries WHERE id <= (SELECT id FROM deliveries ORDER BY id DESC LIMIT 1 OFFSET ?)", (KEEP,))
    await db.commit()
    return cur.lastrowid


async def update(db, row_id: int, status: str, detail=None, secrets=()) -> None:
    """Rewrites the status and detail of one row (a retry finished, or failed again)."""
    await db.execute("UPDATE deliveries SET status=?, detail=?, at=? WHERE id=?",
                     (status, clean(detail, secrets), time.time(), row_id))
    await db.commit()


async def recent(db, limit: int = 100) -> list[dict]:
    cols = ("id", "at", "kind", "ref", "channel", "status", "detail")
    async with db.execute(f"SELECT {', '.join(cols)} FROM deliveries ORDER BY id DESC LIMIT ?", (limit,)) as cur:
        return [dict(zip(cols, r, strict=True)) for r in await cur.fetchall()]
