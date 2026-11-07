"""YAS, SWPM, CDSW and FXFA on top of DataService (a mixin of Derivs, see derivs/service.py). Pure math and payloads are in calc.py;
this layer parses the typed arguments, gathers the market inputs (Treasury curve, ECB, MoF, the spot quote) and turns CalcError into a 400."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from ..errors import DataError
from ..redact import redact
from ..router import AllFailed
from ..service import envelope
from ..symbols import resolve
from . import calc as cc
from . import freshness

if TYPE_CHECKING:
    from ..service import DataService


def _env(data: dict) -> dict:
    return envelope({"data": data, "source": data["source"]}, time.time(), stale=False)


class CalcMixin:
    svc: DataService

    # --- YAS ------------------------------------------------------------------------------------
    async def fn_yas(self, **p: Any) -> dict:
        try:
            cpn = cc.num(p, "cpn")
            cpn = None if cpn is None else cpn / 100.0
            mat = cc.parse_date(p.get("mat"), "MAT")
            freq_typed = cc.num(p, "freq")
            freq = 2 if freq_typed is None else int(freq_typed)
            if freq not in (1, 2, 4, 12):
                raise cc.CalcError("FREQ: 1 2 4 OR 12")
            settle = cc.parse_date(p.get("settle"), "SETTLE")
            today = self.today()  # type: ignore[attr-defined]
            settle_basis = "typed" if settle else "default: today (a fact, not an opinion)"
            settle = settle or today
            conv = str(p.get("days") or "ACT/ACT").strip().upper()
            if conv not in cc.DAY_COUNTS:
                raise cc.CalcError("DAYS: " + " ".join(cc.DAY_COUNTS))
            face = cc.num(p, "face") or 100.0
            px, yld = cc.num(p, "px"), cc.num(p, "yld")
            yld = None if yld is None else yld / 100.0
            if face <= 0:
                raise cc.CalcError("FACE MUST BE POSITIVE")
            if yld is not None and yld <= -0.5:  # the solver searches -50%..500%; below -100% per period the discount base is <= 0
                raise cc.CalcError("YLD MUST BE ABOVE -50%")
            if px is not None and yld is not None:
                raise cc.CalcError("TYPE PX OR YLD, NOT BOTH")
            if px is not None and px <= 0:
                raise cc.CalcError("PX MUST BE POSITIVE")
            if cpn is not None and cpn < 0:
                raise cc.CalcError("CPN MUST NOT BE NEGATIVE")
            if mat is not None and mat <= settle:
                raise cc.CalcError(f"MAT {mat} IS NOT AFTER SETTLE {settle}")
            missing = [n for n, v in (("CPN", cpn), ("MAT", mat)) if v is None]
            data = cc.yas_payload(cpn, mat, freq, settle, face, conv, px, yld, settle_basis, missing)
        except cc.CalcError as e:
            raise DataError("bad_request", str(e)) from e
        return _env(data)

    # --- SWPM -----------------------------------------------------------------------------------
    async def fn_swpm(self, **p: Any) -> dict:
        from ..quant import swap as qs

        try:
            n, fixed, tenor = cc.num(p, "n"), cc.num(p, "fixed"), cc.num(p, "tenor")
            fixed = None if fixed is None else fixed / 100.0
            freq_typed = cc.num(p, "freq")
            freq = 2 if freq_typed is None else int(freq_typed)
            freq_basis = "default: 2 (semi-annual)" if freq_typed is None else "typed"
            direction = str(p.get("dir") or "").strip().upper() or None
            if direction not in (None, "PAY", "REC"):
                raise cc.CalcError("DIR: PAY (PAY FIXED) OR REC (RECEIVE FIXED)")
            if n is not None and n <= 0 or tenor is not None and tenor <= 0 or freq <= 0:
                raise cc.CalcError("N, TENOR AND FREQ MUST BE POSITIVE")
            spec = str(p.get("curve") or "TSY").strip().upper()
            missing = [name for name, v in (("N", n), ("FIXED", fixed), ("TENOR", tenor), ("DIR", direction)) if v is None]
            curve = None
            curve_note = ""
            if spec.startswith("FLAT:"):
                try:
                    r = float(spec[5:]) / 100.0
                except ValueError:
                    raise cc.CalcError("CURVE: FLAT:4.2 (PERCENT, CONTINUOUS) OR TSY") from None
                curve, label = qs.flat_curve(r), f"FLAT {r * 100:g}%"
                basis, source = "typed: flat continuously compounded zero rate", "typed inputs"
            elif spec == "TSY":
                env = await self.svc.rates()
                freshness.note(env)
                c = env["data"]
                par = {y: v / 100.0 for y, v in zip(c["years"], c["yields"], strict=True) if v is not None and y > 0}
                try:
                    curve = qs.bootstrap_par_curve(par, 2)
                except ValueError as e:
                    raise cc.CalcError(f"CANNOT BOOTSTRAP THE TREASURY CURVE: {e}") from e
                label = f"TSY {c.get('date') or ''}".strip()
                basis = f"US Treasury par curve of {c.get('date')}, bootstrapped (log-linear discount factors)"
                source = env.get("source") or "treasury"
                curve_note = "TREASURY PAR CURVE AS A DISCOUNT PROXY, NOT SOFR/OIS: A SWAP DISCOUNTED ON TREASURIES IS NOT A MARKET SWAP VALUE"
            else:
                raise cc.CalcError("CURVE: FLAT:4.2 (PERCENT, CONTINUOUS) OR TSY")
            res = None
            if not missing:
                try:
                    res = qs.value_swap(n, fixed, tenor, freq, curve, pay_fixed=direction == "PAY")
                except ValueError as e:
                    raise cc.CalcError(str(e).upper()) from e
            data = cc.swpm_payload(n, fixed, tenor, freq, direction, label, basis, curve_note, res, missing, freq_basis, source)
        except cc.CalcError as e:
            raise DataError("bad_request", str(e)) from e
        return _env(data)

    # --- CDSW -----------------------------------------------------------------------------------
    async def fn_cdsw(self, **p: Any) -> dict:
        from ..quant import credit as qc

        try:
            spread, rec, tenor = cc.num(p, "spread"), cc.num(p, "rec"), cc.num(p, "tenor")
            rf, coupon, notional = cc.num(p, "rf"), cc.num(p, "coupon"), cc.num(p, "n")
            rec = None if rec is None else rec / 100.0
            rf = None if rf is None else rf / 100.0
            freq_typed = cc.num(p, "freq")
            freq = 4 if freq_typed is None else int(freq_typed)
            freq_basis = "default: 4 (quarterly, the standard CDS convention)" if freq_typed is None else "typed"
            missing = [name for name, v in (("SPREAD", spread), ("REC", rec), ("TENOR", tenor), ("RF", rf), ("COUPON", coupon),
                                            ("N", notional)) if v is None]
            res = None
            if not missing:
                try:
                    res = qc.cds_price(spread, rec, tenor, rf, coupon, notional, freq)
                except ValueError as e:
                    raise cc.CalcError(str(e).upper().replace("_", " ")) from e
            data = cc.cdsw_payload(spread, rec, tenor, rf, coupon, notional, freq, freq_basis, res, missing)
        except cc.CalcError as e:
            raise DataError("bad_request", str(e)) from e
        return _env(data)

    # --- FXFA -----------------------------------------------------------------------------------
    async def _fx_rate(self, ccy: str, typed: float | None, flag: str) -> tuple[dict, str | None]:
        """({"typed", "points", "basis"}, the missing-input text or None). Money-market rates: USD from the Treasury bill part, EUR from
        the ECB 3M-1Y, JPY from the MoF 1Y; any other currency needs a typed rate."""
        if typed is not None:
            return {"typed": typed, "points": None, "basis": f"typed {flag}= (percent)"}, None
        try:
            if ccy == "USD":
                env = await self.svc.rates()
                freshness.note(env)
                c = env["data"]
                pts = [(y, v) for y, v in zip(c["years"], c["yields"], strict=True) if v is not None and y <= 1.0]
                basis, date = "US Treasury bill/par curve up to 1Y", c.get("date")
                source = env.get("source")
            elif ccy in ("EUR", "JPY") and getattr(self.svc, "rates_views", None) is not None:
                cp = await self.svc.rates_views.curve_points(ccy)
                pts = [(y, v) for y, v in cp["points"] if y <= 1.0]
                basis = "ECB AAA spot curve, 3M-1Y" if ccy == "EUR" else "MoF JGB curve, 1Y point (no shorter point is published)"
                date, source = cp.get("date"), cp.get("source")
            else:
                return {"typed": None, "points": None, "basis": "MISSING"}, f"{ccy} RATE (NO FREE SOURCE: TYPE {flag}=<percent>)"
        except (DataError, AllFailed) as e:
            return {"typed": None, "points": None, "basis": "MISSING"}, f"{ccy} RATE (SOURCE FAILED: {redact(str(e))}; TYPE {flag}=<percent>)"
        if not pts:
            return {"typed": None, "points": None, "basis": "MISSING"}, f"{ccy} RATE (NO CURVE POINT UP TO 1Y; TYPE {flag}=<percent>)"
        return {"typed": None, "points": pts, "basis": f"{basis} ({date}, {source})"}, None

    async def fn_fxfa(self, pair: str | None = None, symbol: str | None = None, **p: Any) -> dict:
        raw = pair or symbol
        if not raw:
            raise DataError("bad_request", "PAIR REQUIRED, E.G. EURUSD")
        try:
            base, quote = cc.split_pair(raw)
            r1, r2 = cc.num(p, "r1"), cc.num(p, "r2")
            tenors = cc.tenors_of(p.get("tenors"))
        except cc.CalcError as e:
            raise DataError("bad_request", str(e)) from e
        sym = resolve(base + quote)
        rb, mb = await self._fx_rate(base, r1, "R1")
        rq, mq = await self._fx_rate(quote, r2, "R2")
        missing = [m for m in (mb, mq) if m]
        spot = spot_basis = None
        try:
            spot, spot_basis = await self.spot(sym)  # type: ignore[attr-defined]
        except DataError:
            missing.append(f"SPOT {sym}")
        data = cc.fxfa_payload(base + quote, base, quote, spot, spot_basis or "MISSING", tenors, rb, rq, missing,
                               "quote + treasury + ecb + mof (rates as typed or shown)")
        return _env(data)
