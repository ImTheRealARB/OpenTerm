"""Audit C-10 follow-up: migration 21 recomputes stored journal de-duplication keys with the new rule.

Group 8 widened the key for rows with a broker trade id (id alone -> id + time + symbol + side + order id). Rows stored before
that kept their old key, so re-importing an old broker file would have added every one of them a second time. The migration
rewrites each stored key with the same function the parser uses, so a re-import stays a no-op.
"""

import hashlib

import pytest

from openterm.db import MIGRATIONS, migrate, open_db
from openterm.journal import parsers


def _old_key(broker: str, trade_id: str, n: int = 1) -> str:
    """The key rule before audit C-10 (a broker trade id alone decided)."""
    return hashlib.sha1(f"{broker}|id|{trade_id}#{n}".encode()).hexdigest()[:24]


REKEY_MIGRATION = 21  # the migration that re-keys journal_trades (db.py)

COLS = "dkey, ts, time, symbol, side, qty, price, fee, currency, broker, order_id, trade_id, mult, import_id"


@pytest.mark.asyncio
async def test_migration_rekeys_rows_stored_with_the_old_rule(tmp_path):
    db = await open_db(tmp_path / "j.db")
    try:
        rows = [
            # import 1: a trade with an id (old key), and one without (its key rule did not change)
            (_old_key("zerodha", "T1"), 0.0, "2026-01-02T10:00:00", "INFY.NS", "buy", 5.0, 1500.0, 0.0, "INR", "zerodha", "O1", "T1", 1.0, 1),
            ("x" * 24, 0.0, "2026-01-02T11:00:00", "TCS.NS", "sell", 2.0, 4000.0, 0.0, "INR", "zerodha", "O2", "", 1.0, 1),
        ]
        await db.executemany(f"INSERT INTO journal_trades ({COLS}) VALUES ({','.join('?' * 14)})", rows)
        # As if the DB predates the re-key step (migration 21): roll the version back to 20 and drop what later
        # migrations create, so they can run again (22 = `scripts`, Phase 25). A new migration adds its tables here.
        await db.execute(f"PRAGMA user_version={REKEY_MIGRATION - 1}")
        await db.execute("DROP TABLE scripts")
        await db.commit()

        await migrate(db)

        # What the parser would key these rows as today: the same function, same grouping (per import).
        want = [parsers.Trade(time=r[2], symbol=r[3], side=r[4], qty=r[5], price=r[6], fee=r[7], currency=r[8], broker=r[9],
                              order_id=r[10], trade_id=r[11], mult=r[12]) for r in rows]
        parsers.assign_keys(want)
        async with db.execute("SELECT dkey FROM journal_trades ORDER BY id") as cur:
            got = [r[0] async for r in cur]
        assert got == [t.dkey for t in want]
        assert got[0] != _old_key("zerodha", "T1")  # really rewritten
        async with db.execute("PRAGMA user_version") as cur:
            assert (await cur.fetchone())[0] == len(MIGRATIONS)
    finally:
        await db.close()
