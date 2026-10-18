"""Phase 13 step 4: the ported valuation engine matches Vibe-Trading's own numbers.

fixtures/valuation_vibe_expected.json was produced by running Vibe's code at d0db2e3 on the inputs stored in the same file
(scripts/vibe_valuation_crosscheck.py). Every number below comes from there; nothing is hand-typed.
"""

import dataclasses
import json
import math
import subprocess
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

from openterm.valuation import comps, contracts, dcf

EXPECTED = json.loads((Path(__file__).parent / "fixtures" / "valuation_vibe_expected.json").read_bytes().decode("utf-8"))


def plain(o):
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return {f.name: plain(getattr(o, f.name)) for f in dataclasses.fields(o)}
    if isinstance(o, (dict, MappingProxyType)):
        return {str(k): plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [plain(v) for v in o]
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def same(got, want, path="result"):
    if isinstance(want, dict):
        assert isinstance(got, dict) and got.keys() == want.keys(), (path, sorted(got), sorted(want))
        for k in want:
            same(got[k], want[k], f"{path}.{k}")
    elif isinstance(want, list):
        assert isinstance(got, list) and len(got) == len(want), path
        for i, (g, w) in enumerate(zip(got, want)):
            same(g, w, f"{path}[{i}]")
    elif isinstance(want, float):
        assert got == pytest.approx(want, rel=1e-9, abs=1e-9), path
    else:
        assert got == want, path


def dcf_inputs():
    d = dict(EXPECTED["dcf_inputs"])
    for k in ("terminal_growth", "exit_multiple"):
        d[k] = contracts.Assumption(**d[k])
    return d


@pytest.mark.parametrize("case", EXPECTED["dcf_cases"], ids=lambda c: c["name"])
def test_run_dcf_matches_vibe(case):
    r = dcf.run_dcf(dcf_inputs(), capital_structure_basis=case["basis"], discounting_convention=case["conv"],
                    terminal_value_method=case["tv"])
    same(plain(r), case["result"])


def test_sensitivity_grid_matches_vibe_and_leaves_growth_above_wacc_empty():
    i = EXPECTED["dcf_inputs"]
    bridge = dcf.fcff_bridge(ebit=i["ebit"], tax_rate=i["tax_rate"], depreciation_amortization=i["depreciation_amortization"],
                             capex=i["capex"], delta_nwc=i["delta_nwc"])
    g = dcf.sensitivity_grid(bridge, wacc_values=EXPECTED["grid"]["wacc"], growth_values=EXPECTED["grid"]["growth"],
                             discounting_convention="mid_year", total_debt=98000.0, cash_and_equivalents=62000.0,
                             minority_interest=0.0, preferred_equity=0.0, associate_investments=0.0, diluted_shares=15000.0)
    same(plain(list(map(list, g.values))), EXPECTED["grid"]["values"])
    assert all(math.isnan(row[3]) for row in g.values) and not math.isnan(g.values[0][0])  # growth 9% >= every WACC in the grid
    assert g.wacc == tuple(EXPECTED["grid"]["wacc"]) and g.terminal_growth == tuple(EXPECTED["grid"]["growth"])


def flow(x):
    return comps.FlowMetricPeriods(**x)


def company(cls, c):
    kw = {k: v for k, v in c.items() if k not in ("ebitda", "ebit", "revenue", "diluted_eps")}
    for k in ("ebitda", "ebit", "revenue", "diluted_eps"):
        kw[k] = flow(c[k])
    return cls(**kw)


@pytest.mark.parametrize("case", EXPECTED["comps_cases"], ids=lambda c: c["policy"])
def test_run_comps_matches_vibe(case):
    target = company(comps.TargetCompany, EXPECTED["comps_inputs"]["target"])
    peers = [company(comps.PeerCompany, p) for p in EXPECTED["comps_inputs"]["peers"]]
    same(plain(comps.run_comps(target, peers, calendarisation_policy=case["policy"])), case["result"])


def test_refusals_match_vibe_by_type_message_and_missing_names():
    inp = dcf_inputs()
    target = company(comps.TargetCompany, EXPECTED["comps_inputs"]["target"])
    run = {
        "growth_at_wacc": lambda: dcf.run_dcf({**inp, "terminal_growth": contracts.Assumption("terminal_growth", 0.5, "x")},
                                              capital_structure_basis="current", discounting_convention="mid_year",
                                              terminal_value_method="perpetuity_growth"),
        "missing": lambda: dcf.run_dcf({k: v for k, v in inp.items() if k not in ("beta", "diluted_shares")},
                                       capital_structure_basis="current", discounting_convention="mid_year",
                                       terminal_value_method="perpetuity_growth"),
        "bare_growth": lambda: dcf.run_dcf({**inp, "terminal_growth": 0.025}, capital_structure_basis="current",
                                           discounting_convention="mid_year", terminal_value_method="perpetuity_growth"),
        "no_peers": lambda: comps.run_comps(target, [], calendarisation_policy="ltm"),
    }
    for want in EXPECTED["errors"]:
        with pytest.raises(contracts.ValuationError) as e:
            run[want["name"]]()
        assert type(e.value).__name__ == want["type"], want["name"]
        assert str(e.value) == want["message"], want["name"]
        assert list(getattr(e.value, "missing", ())) == want["missing"], want["name"]


def test_a_missing_input_is_never_replaced_by_a_default():
    with pytest.raises(contracts.MissingInputError) as e:
        contracts.require_inputs({"a": 1, "b": None, "c": " "}, ["a", "b", "c", "d"], "m")
    assert e.value.missing == ("b", "c", "d")
    contracts.require_inputs({"zero": 0, "no": False}, ["zero", "no"], "m")  # zero and False are real values
    with pytest.raises(ValueError):
        contracts.Assumption("g", 0.02, "  ")


def test_the_valuation_package_never_imports_numpy_or_pandas():
    code = ("import sys, openterm.valuation.contracts, openterm.valuation.dcf, openterm.valuation.comps\n"
            "bad = [m for m in ('numpy', 'pandas') if m in sys.modules]\nassert not bad, bad\n")
    r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=Path(__file__).parents[1], check=False)
    assert r.returncode == 0, r.stderr
