"""Phase 14 RATES views on top of DataService: provider fallback through the router, SWR cache, one envelope (same pattern as
research/service.py). Every table method returns the standard envelope whose `data` is a table payload (research/table.py).

Curves are cached as the parsed curve (not the table), so `curve(ccy)`, `curve(ccy, fit="NS")` and `curve_points(ccy)` (FXFA) share one
fetch and one cache key per currency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from ..errors import DataError
from . import parse as rp
from . import tables as rt

if TYPE_CHECKING:
    from ..service import DataService

CAPABILITY = {"EUR": "curve_eur", "GBP": "curve_gbp", "CAD": "curve_cad", "JPY": "curve_jpy"}


class RatesViews:
    TTL: ClassVar[dict[str, float]] = {"curve": 3600.0, "spreads": 21600.0, "auctions": 3600.0}

    def __init__(self, svc: DataService):
        self.svc = svc

    def ttl(self, name: str) -> float:
        return self.svc.ttl.get(f"rt_{name}", self.TTL[name])

    # --- curves ---------------------------------------------------------------------------------
    @staticmethod
    def _ccy(ccy: str | None) -> str:
        c = (ccy or "").strip().upper()
        if c not in rt.CURRENCIES:
            raise DataError("bad_request", "CURRENCY: " + " ".join(rt.CURRENCIES))
        return c

    async def _curve_env(self, ccy: str) -> dict:
        capability = CAPABILITY[ccy]

        async def fetch() -> dict:
            out, failed = await self.svc.router.call(capability, lambda p: getattr(p, capability)())
            return {"data": out["curve"], "source": out["source"], "fallback_from": failed}

        return await self.svc.swr(f"rt:curve:{ccy}", self.ttl("curve"), fetch)

    async def curve(self, ccy: str | None, fit: str | None = None) -> dict:
        c = self._ccy(ccy)
        model = (fit or "").strip().upper()
        if model not in ("", "NS"):
            raise DataError("bad_request", "FIT: NS (NELSON-SIEGEL)")
        env = await self._curve_env(c)
        curve = env["data"]
        fitted = self._fit(c, curve) if model else None
        return {**env, "data": rt.curve_payload(c, curve, env["source"], fitted)}

    @staticmethod
    def _fit(ccy: str, curve: dict) -> dict:
        # lazy: the quant library stays out of the server import
        from ..quant.fixedincome import fit_yield_curve

        rows = rp.curve_rows(curve)
        pts = [(r["years"], r["yield"]) for r in rows if r["yield"] is not None]
        try:
            f = fit_yield_curve([t for t, _ in pts], [y / 100.0 for _, y in pts], "nelson_siegel")
        except ValueError as e:
            raise DataError("bad_request", f"NELSON-SIEGEL NEEDS 4 CURVE POINTS: {ccy} HAS {len(pts)}", str(e)) from e
        return {"params": f.params, "rmse": f.rmse, "points": len(pts),
                "fitted": {r["tenor"]: float(f(r["years"])) * 100.0 for r in rows}}

    async def curve_points(self, ccy: str | None) -> dict:
        """{"date", "source", "points": [(years, yield percent)]} for FXFA: the latest curve, from the same cache entry the table uses."""
        c = self._ccy(ccy)
        env = await self._curve_env(c)
        curve = env["data"]
        return {"date": curve["dates"][-1] if curve["dates"] else None, "source": env["source"], "points": rp.curve_points(curve)}

    # --- credit spreads -------------------------------------------------------------------------
    async def spreads(self) -> dict:
        async def fetch() -> dict:
            out, failed = await self.svc.router.call("credit_spreads", lambda p: p.credit_spreads())
            rows = [rp.oas_row(sid, rt.OAS_NAMES[sid], out["series"].get(sid, [])) for sid in rt.OAS_NAMES]
            return {"data": rt.spreads_payload(rows, out["failed"], out["source"]), "fallback_from": failed}

        return await self.svc.swr("rt:spreads", self.ttl("spreads"), fetch)

    # --- Treasury auctions ----------------------------------------------------------------------
    async def auctions(self) -> dict:
        async def fetch() -> dict:
            out, failed = await self.svc.router.call("auctions", lambda p: p.auctions())
            return {"data": rt.auctions_payload(out["results"], out["upcoming"], out["source"]), "fallback_from": failed}

        return await self.svc.swr("rt:auctions", self.ttl("auctions"), fetch)
