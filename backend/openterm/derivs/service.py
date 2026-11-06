"""Phase 14 derivative functions on top of DataService: provider fallback through the router, SWR cache, one envelope.

Every method returns the standard envelope whose `data` is a table payload (research/table.py, plus the optional `status`, `charts`
and `heat` keys). Pure payload builders live next to the data they format (options/, rates/, futures/); this layer chooses the provider
order, the cache keys and the TTLs, and turns the clock into time to expiry (spec decision C).
"""

from __future__ import annotations

import asyncio
import math
import os
import time
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from ..kite.symbols import derivative_root
from ..options import chain as ch
from ..options import ivstore
from ..options import market as mk
from ..options import pricer as pr
from ..options import surface as sf
from ..options import surface_tables as st
from ..options import tables as ot
from ..redact import redact
from ..research import corp_parse as cp
from ..router import AllFailed
from ..service import DataError, envelope
from ..symbols import resolve
from . import freshness
from .calc_service import CalcMixin
from .fut_service import FuturesMixin

if TYPE_CHECKING:
    from ..service import DataService

#: Fixture mode pins the clock to the recording day (spec C): times to expiry in tests and the bench never drift.
FIXTURE_NOW = datetime(2026, 10, 18, tzinfo=UTC)


class Derivs(FuturesMixin, CalcMixin):
    TTL: ClassVar[dict[str, float]] = {
        "chain": 120.0, "omon": 120.0, "pcr": 120.0, "surface": 300.0, "hivg": 300.0,
    }
    MAX_EXPIRIES = 8

    def __init__(self, svc: DataService, fixtures: bool = False, db: Any = None):
        self.svc = svc
        self.fixtures = fixtures
        self._smile_inputs: dict[str, dict | None] = {}  # smiles cache key -> freshness of the inputs it was computed from
        self.db = db   # local IV30 snapshots (HIVG); None in unit tests that never touch SQLite

    # --- clock ----------------------------------------------------------------------------------
    def now(self) -> float:
        pinned = os.environ.get("OPENTERM_NOW")
        if pinned:
            return datetime.fromisoformat(pinned).replace(tzinfo=UTC).timestamp()
        return FIXTURE_NOW.timestamp() if self.fixtures else time.time()

    def today(self) -> date:
        return datetime.fromtimestamp(self.now(), UTC).date()

    def ttl(self, name: str) -> float:
        return self.svc.ttl.get(f"d_{name}", self.TTL.get(name, 300.0))

    # --- dispatch -------------------------------------------------------------------------------
    PARAMS: ClassVar[dict[str, tuple[str, ...]]] = {"omon": ("date", "moneyness", "q", "r")}

    async def run(self, fn: str, **params: Any) -> dict:
        """Dispatch for GET /api/deriv/{fn}. `params` holds every query pair (names lower-cased)."""
        fn = fn.lower()
        method = getattr(self, f"fn_{fn}", None)
        if method is None:
            raise DataError("not_found", f"NO DERIVATIVES FUNCTION {fn.upper()}")
        with freshness.collect() as notes:
            result = await method(**params)
        return freshness.stamp(result, notes)  # the oldest input sets as_of, any stale input makes the answer stale (audit B-2)

    @staticmethod
    def _need(params: dict[str, Any], what: str) -> str:
        v = params.get(what)
        if not v:
            raise DataError("bad_request", f"{what.upper()} REQUIRED")
        return str(v)

    # --- chains ---------------------------------------------------------------------------------
    async def chain(self, symbol: str, epoch: int | None = None) -> dict:
        """One normalised chain, cached; `epoch=None` is the nearest expiry (which also lists every expiry)."""
        async def fetch() -> dict:
            out, failed = await self.svc.router.call("option_chain", lambda p: p.option_chain(symbol, epoch), symbol)
            return {"data": out, "fallback_from": failed}

        env = await self.svc._swr(f"d:chain:{symbol}:{epoch or 0}", self.ttl("chain"), fetch)
        freshness.note(env)
        return env

    async def chains(self, symbol: str) -> tuple[dict, list[dict], int]:
        """(base chain, the picked expiries' chains in date order, number planned). An expiry that fails is left out."""
        base = (await self.chain(symbol))["data"]
        picked = sf.pick_expiries(base["expirations"])[: self.MAX_EXPIRIES]

        async def one(epoch: int):
            if epoch == base["expiry"]:
                return base
            try:
                return (await self.chain(symbol, epoch))["data"]
            except (DataError, AllFailed):
                return None

        got = await asyncio.gather(*(one(e) for e in picked))
        return base, [c for c in got if c is not None], len(picked)

    # --- market inputs --------------------------------------------------------------------------
    async def rate_and_yield(self, symbol: str, years: float, q_typed: float | None) -> tuple[float, float | None, str | None, float | None, str | None]:
        """(r, UST par yield %, curve date, q, note about q)."""
        env = await self.svc.rates()
        freshness.note(env)
        curve = env["data"]
        r, par = mk.treasury_rate(curve, years)
        q, note = q_typed, None
        if q is None:
            try:
                out, _ = await self.svc.router.call("keystats", lambda p: p.keystats(symbol), symbol)
                q = cp.keystats_values(out).get("dividend_yield")
            except AllFailed:
                q = None
            if q is None:
                note = "DIVIDEND YIELD NOT FOUND AT YAHOO: 0 IS USED. TYPE Q=<percent> FOR A DIVIDEND PAYER"
        return r, par, curve.get("date"), q, note

    def tradier_missing(self) -> list[dict]:
        t = self.svc.router.providers.get("tradier")
        return [] if t is None or t.has_key else [{"key": t.key_name if t else "TRADIER_TOKEN", "what": "VENDOR GREEKS AND IV"}]

    # --- OMON, PCR ------------------------------------------------------------------------------
    async def fn_omon(self, symbol: str | None = None, date: str | None = None, moneyness: str | None = None,
                      q: str | None = None, r: str | None = None, **_: Any) -> dict:
        sym = resolve(self._need({"symbol": symbol}, "symbol"))
        m = (moneyness or "ALL").upper()
        if m not in ot.MONEYNESS:
            raise DataError("bad_request", f"MONEYNESS: {' '.join(ot.MONEYNESS)}")
        try:
            q_typed = float(q) / 100.0 if q not in (None, "") else None
        except ValueError as e:
            raise DataError("bad_request", f"Q={q}: NOT A NUMBER") from e
        if derivative_root(sym) is not None:  # Phase 15: <UNDERLYING>.NFO / .MCX come from Kite Connect, never from Yahoo
            return await self.kite_omon(sym, date, m, q_typed, r)
        base_env = await self.chain(sym)
        base = base_env["data"]
        env = base_env
        if date:
            try:
                want = datetime.strptime(date.strip(), "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError as e:
                raise DataError("bad_request", "DATE: YYYY-MM-DD") from e
            epoch = next((e for e in base["expirations"] if ot.day(e) == want.strftime("%Y-%m-%d")), None)
            if epoch is None:
                near = " ".join(ot.day(e) for e in base["expirations"][:6])
                raise DataError("bad_request", f"NOT AN EXPIRY. NEXT EXPIRIES: {near}")
            env = base_env if epoch == base["expiry"] else await self.chain(sym, epoch)
        chain = env["data"]
        T = ch.years_to_expiry(chain["expiry"], self.now())
        r, par, cdate, qv, note = await self.rate_and_yield(sym, T, q_typed)
        data = ot.omon_payload(chain, T, r, par, cdate, qv, note, m, self.tradier_missing())
        return {**env, "data": data, "source": chain["source"]}

    async def kite_omon(self, sym: str, day: str | None, moneyness: str, q_typed: float | None, r_text: str | None) -> dict:
        from ..kite import chain as kc

        try:
            r_typed = float(r_text) / 100.0 if r_text not in (None, "") else None
        except ValueError as e:
            raise DataError("bad_request", f"R={r_text}: NOT A NUMBER") from e
        kite = self.svc.router.providers["kite"]
        data = await kc.omon(kite.session, kite.client, kite.instruments, sym, self.now(), self.fixtures, day, moneyness, r_typed, q_typed)
        return envelope({"data": data, "source": data["source"]}, time.time(), stale=False)

    async def fn_pcr(self, symbol: str | None = None, **_: Any) -> dict:
        sym = resolve(self._need({"symbol": symbol}, "symbol"))
        base, chains, planned = await self.chains(sym)
        data = ot.pcr_payload(sym, chains, planned, base["source"], self.tradier_missing())
        return envelope({"data": data, "source": base["source"]}, time.time(), stale=False)

    # --- shared inputs for OV and OSA -----------------------------------------------------------
    async def spot(self, sym: str) -> tuple[float, str]:
        try:
            r = await self.svc.quotes([sym])
        except (DataError, AllFailed) as e:
            raise DataError("not_found", f"NO QUOTE FOR {sym}") from e
        freshness.note(r.get(sym))
        d = (r.get(sym) or {}).get("data") or {}
        if d.get("price") is None:
            raise DataError("not_found", f"NO QUOTE FOR {sym}")
        return float(d["price"]), f"live quote ({r[sym].get('source') or 'quote'})"

    async def atm_iv(self, sym: str, target_epoch: float, q_typed: float | None) -> tuple[float, str] | None:
        """ATM IV of the first listed expiry at or after `target_epoch` (else the last one), with that expiry's date."""
        try:
            base = (await self.chain(sym))["data"]
            dates = sorted(base["expirations"])
            if not dates:
                return None
            epoch = next((e for e in dates if e + 20 * 3600 >= target_epoch), dates[-1])
            c = base if epoch == base["expiry"] else (await self.chain(sym, epoch))["data"]
            T = ch.years_to_expiry(epoch, self.now())
            r, _, _, q, _ = await self.rate_and_yield(sym, T, q_typed)
            S = c["spot"]
            calls = ot.side_rows(c["calls"], "call", S, T, r, q or 0.0, "ALL")
            puts = ot.side_rows(c["puts"], "put", S, T, r, q or 0.0, "ALL")
            iv = ch.atm_iv(calls, puts, S)
        except (DataError, AllFailed):
            return None
        return (iv, ot.day(epoch)) if iv is not None else None

    async def _time_and_rate(self, sym: str, params: dict[str, Any]):
        """(T, T basis, r, r basis, q, q basis, target epoch) from EXP / T / R / Q; Nones where they cannot be known."""
        exp, t_typed = pr.parse_expiry(params)
        T = target = None
        t_basis = ""
        if exp:
            target = pr.exp_epoch(exp)
            T = ch.years_to_expiry(target, self.now())
            if T <= 0:
                raise pr.ParamError("EXP IS IN THE PAST")
            t_basis = f"EXP {exp}, 16:00 New York, ACT/365"
        elif t_typed is not None:
            T = t_typed
            target = self.now() + T * 365.0 * 86400.0
            t_basis = "typed on the command line (years)"
        r_typed, q_typed = pr.pct(params, "r"), pr.pct(params, "q")
        r = q = None
        r_basis = q_basis = ""
        if T is not None:
            rr, par, cdate, qv, _ = await self.rate_and_yield(sym, T, q_typed)
            r = r_typed if r_typed is not None else rr
            r_basis = ("typed on the command line (continuous)" if r_typed is not None
                       else f"US Treasury par {par:.2f}% at T ({cdate}), converted to continuous")
            q = qv
            q_basis = "typed on the command line" if q_typed is not None else ("Yahoo trailing annual dividend yield" if qv is not None else "")
        return T, t_basis, r, r_basis, q, q_basis, target

    # --- OV -------------------------------------------------------------------------------------
    async def fn_ov(self, symbol: str | None = None, **params: Any) -> dict:
        sym = resolve(self._need({"symbol": symbol}, "symbol"))
        try:
            i = pr.OvInputs()
            i.k = pr.num(params, "k")
            if i.k is not None and i.k <= 0:
                raise pr.ParamError("K MUST BE POSITIVE")
            kind = str(params.get("type", "")).strip().upper()
            if kind and kind not in pr.TYPE_WORDS:
                raise pr.ParamError("TYPE: C OR P")
            i.kind = pr.TYPE_WORDS.get(kind)
            i.spot, i.spot_basis = await self.spot(sym)
            i.T, i.t_basis, i.r, i.r_basis, i.q, i.q_basis, target = await self._time_and_rate(sym, params)
            i.iv = pr.pct(params, "iv")
            if i.iv is not None:
                if i.iv <= 0:
                    raise pr.ParamError("IV MUST BE POSITIVE (PERCENT)")
                i.iv_basis = "typed on the command line"
            elif target is not None:
                found = await self.atm_iv(sym, target, pr.pct(params, "q"))
                if found:
                    i.iv, i.iv_basis = found[0], f"ATM IV FROM CHAIN, EXP {found[1]}"
            i.price = pr.num(params, "price")
            steps = pr.num(params, "steps")
            if steps is not None:
                if not 10 <= steps <= 2000:
                    raise pr.ParamError("STEPS: 10-2000")
                i.steps = int(steps)
            typed = {k: pr.num(params, k) for k in ("v0", "kappa", "theta", "sigmav", "rho")}
            if any(v is not None for v in typed.values()):
                lacking = [k.upper() for k, v in typed.items() if v is None]
                if lacking:
                    raise pr.ParamError("HESTON NEEDS V0 KAPPA THETA SIGMAV RHO. MISSING: " + " ".join(lacking))
                i.heston = typed
            h, barr = pr.num(params, "h"), str(params.get("barr", "")).strip().upper()
            if h is not None or barr:
                if h is None or barr not in pr.BARRIERS:
                    raise pr.ParamError("BARRIER NEEDS H=<level> BARR=UO|UI|DO|DI")
                i.barrier = {"h": h, "type": pr.BARRIERS[barr], "rebate": pr.num(params, "rebate") or 0.0}
        except pr.ParamError as e:
            raise DataError("bad_request", str(e)) from e
        for name, val in (("K", i.k), ("EXP OR T", i.T), ("TYPE", i.kind), ("IV", i.iv), ("R", i.r), ("Q (TYPE Q=0 FOR NONE)", i.q)):
            if val is None:
                i.missing.append(name)
        data = pr.ov_payload(sym, i, "quote + yahoo_options + treasury")
        return envelope({"data": data, "source": data["source"]}, time.time(), stale=False)

    # --- OSA ------------------------------------------------------------------------------------
    async def fn_osa(self, symbol: str | None = None, **params: Any) -> dict:
        sym = resolve(self._need({"symbol": symbol}, "symbol"))
        try:
            if params.get("legs") and params.get("strat"):
                raise pr.ParamError("USE LEGS= OR STRAT=, NOT BOTH")
            if params.get("legs"):
                legs = pr.parse_legs(params["legs"])
            elif params.get("strat"):
                legs = pr.parse_strategy(params["strat"])
            else:
                raise pr.ParamError("LEGS=+1C270@5,-1C290 OR STRAT=BULLCALL,270,290")
            mult = pr.num(params, "mult") or 100.0
            comm = pr.pct(params, "comm") or 0.0
            if mult <= 0 or not 0 <= comm < 1:
                raise pr.ParamError("MULT MUST BE POSITIVE; COMM IS A PERCENT BELOW 100")
            spot, spot_basis = await self.spot(sym)
            T, _, r, r_basis, _, _, target = await self._time_and_rate(sym, params)
            iv = pr.pct(params, "iv")
            iv_basis = "typed on the command line"
            if iv is not None and iv <= 0:
                raise pr.ParamError("IV MUST BE POSITIVE (PERCENT)")
            if iv is None and target is not None:
                found = await self.atm_iv(sym, target, pr.pct(params, "q"))
                if found:
                    iv, iv_basis = found[0], f"ATM IV FROM CHAIN, EXP {found[1]}"
        except pr.ParamError as e:
            raise DataError("bad_request", str(e)) from e
        missing = [name for name, val in (("EXP OR T", T), ("IV", iv)) if val is None]
        data = pr.osa_payload(sym, legs, spot, spot_basis, T, iv, iv_basis if iv is not None else "", r, r_basis, mult, comm,
                              "quote + yahoo_options + treasury", missing)
        return envelope({"data": data, "source": data["source"]}, time.time(), stale=False)

    # --- surface: OVDV, SKEW, HIVG --------------------------------------------------------------
    EQUITY_K_MAX = 0.35
    CRYPTO_K_MAX = 0.60

    @staticmethod
    def crypto_currency(sym: str) -> str | None:
        base = sym.upper().replace("-USD", "").replace("USDT", "")
        return base if base in ("BTC", "ETH", "SOL", "XRP") else None

    async def smiles(self, sym: str) -> dict:
        """Out-of-the-money (k, iv) points per expiry, cached. Equity: solved from the bid/ask mid of the picked chains. Crypto: Deribit's
        mark IV. `k = ln(K / F)`, F the expiry's forward."""
        cur = self.crypto_currency(sym)
        key = f"d:smiles:{cur or sym}"

        async def fetch() -> dict:
            # The smiles are computed from chains and a curve that may themselves have been stale: keep that with the cached value.
            with freshness.collect() as inputs:
                data = await (self._crypto_smiles(cur) if cur else self._equity_smiles(sym))
            self._smile_inputs[key] = freshness.summarize(inputs)
            return {"data": data, "fallback_from": []}

        env = await self.svc._swr(key, self.ttl("surface"), fetch)
        freshness.note(env)
        freshness.note(self._smile_inputs.get(key))
        return env

    async def _equity_smiles(self, sym: str) -> dict:
        base, chains, planned = await self.chains(sym)
        S = base["spot"]
        out, notes, q_known = [], [], None
        for c in chains:
            T = ch.years_to_expiry(c["expiry"], self.now())
            if T <= 0:
                notes.append(f"{ot.day(c['expiry'])}: EXPIRED, SKIPPED")
                continue
            r, _par, _cd, q, qnote = await self.rate_and_yield(sym, T, q_known)
            if q is not None:
                q_known = q
            elif qnote and qnote not in notes:
                notes.append(qnote)
            qv = q or 0.0
            F = S * math.exp((r - qv) * T)
            pts = []
            for kind, side in (("call", c["calls"]), ("put", c["puts"])):
                for x in side:
                    k = math.log(x["strike"] / F)
                    if abs(k) > self.EQUITY_K_MAX or (kind == "call") != (x["strike"] >= F):
                        continue
                    iv, src = ch.solved_iv(x, kind, S, T, r, qv)
                    if iv is not None and src == "MID" and 0.03 <= iv <= 3.0:
                        pts.append([k, iv])
            out.append({"epoch": c["expiry"], "date": ot.day(c["expiry"]), "T": T, "F": F, "points": pts})
        return {"kind": "equity", "spot": S, "source": base["source"], "planned": planned, "smiles": out, "notes": notes}

    async def _crypto_smiles(self, cur: str) -> dict:
        book, _failed = await self.svc.router.call("crypto_options", lambda p: p.crypto_options(cur), cur)
        out, notes = [], []
        for e in book["expiries"]:
            T = (e["expiry"] - self.now()) / (365.0 * 86400.0)
            if T <= 0:
                notes.append(f"{ot.day(e['expiry'])}: EXPIRED, SKIPPED")
                continue
            F = e["forward"]
            pts = []
            for side, is_call in ((e["calls"], True), (e["puts"], False)):
                for x in side:
                    k = math.log(x["strike"] / F)
                    if abs(k) <= self.CRYPTO_K_MAX and is_call == (x["strike"] >= F):
                        pts.append([k, x["iv"]])
            out.append({"epoch": e["expiry"], "date": ot.day(e["expiry"]), "T": T, "F": F, "points": pts})
        notes.append("CRYPTO IV IS DERIBIT'S MARK IV; THE FORWARD OF EACH EXPIRY IS DERIBIT'S UNDERLYING PRICE FOR IT, 08:00 UTC EXPIRY")
        return {"kind": "crypto", "spot": book["index"], "source": book["source"], "planned": len(book["expiries"]), "smiles": out,
                "notes": notes}

    async def fitted(self, sym: str) -> tuple[dict, list[dict], list[str], dict]:
        """(smiles, expiries that fitted, notes, envelope). An expiry with too few two-sided quotes is left out and listed."""
        env = await self.smiles(sym)
        sm = env["data"]
        rows, notes = [], list(sm["notes"])
        for s in sm["smiles"]:
            fit = sf.fit_smile([(k, v) for k, v in s["points"]])
            if fit is None:
                notes.append(f"{s['date']}: TOO FEW TWO-SIDED QUOTES TO FIT ({len(s['points'])}, NEEDS {sf.MIN_POINTS}), LEFT OUT")
                continue
            rows.append({**s, "fit": fit})
        if not rows:
            raise DataError("not_found", f"NO FITTABLE SMILE FOR {sym}")
        return sm, rows, notes, env

    def iv30(self, rows: list[dict]) -> tuple[float | None, str | None]:
        iv, outside = sf.interp_total_variance([(r["T"], r["fit"].a) for r in rows], 30.0 / 365.0)
        note = "30 DAYS IS OUTSIDE THE FITTED EXPIRIES: THE NEAREST EXPIRY'S ATM IV IS USED FLAT" if outside else \
            "IV30: ATM IV INTERPOLATED LINEARLY IN TOTAL VARIANCE BETWEEN THE TWO EXPIRIES AROUND 30 DAYS"
        return iv, note

    async def snapshot(self, sym: str, iv30: float | None) -> list[tuple[str, float]]:
        if self.db is None:
            return []
        if iv30 is not None:
            await ivstore.record(self.db, sym, self.today().isoformat(), iv30)
        return await ivstore.history(self.db, sym)

    async def fn_ovdv(self, symbol: str | None = None, **_: Any) -> dict:
        sym = resolve(self._need({"symbol": symbol}, "symbol"))
        sm, rows, notes, env = await self.fitted(sym)
        iv30, _ = self.iv30(rows)
        await self.snapshot(sym, iv30)
        data = st.ovdv_payload(sym, sm, rows, notes, [] if sm["kind"] == "crypto" else self.tradier_missing())
        return {**env, "data": data, "source": sm["source"]}

    async def fn_skew(self, symbol: str | None = None, **_: Any) -> dict:
        sym = resolve(self._need({"symbol": symbol}, "symbol"))
        sm, rows, notes, env = await self.fitted(sym)
        data = st.skew_payload(sym, sm, rows, notes, [] if sm["kind"] == "crypto" else self.tradier_missing())
        return {**env, "data": data, "source": sm["source"]}

    async def fn_hivg(self, symbol: str | None = None, **_: Any) -> dict:
        sym = resolve(self._need({"symbol": symbol}, "symbol"))
        sm, rows, notes, env = await self.fitted(sym)
        iv30, iv30_note = self.iv30(rows)
        history = await self.snapshot(sym, iv30)
        bars_sym = f"{self.crypto_currency(sym)}-USD" if sm["kind"] == "crypto" else sym
        bars = bars_error = None
        try:
            bars_env = await self.svc.history(bars_sym, "1y", "1d")
            freshness.note(bars_env)
            bars = bars_env["data"]
        except (DataError, AllFailed) as e:
            bars_error = redact(str(e))
        notes = [*notes, "RV: CLOSE-TO-CLOSE AND PARKINSON, ANNUALISED WITH SQRT(252); VRP = IV30 - RV30 (A SPREAD, NOT A FORECAST)",
                 "IV RANK / PERCENTILE USE ONLY THIS MACHINE'S DAILY IV30 SNAPSHOTS (NO FREE SOURCE HAS IV HISTORY)"]
        data = st.hivg_payload(sym, sm, rows, bars, bars_error, iv30, iv30_note, history, notes,
                               [] if sm["kind"] == "crypto" else self.tradier_missing())
        return {**env, "data": data, "source": sm["source"]}
