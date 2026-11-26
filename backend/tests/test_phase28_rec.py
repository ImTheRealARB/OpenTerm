"""Phase 28: the chain recorder (snapshot write, prev OI, IV rank) with a fake chain, and the OSCAN filter parser. No network."""

import asyncio
from datetime import UTC, datetime

import pytest

from openterm.db import open_db
from openterm.options import recorder as rec

NOW = datetime(2026, 10, 1, tzinfo=UTC).timestamp()
EXPIRY = int(NOW + 30 * 86400)  # 30 days out: counts for the IV rank (needs >= 20 days)


class FakeDerivs:
    """Stands in for `Derivs`: one expiry, strikes 90/100/110, the same IV on both sides, OI set per test."""

    def __init__(self):
        self.iv = 0.2
        self.oi = {"call": 100, "put": 200}

    def now(self):
        return NOW

    async def chain(self, symbol, epoch=None):
        def side(kind):
            return [{"strike": k, "bid": None, "ask": None, "last": 1.0, "volume": 5, "oi": self.oi[kind], "iv_vendor": self.iv}
                    for k in (90.0, 100.0, 110.0)]
        return {"data": {"symbol": symbol, "spot": 100.0, "expiry": EXPIRY, "expirations": [EXPIRY],
                         "calls": side("call"), "puts": side("put"), "vendor_greeks": False, "source": "fake"}}

    async def rate_and_yield(self, symbol, years, q_typed):
        return 0.04, None, None, 0.0, None


def test_snapshot_prev_oi_and_iv_rank(tmp_path):
    async def go():
        db = await open_db(tmp_path / "t.db")
        d = FakeDerivs()
        # three recorded days with ATM IV 20%, 30%, 25%; open interest changes on the last day
        for day, iv in (("2026-09-28", 0.2), ("2026-09-29", 0.3), ("2026-09-30", 0.25)):
            d.iv = iv
            out = await rec.record_symbol(d, db, "AAPL", day)
            assert out == {"expiries": 1, "rows": 6}
        d.oi = {"call": 150, "put": 250}
        await rec.record_symbol(d, db, "AAPL", "2026-10-01")

        prev, day = await rec.prev_oi(db, "AAPL", EXPIRY, "2026-10-01")
        assert day == "2026-09-30" and prev[("call", 100.0)] == 100 and prev[("put", 100.0)] == 200
        assert await rec.prev_oi(db, "AAPL", EXPIRY, "2026-09-28") == (None, None)  # nothing before the first day

        st = await rec.symbol_stats(db, "AAPL")
        assert st["days_recorded"] == 4 and st["first_day"] == "2026-09-28"
        assert st["oi"] == 3 * 150 + 3 * 250 and st["pcr"] == pytest.approx(250 / 150)
        # IV now 25% against recorded 20 / 30 / 25 / 25: rank (0.25-0.2)/(0.3-0.2) = 0.5, percentile = 1 of 4 below
        assert st["iv_rank"] == pytest.approx(0.5) and st["iv_percentile"] == pytest.approx(0.25)
        assert await rec.symbol_stats(db, "MSFT") is None  # never recorded
        await db.close()

    asyncio.run(go())


def test_oscan_filter_parser():
    assert rec.parse_filter("IVR>50 EM>=5 pcr<1.2") == [("IVR", ">", 50.0), ("EM", ">=", 5.0), ("PCR", "<", 1.2)]
    assert rec.parse_filter("") == []
    with pytest.raises(rec.FilterError):
        rec.parse_filter("RSI>50")
    stats = {"iv_rank": 0.6, "em_pct": 4.0, "oi": 5000, "pcr": None}
    assert rec.matches(stats, rec.parse_filter("IVR>50 OI>1000"))
    assert not rec.matches(stats, rec.parse_filter("EM>5"))
    assert not rec.matches(stats, rec.parse_filter("PCR>1"))  # a missing number never passes
