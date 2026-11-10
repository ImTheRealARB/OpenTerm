"""Ports the Alpha Zoo of HKUDS/Vibe-Trading into OpenTerm (Phase 15 follow-up: all OHLCV factors, not the first 29).

    uv run --project backend python scripts/port_vibe_alphas.py <path to a Vibe-Trading checkout>

Reads `agent/src/factors/{base.py,zoo/<family>/*.py}` (MIT; Qlib Alpha158 parts Apache-2.0, see THIRD_PARTY.md) and writes
  * backend/openterm/quantlib/alpha/base.py           the operator library (import line + header only)
  * backend/openterm/quantlib/alpha/zoo/<family>/*.py  one module per factor that OpenTerm's panel can feed (import line + header only)
  * backend/openterm/quantlib/alpha/zoo_index.json      id / family / file / inputs / warm-up for every ported factor (`core` = the first 29)
  * docs/ALPHA_SKIPPED.md                               every factor that was NOT ported, with the reason

Idempotent: the same input gives byte-identical output. The files are never edited by hand; a factor is skipped only by the rules in
`skip_reason` (or `RUNTIME_SKIPS`, found by running the factor on the cross-check panel), never silently.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALPHA = ROOT / "backend" / "openterm" / "quantlib" / "alpha"
FAMILIES = ("alpha101", "qlib158", "academic", "gtja191", "fundamental")
PANEL_FIELDS = {"open", "high", "low", "close", "volume", "vwap", "amount"}  # vwap / amount are built from OHLCV by `extend_panel`

# The 29 factors OpenTerm shipped first (`core`): the default of ALPHA, so its run time does not grow with the zoo.
CORE = {
    "alpha101": (1, 2, 3, 4, 6, 9, 12, 13, 16, 21, 33, 34, 101),
    "qlib158": ("roc10", "std20", "ma20", "beta10", "resi10", "rsqr20", "rank20", "corr10", "rsv10", "wvma20"),
    "academic": ("strev", "illiq", "retskew", "mkt_rf", "rmw", "smb"),
}
CORE_IDS = {f"alpha101_{n:03d}" for n in CORE["alpha101"]} | {f"qlib158_{n}" for n in CORE["qlib158"]} | {f"academic_{n}" for n in CORE["academic"]}

# Factors the static rules cannot see: filled by running the port (id -> reason). Empty means every non-static-skipped factor runs.
RUNTIME_SKIPS: dict[str, str] = {}

# Warm-up fixes OpenTerm applies to a ported body (id -> (old text, new text, why)); the old text must occur exactly once. Each factor
# emitted a number while one of its inputs was still NaN (a NaN condition read as False; `1 ** NaN == 1`), found by
# `test_warmup_is_nan_not_a_fake_value`. The header says "Changes: warm-up mask" for these files.
MASK = "out = out.where(left.notna() & right.notna())  # OpenTerm: 1 ** NaN is 1, so rank-1 names got a value before `right` existed\n    return out"
PATCHES: dict[str, tuple[str, str]] = {
    "gtja191_010": ("    pick = ret.copy()\n", "    pick = ret.copy()\n    c = c.where(ret.notna())  # OpenTerm: a NaN RET is not `RET >= 0`; without a return the bar has no value\n"),
    "gtja191_143": ("    return out", "    out = out.where(dc.notna())  # OpenTerm: `dc > 0` is False for a NaN dc, so a name with no bars read as a flat 1.0\n    return out"),
    "gtja191_108": ("    return out", "    " + MASK),
    "gtja191_121": ("    return out", "    " + MASK),
    "gtja191_131": ("    return out", "    " + MASK),
}

HEADER = ("# Ported from HKUDS/Vibe-Trading @ {sha}, agent/src/factors/{rel} (MIT; see THIRD_PARTY.md).\n"
          "# Changes: imports only; a per-file `ruff: noqa` header covers lint (unused imports, import order, style).\n"
          "# ruff: noqa\n")


def meta_of(src: str) -> dict:
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "__alpha_meta__":
            return ast.literal_eval(node.value)
    raise ValueError("no __alpha_meta__")


def skip_reason(meta: dict, src: str, family: str) -> str | None:
    cols = set(meta.get("columns_required") or [])
    if family == "fundamental" or any(c.startswith(("fund:", "val:")) for c in cols):
        return "needs company fundamentals / valuation ratios (fund:*, val:*); OpenTerm's ALPHA panel is OHLCV only"
    if meta.get("requires_sector") or re.search(r"""panel(\.get\(|\[)['"]sector['"]""", src):
        return "needs a sector / industry map (`panel['sector']`) for industry neutralisation; the ALPHA panel carries no classification"
    if "benchmark_close" in src:
        return "needs a benchmark index close series (`panel['benchmark_close']`); the ALPHA panel has stock bars only"
    if meta.get("extras_required"):
        return f"needs extra series {', '.join(meta['extras_required'])} (Fama-French style factor returns) that the panel lacks"
    odd = sorted(c for c in cols if c not in PANEL_FIELDS)
    if odd:
        return f"needs data fields OpenTerm lacks: {', '.join(odd)}"
    return None


def main(vibe: Path) -> int:
    sha = subprocess.run(["git", "-C", str(vibe), "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    fac = vibe / "agent" / "src" / "factors"
    # operator library: Vibe's base with the import line pointed at OpenTerm's backend shim
    base = (fac / "base.py").read_text(encoding="utf-8").replace("from src.factors._backend import", "from openterm.quantlib.alpha._backend import")
    first = '"""Alpha Zoo base operators.\n'
    assert base.startswith(first)
    base = first + f"Ported from HKUDS/Vibe-Trading @ {sha}, agent/src/factors/base.py (MIT; see THIRD_PARTY.md).\nChanges: imports only.\n" + base[len(first):]
    (ALPHA / "base.py").write_text(base, encoding="utf-8")

    index, skipped, total = [], [], 0
    for family in FAMILIES:
        files = sorted(p for p in (fac / "zoo" / family).glob("*.py") if p.name != "__init__.py")
        outdir = ALPHA / "zoo" / family
        for p in files:
            total += 1
            src = p.read_text(encoding="utf-8")
            meta = meta_of(src)
            fid = meta["id"]
            why = skip_reason(meta, src, family) or RUNTIME_SKIPS.get(fid)
            if why:
                skipped.append((family, fid, p.name, why))
                continue
            outdir.mkdir(parents=True, exist_ok=True)
            (outdir / "__init__.py").touch()
            body = src.replace("from src.factors.base import", "from openterm.quantlib.alpha.base import")
            assert "from src." not in body and "import src." not in body, p
            head = HEADER.format(sha=sha, rel=f"zoo/{family}/{p.name}")
            if fid in PATCHES:
                old, new = PATCHES[fid]
                assert body.count(old) == 1, fid
                body = body.replace(old, new)
                head = head.replace("Changes: imports only;", "Changes: imports and a warm-up NaN mask (see PATCHES in scripts/port_vibe_alphas.py);")
            (outdir / p.name).write_text(head + body, encoding="utf-8")
            index.append({"id": fid, "family": family, "file": f"openterm/quantlib/alpha/zoo/{family}/{p.name}",
                          "columns_required": list(meta["columns_required"]), "decay_horizon": meta.get("decay_horizon"),
                          "min_warmup_bars": meta.get("min_warmup_bars"), "core": fid in CORE_IDS})
    assert {z["id"] for z in index} >= CORE_IDS, CORE_IDS - {z["id"] for z in index}
    (ALPHA / "zoo_index.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    (ALPHA / "SOURCE").write_text(f"{sha}\n{len(index)}\n{len(skipped)}\n", encoding="utf-8")

    by_reason: dict[str, list[str]] = {}
    for _, fid, _, why in skipped:
        by_reason.setdefault(why, []).append(fid)
    lines = ["# Alpha Zoo: factors not ported", "",
             f"Generated by `scripts/port_vibe_alphas.py` from HKUDS/Vibe-Trading @ `{sha}`. Vibe's zoo has {total} factors; OpenTerm ports "
             f"{len(index)} and skips {len(skipped)}. A factor is skipped only when its inputs are data the ALPHA panel does not have "
             "(the panel is OHLCV bars of the chosen universe). Nothing is approximated silently: `vwap` and `amount` are built from the "
             "bars by `extend_panel` (see `docs/specs/PHASE_15.md`).", "",
             "| Reason | Count |", "|---|---|"]
    lines += [f"| {why} | {len(ids)} |" for why, ids in sorted(by_reason.items(), key=lambda kv: -len(kv[1]))]
    lines += ["", "| Factor | Family | Reason |", "|---|---|---|"]
    lines += [f"| `{fid}` | {fam} | {why} |" for fam, fid, _, why in skipped]
    (ROOT / "docs" / "ALPHA_SKIPPED.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    per = {f: sum(1 for z in index if z["family"] == f) for f in FAMILIES}
    print(f"ported {len(index)} of {total}; skipped {len(skipped)}; by family {per}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
