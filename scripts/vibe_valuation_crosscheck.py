"""Produces backend/tests/fixtures/valuation_vibe_expected.json by running Vibe-Trading's OWN valuation code.

Not part of the app and never imported by it. Needs numpy and pandas (the backend venv has them) and a directory with the
original files from HKUDS/Vibe-Trading @ d0db2e3:  agent/src/quantlib/valuation/{contracts,dcf,comps}.py  and
agent/src/entities/models.py  (the tests/ page of the repo explains the download; the files are never copied into this repo).

    cd backend
    uv run python ../scripts/vibe_valuation_crosscheck.py <dir with contracts.py dcf.py comps.py entities_models.py>

The inputs below are written into the output file so the tests rebuild exactly the same cases for OpenTerm's port.
"""

import dataclasses
import importlib
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path
from types import MappingProxyType

SRC = Path(sys.argv[1])
OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "valuation_vibe_expected.json"


def build_package() -> Path:
    root = Path(tempfile.mkdtemp(prefix="vibe_val_"))
    for pkg in ("src", "src/quantlib", "src/quantlib/valuation", "src/entities"):
        (root / pkg).mkdir(parents=True, exist_ok=True)
        (root / pkg / "__init__.py").write_text("", encoding="utf-8")
    for name in ("contracts", "dcf", "comps"):
        shutil.copy(SRC / f"{name}.py", root / "src/quantlib/valuation" / f"{name}.py")
    shutil.copy(SRC / "entities_models.py", root / "src/entities/models.py")
    return root


def plain(o):
    """Dataclasses, Assumptions, mappings and tuples -> JSON-able values (NaN -> None)."""
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {f.name: plain(getattr(o, f.name)) for f in dataclasses.fields(o)}
    if isinstance(o, (dict, MappingProxyType)):
        return {str(k): plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [plain(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if hasattr(o, "item"):
        return plain(o.item())
    return o


DCF_INPUTS = {
    "risk_free_rate": 0.041, "beta": 1.069, "equity_risk_premium": 0.055, "pretax_cost_of_debt": 0.035, "tax_rate": 0.16,
    "ebit": [130000.0, 138000.0, 146000.0, 154000.0, 162000.0],
    "depreciation_amortization": [11500.0, 12000.0, 12500.0, 13000.0, 13500.0],
    "capex": [10500.0, 11000.0, 11500.0, 12000.0, 12500.0],
    "delta_nwc": [-1500.0, 2000.0, 1000.0, 800.0, 900.0],
    "terminal_growth": {"name": "terminal_growth", "value": 0.025, "basis": "typed on the command line"},
    "exit_multiple": {"name": "exit_multiple", "value": 14.0, "basis": "typed on the command line"},
    "total_debt": 98000.0, "cash_and_equivalents": 62000.0, "minority_interest": 0.0, "preferred_equity": 0.0,
    "associate_investments": 0.0, "diluted_shares": 15000.0,
    "market_value_of_equity": 3000000.0, "market_value_of_debt": 98000.0,
    "target_equity_weight": 0.9, "target_debt_weight": 0.1,
}
DCF_CASES = [
    {"name": "current_mid_perp", "basis": "current", "conv": "mid_year", "tv": "perpetuity_growth"},
    {"name": "current_end_exit", "basis": "current", "conv": "year_end", "tv": "exit_multiple"},
    {"name": "target_mid_perp", "basis": "target", "conv": "mid_year", "tv": "perpetuity_growth"},
]
GRID = {"wacc": [0.07, 0.08, 0.09], "growth": [0.01, 0.02, 0.03, 0.09]}


def fm(fye, last, ytd=None, pytd=None, nxt=None):
    return {"fiscal_year_end_month": fye, "last_full_fiscal_year": last, "current_year_to_date": ytd,
            "prior_year_to_date": pytd, "next_full_fiscal_year": nxt}


def company(name, fye, scale, cap=None, shares=None):
    c = {"name": name, "total_debt": 100.0 * scale, "cash_and_equivalents": 60.0 * scale,
         "ebitda": fm(fye, 400.0 * scale, 330.0 * scale, 300.0 * scale, 450.0 * scale),
         "ebit": fm(fye, 330.0 * scale, 270.0 * scale, 245.0 * scale, 370.0 * scale),
         "revenue": fm(fye, 1200.0 * scale, 950.0 * scale, 880.0 * scale, 1300.0 * scale),
         "diluted_eps": fm(fye, 6.0, 4.6, 4.2, 6.6), "book_value_of_equity": 700.0 * scale,
         "eps_basis": "gaap", "minority_interest": 5.0 * scale, "preferred_stock": None, "investments_in_associates": 10.0 * scale}
    if cap is not None:
        c.update(market_cap=cap * scale, price_per_share=120.0)
    if shares is not None:
        c["diluted_shares_outstanding"] = shares
    return c


COMPS = {
    "target": company("TGT", 12, 1.0, shares=100.0),
    "peers": [company("P1", 12, 1.1, cap=3200.0), company("P2", 6, 0.8, cap=2100.0), company("P3", 9, 1.4, cap=5200.0)],
}


def main() -> None:
    root = build_package()
    sys.path.insert(0, str(root))
    contracts = importlib.import_module("src.quantlib.valuation.contracts")
    dcf = importlib.import_module("src.quantlib.valuation.dcf")
    comps = importlib.import_module("src.quantlib.valuation.comps")

    def prep(inp):
        d = dict(inp)
        for k in ("terminal_growth", "exit_multiple"):
            d[k] = contracts.Assumption(**inp[k])
        return d

    def flow(x):
        return comps.FlowMetricPeriods(**x)

    def company_obj(cls, c):
        kw = {k: v for k, v in c.items() if k not in ("ebitda", "ebit", "revenue", "diluted_eps")}
        for k in ("ebitda", "ebit", "revenue", "diluted_eps"):
            kw[k] = flow(c[k])
        return cls(**kw)

    out = {"commit": "d0db2e3", "dcf_inputs": DCF_INPUTS, "dcf_cases": [], "grid": {**GRID}, "comps_inputs": COMPS,
           "comps_cases": [], "errors": []}
    for case in DCF_CASES:
        r = dcf.run_dcf(prep(DCF_INPUTS), capital_structure_basis=case["basis"], discounting_convention=case["conv"],
                        terminal_value_method=case["tv"])
        out["dcf_cases"].append({**case, "result": plain(r)})
    bridge = dcf.fcff_bridge(ebit=DCF_INPUTS["ebit"], tax_rate=DCF_INPUTS["tax_rate"],
                             depreciation_amortization=DCF_INPUTS["depreciation_amortization"],
                             capex=DCF_INPUTS["capex"], delta_nwc=DCF_INPUTS["delta_nwc"])
    g = dcf.sensitivity_grid(bridge, wacc_values=GRID["wacc"], growth_values=GRID["growth"], discounting_convention="mid_year",
                             total_debt=98000.0, cash_and_equivalents=62000.0, minority_interest=0.0, preferred_equity=0.0,
                             associate_investments=0.0, diluted_shares=15000.0)
    out["grid"]["values"] = plain(g.to_numpy().tolist())
    target = company_obj(comps.TargetCompany, COMPS["target"])
    peers = [company_obj(comps.PeerCompany, p) for p in COMPS["peers"]]
    for policy in ("ltm", "calendar_year"):
        out["comps_cases"].append({"policy": policy, "result": plain(comps.run_comps(target, peers, calendarisation_policy=policy))})
    for name, fn in (
        ("growth_at_wacc", lambda: dcf.run_dcf({**prep(DCF_INPUTS), "terminal_growth": contracts.Assumption("terminal_growth", 0.5, "x")},
                                               capital_structure_basis="current", discounting_convention="mid_year",
                                               terminal_value_method="perpetuity_growth")),
        ("missing", lambda: dcf.run_dcf({k: v for k, v in prep(DCF_INPUTS).items() if k not in ("beta", "diluted_shares")},
                                        capital_structure_basis="current", discounting_convention="mid_year",
                                        terminal_value_method="perpetuity_growth")),
        ("bare_growth", lambda: dcf.run_dcf({**prep(DCF_INPUTS), "terminal_growth": 0.025}, capital_structure_basis="current",
                                            discounting_convention="mid_year", terminal_value_method="perpetuity_growth")),
        ("no_peers", lambda: comps.run_comps(target, [], calendarisation_policy="ltm")),
    ):
        try:
            fn()
            out["errors"].append({"name": name, "type": None, "message": None})
        except Exception as e:  # noqa: BLE001 - recording what Vibe raises is the point
            out["errors"].append({"name": name, "type": type(e).__name__, "message": str(e),
                                  "missing": list(getattr(e, "missing", ()))})
    OUT.write_bytes(json.dumps(out, indent=1).encode("utf-8"))
    print("wrote", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
