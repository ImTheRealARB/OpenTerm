"""Ports Vibe-Trading's 30 swarm presets into OpenTerm (Phase 20 step 6).

    cd backend
    uv run python ../scripts/port_vibe_presets.py <vibe checkout or its presets folder>

Reads `agent/src/swarm/presets/*.yaml` from HKUDS/Vibe-Trading (MIT, commit 8172827; licence text in THIRD_PARTY.md) and writes
  * backend/openterm/ai/presets/<file>.yaml   one OpenTerm preset per Vibe preset (loaded by `swarm.all_presets`)
  * docs/PHASE_20_PRESETS.md                  the report: code mapping, coverage, every sentence the rules cut and how
It is idempotent: the same input gives byte-identical output, so a re-run after the tool set or the skill library grows only changes what the
new tools make possible. Nothing here is hand-edited per preset; the only per-preset input is the code table `CODES` and `OVERRIDES` (empty).

What the rules do (Vibe's prompts were written for a desk with a shell, file access and the web; OpenTerm has none of the three):
  1. Tool names are mapped (`TOOL_MAP`). `bash read_file write_file edit_file` are never allowed. `web_search read_url` are not built.
  2. A *sentence* (or list item) of a system prompt or task prompt that tells the model to run code, read or write files, browse the web, call a
     tool OpenTerm lacks, or call a function of a Vibe tool that OpenTerm's version lacks, is found by regex (`MARKERS`). A flagged list item with a bold
     label keeps its label with a stub ("not available here"); any other flagged sentence is cut. The list that a cut sentence introduces ("in
     bash:" and its bullets) goes with it.
  3. A role that lost a capability gets a short "OpenTerm tool notes" section at the end of its prompt saying so; if code was cut it gains the `quant`
     tool (the one analytics tool that runs jobs). A role that lost web access gets the data tools that match its subject (`WEB_REPLACEMENTS`).
  4. Coverage is computed: FULL = nothing was cut; PARTIAL = something was cut (the preset lists what, with the roles); UNAVAILABLE = a role that
     reads no upstream notes is left with no data tool at all (it would run ungrounded) or the preset is in `OVERRIDES`.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from openterm.ai import skills as skill_lib  # noqa: E402
from openterm.ai import swarm  # noqa: E402
from openterm.ai import tools as toolbox  # noqa: E402

COMMIT = "8172827"
OUT_DIR = ROOT / "backend" / "openterm" / "ai" / "presets"
REPORT = ROOT / "docs" / "PHASE_20_PRESETS.md"

# --- the code of each preset (uppercase, at most 14 characters, unique, not one of the five built-in desks) ------------------------------------
CODES = {
    "commodity_research_team": "COMMODITY", "convertible_bond_team": "CONVERT", "credit_research_team": "CREDIT",
    "crypto_research_lab": "CRYPTOLAB", "crypto_trading_desk": "CRYPTODESK", "derivatives_strategy_desk": "DERIVS",
    "earnings_research_desk": "EARNDESK", "equity_research_team": "EQRESEARCH", "etf_allocation_desk": "ETFALLOC",
    "event_driven_task_force": "EVENTDRIVEN", "factor_research_committee": "FACTORS", "fund_selection_panel": "FUNDSEL",
    "fundamental_research_team": "FUNDAMENTAL", "geopolitical_war_room": "GEOPOL", "global_allocation_committee": "GLOBALLOC",
    "global_equities_desk": "GLOBALEQ", "investment_committee": "INVCOMM", "macro_rates_fx_desk": "RATESFX",
    "macro_strategy_forum": "MACROFORUM", "ml_quant_lab": "MLQUANT", "pairs_research_lab": "PAIRS",
    "portfolio_review_board": "PORTREVIEW", "quant_strategy_desk": "QUANTDESK", "risk_committee": "RISKCOMM",
    "sector_rotation_team": "SECTORROT", "sentiment_intelligence_team": "SENTIMENT", "social_alpha_team": "SOCIAL",
    "statistical_arbitrage_desk": "STATARB", "technical_analysis_panel": "TECHPANEL", "value_investing_committee": "VALUEINV",
}
BUILT_IN = set(swarm.PRESETS)
OVERRIDES: dict[str, tuple[str, str]] = {}  # code -> (coverage, reason). Empty: the rules decide.

# --- variable examples ------------------------------------------------------------------------------------------------------------------
# Vibe's variable descriptions give China A-share examples ("600519.SH Kweichow Moutai", "A-shares, Hong Kong"). OpenTerm's owner works in US and Indian
# markets, so the examples shown in the SWARM variable form are swapped for AAPL, RELIANCE.NS and "US equities, Indian equities". Plain ordered
# find-and-replace on the DESCRIPTION text only (never a role prompt, never a variable name): most specific phrase first, so a long phrase is replaced
# before the shorter one inside it. Descriptions about a China-only subject (China bond market, A-share convertible bonds) are left alone on purpose:
# those desks are about China and the example is the subject, not a default.
EXAMPLE_SWAPS: tuple[tuple[str, str], ...] = (
    ("A-shares, Hong Kong, global multi-asset, crypto", "US equities, Indian equities, global multi-asset, crypto"),
    ("A-shares, Hong Kong, global multi-asset", "US equities, Indian equities, global multi-asset"),
    ("A-shares, Hong Kong, US equities", "US equities, Indian equities"),
    ("A-shares, Hong Kong, US, crypto", "US equities, Indian equities, crypto"),
    ("A-shares, Hong Kong, US", "US equities, Indian equities"),
    ("A-shares, Hong Kong/US equities", "US equities, Indian equities"),
    ("A-shares, Hong Kong, crypto", "US equities, Indian equities, crypto"),
    ("A-shares, Hong Kong, Crypto", "US equities, Indian equities, crypto"),
    ("A-shares / Hong Kong / US equities / Chinese ADRs", "US equities / Indian equities"),
    ("A-shares / HK / US / crypto / CSI 300", "US equities / Indian equities / crypto / S&P 500 / Nifty 50"),
    ("default A-shares; can specify HK/US", "default US equities; can specify Indian equities"),
    ("default: A-shares; options: global multi-asset, HK/US equities, A-shares + HK",
     "default: US equities; options: global multi-asset, Indian equities, US + Indian equities"),
    ("AAPL.US, NVDA.US, 700.HK, 600519.SH", "AAPL, NVDA, RELIANCE.NS"),
    ("600519.SH Kweichow Moutai, BTC-USDT, AAPL", "AAPL, RELIANCE.NS, BTC-USDT"),
    ("stock code or name, e.g.: 600519 Kweichow Moutai", "ticker or name, e.g.: AAPL, RELIANCE.NS"),
    ("Tencent, NVDA, Moutai", "AAPL, RELIANCE.NS"),
    ("BTC, CSI 300 ETF, AAPL", "BTC, AAPL, RELIANCE.NS"),
    ("A-share tech", "Indian tech"),
    ("CSI 300", "Nifty 50"),
    ("quant hedge / QDII", "quant hedge / international"),
)


def neutral_examples(description: str) -> str:
    """A variable description with its China-market examples replaced by US / Indian ones (deterministic; text with no match is unchanged)."""
    for old, new in EXAMPLE_SWAPS:
        description = description.replace(old, new)
    return description


# --- tools ------------------------------------------------------------------------------------------------------------------------------------
TOOL_MAP = {  # Vibe tool -> OpenTerm tools
    "load_skill": ["skill", "skills"],  # a role that may open a playbook may also search the library for one
    "get_market_data": ["history", "quote", "indicators"],
    "factor_analysis": ["quant"], "quantlib_call": ["quant"],
    "backtest": ["backtest_run", "strategy_check"],
    "get_financial_statements": ["fa"], "get_fundamentals": ["fa", "profile"], "get_stock_profile": ["profile"], "get_stock_news": ["news"],
    "get_options_chain": ["options_chain"], "options_pricing": ["option_price"], "options_payoff": ["option_payoff"],
    "technical_indicators": ["indicators"], "screen_market": ["screener"], "etf_holdings": ["etf"], "orderbook_depth": ["crypto_depth"],
    "financial_rigor": ["rigor"], "report_audit": ["rigor"],
}
SHELL_TOOLS = {"bash", "read_file", "write_file", "edit_file"}  # never allowed; silent in the tool list (every Vibe agent lists them)
CUT_TOOLS = {  # Vibe tool -> the kind of capability lost
    "web_search": "web", "read_url": "web", "pattern": "pattern",
    "get_fund_flow": "china", "get_margin_trading": "china", "get_research_reports": "china", "analyze_trade_journal": "journal",
}
# Text rewrites for tool names that survive in prose. Identifiers with an underscore are unambiguous; the plain words need backticks.
NAME_REWRITES = [
    (r"\bget_market_data\b", "history"), (r"\bget_financial_statements\b", "fa"), (r"\bget_stock_profile\b", "profile"),
    (r"\bget_stock_news\b", "news"), (r"\bget_options_chain\b", "options_chain"), (r"\boptions_pricing\b", "option_price"),
    (r"\boptions_payoff\b", "option_payoff"), (r"\btechnical_indicators\b", "indicators"), (r"\bscreen_market\b", "screener"),
    (r"\betf_holdings\b", "etf"), (r"\borderbook_depth\b", "crypto_depth"), (r"\bfinancial_rigor\b", "rigor"), (r"\breport_audit\b", "rigor"),
    (r"\bget_fundamentals\b", "profile"), (r"\bfactor_analysis\b", "quant (fn fact)"), (r"`backtest`", "`backtest_run`"),
    (r"\bload_skill\b(?!\()", "skill"),
]
SKILL_ALIASES = {  # Vibe skill -> an OpenTerm playbook that covers the same ground; anything else is not installed (step 7 may add more)
    "risk-analysis": "risk", "valuation-model": "valuation", "macro-analysis": "macro", "global-macro": "macro", "earnings-forecast": "earnings",
    "options-strategy": "options", "options-advanced": "options",
}

# --- what to cut ------------------------------------------------------------------------------------------------------------------------------
MARKERS = [  # (kind, regex): a sentence matching any of these is flagged
    ("code", r"\bbash\b|\bread_file\b|\bwrite_file\b|\bedit_file\b|\bquantlib_call\b|\bsrc\.quantlib\b|\bfrom src\b|\bimport \w+|\bsignal_engine\b"),
    ("code", r"\b(pandas|numpy|scipy|statsmodels|sklearn|matplotlib|arch)\b|\.py\b|\bPython\b|\bsandbox\b"),
    ("calc", r"\bthree_scenario\b|\bverify_valuation\b|command=\"calc\""),
    ("web", r"\bread_url\b|\bweb_search\b|\bweb-reader\b|\bbrowse\b"),
    ("pattern", r"\bpattern tool\b|`pattern`"),
    ("journal", r"\banalyze_trade_journal\b"),
]
LIMITS = {
    "web": "NO WEB ACCESS: web search and page reading are not built, so these roles use only OpenTerm's own data tools",
    "code": "NO CODE EXECUTION: steps that ran Python or read files are cut; the quant tool covers the risk, factor, calculator, alpha and regime jobs",
    "calc": "NO VALUATION CALCULATOR: DCF, three-scenario and verify-valuation functions are not available (the rigor tool only checks that parts add up)",
    "pattern": "NO CHART-PATTERN TOOL: harmonic, Elliott and similar pattern scans are not available",
    "china": "NO CHINA-ONLY DATA: fund flows, margin trading and broker research reports have no OpenTerm source",
    "blind": "NO DATA SOURCE: these roles have no OpenTerm tool for what they study (their Vibe tools were shell, files or web), so they report their study as unavailable",
    "journal": "NO TRADE JOURNAL: fills and broker blotters cannot be read, so execution quality is not assessable",
}
NOTES = {  # the line a role gets under "OpenTerm tool notes"
    "web": "You have no web access (no search, no page reading). Anything that would have come from a web page is unavailable: say so; do not guess it.",
    "code": "You cannot run code or read files. Where a step asked for your own computation, use the `quant` tool if it covers the quantity "
            "(fn risk, fact, ql, alpha, regime); otherwise state that the figure is unavailable. Never compute a statistic from memory.",
    "calc": "There is no DCF or scenario calculator. Show any valuation arithmetic as plain steps from sourced inputs, and label assumed inputs as assumptions.",
    "pattern": "There is no chart-pattern tool. Describe patterns only from the `history` and `indicators` data, and say it is a reading, not a scan.",
    "china": "There are no tools for fund flows, northbound flows, margin balances or broker research reports. Say they are unavailable; do not estimate them.",
    "journal": "There is no trade journal or blotter. Report execution quality as not assessable instead of inventing fills.",
    "blind": "You have no data tool for this study. Say in two lines that it is unavailable here and why; do not write it from memory.",
}
WEB_REPLACEMENTS = [  # (pattern over the role's title + prompt, tools to add): data tools that stand in for pages a role used to read
    (r"yield curve|treasur|fomc|central bank|monetary policy|interest rate|\brates\b", ["rates", "macro", "calendar"]),
    (r"\bcpi\b|inflation|\bgdp\b|\bpmi\b|unemployment|macro", ["macro", "calendar"]),
    (r"earnings|guidance|\beps\b", ["calendar", "research"]),
    (r"news|headline|announcement|sentiment|event|geopolit|policy", ["news"]),
    (r"insider", ["insiders"]), (r"13f|institutional|holders|ownership", ["holders"]),
    (r"funding rate|open interest|perpetual|liquidation|crypto", ["crypto_funding"]),
    (r"\boil\b|crude|natural gas|opec|\beia\b|energy|\bpower\b", ["energy"]),
    (r"prediction market|polymarket|kalshi|odds", ["pred"]),
    (r"\bsec\b|10-k|10-q|filing|prospectus|regulat", ["filings"]),
]
MAX_TOOLS = 12
DATA_TOOLS = set(toolbox.REGISTRY) - {"skill", "skills", "quant", "backtest_run", "backtest_get", "strategy_check", "rigor", "doc_search"}
STUB = {"code": "(not available here: no code execution. Use the `quant` tool where it covers it; otherwise say it is unavailable.)",
        "calc": "(not available here: there is no valuation calculator. Show the arithmetic as plain steps and label assumptions.)",
        "web": "(not available here: no web access. Say what could not be sourced.)",
        "pattern": "(not available here: there is no chart-pattern tool.)", "journal": "(not available here: there is no trade journal.)"}

BULLET = re.compile(r"^(\s*)([-*]|\d+[.)])\s+")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?:;])\s+(?=[A-Z`\"(*\[])")


class Unit:
    """One list item, one paragraph, one heading or one blank line of a prompt. `lines` keeps the original text and indentation."""

    def __init__(self, kind: str, lines: list[str]):
        self.kind, self.lines = kind, lines

    @property
    def indent(self) -> int:
        return len(self.lines[0]) - len(self.lines[0].lstrip())

    @property
    def text(self) -> str:
        return " ".join(x.strip() for x in self.lines)


def units_of(text: str) -> list[Unit]:
    out: list[Unit] = []
    for line in text.split("\n"):
        s = line.strip()
        ind = len(line) - len(line.lstrip())
        prev = out[-1] if out else None
        if not s:
            out.append(Unit("blank", [""]))
        elif s.startswith("#"):
            out.append(Unit("heading", [line]))
        elif BULLET.match(line):
            out.append(Unit("bullet", [line]))
        elif prev and prev.kind in ("para", "bullet") and (prev.kind == "para" or ind > prev.indent):
            prev.lines.append(line)  # a wrapped line of the same paragraph or list item
        else:
            out.append(Unit("para", [line]))
    return out


def flag_kinds(sentence: str) -> list[str]:
    return sorted({k for k, rx in MARKERS if re.search(rx, sentence)})


def rewrite_names(text: str) -> str:
    for rx, to in NAME_REWRITES:
        text = re.sub(rx, to, text)
    return text


def rewrite_skills(text: str, known: set[str], unresolved: Counter) -> str:
    def one(m: re.Match) -> str:
        name = m.group(1)
        target = name if name in known else SKILL_ALIASES.get(name)
        if target and target in known:
            return f'skill("{target}")'
        unresolved[name] += 1
        return f'your own knowledge of "{name}"'

    return re.sub(r'\bload_skill\(\s*["\']([^"\']+)["\']\s*\)', one, text)


def clean_prompt(text: str, known_skills: set[str], unresolved: Counter) -> tuple[str, list[dict]]:
    """Applies the cut rules and the name rewrites to one prompt. Returns the new text and the list of what was cut."""
    cuts: list[dict] = []
    units = units_of(text.replace("\r\n", "\n"))
    out: list[Unit] = []
    i = 0
    while i < len(units):
        u = units[i]
        i += 1
        if u.kind in ("blank", "heading"):
            out.append(u)
            continue
        m = BULLET.match(u.lines[0])
        marker = u.lines[0][: m.end()] if m else ""
        body = u.text[len(marker.strip()):].strip() if m else u.text
        sentences = SENTENCE_SPLIT.split(body)
        keep: list[str] = []
        intro_cut = changed = False
        for s in sentences:
            kinds = flag_kinds(s)
            if not kinds:
                keep.append(s)
                continue
            cuts.append({"kinds": kinds, "text": s, "how": ""})
            changed = True
            intro_cut = s.rstrip().endswith(":")
            if m and not keep and len(sentences) == 1 and (label := re.match(r"\*\*[^*]+\*\*", body)):  # a labelled output item keeps its label
                keep.append(f"{label.group(0)} {STUB[kinds[0]]}")
                cuts[-1]["how"] = "stubbed"
            else:
                cuts[-1]["how"] = "cut"
        if not changed:  # untouched: keep the original line breaks
            out.append(u)
        elif keep:
            out.append(Unit(u.kind, [(marker if m else " " * u.indent) + " ".join(keep)]))
        if intro_cut:  # "…in bash:" takes the list under it along
            while i < len(units) and units[i].kind == "bullet":
                cuts.append({"kinds": flag_kinds(units[i].text) or [cuts[-1]["kinds"][0]], "text": units[i].text, "how": "cut (list under a cut sentence)"})
                i += 1
    text2 = "\n".join(line for u in out for line in u.lines)
    text2 = rewrite_skills(text2, known_skills, unresolved)
    text2 = rewrite_names(text2)
    text2 = "\n".join(x.rstrip() for x in text2.split("\n"))
    text2 = re.sub(r"\n{3,}", "\n\n", text2).strip("\n")
    return text2, cuts


def single_line(text: str, known_skills: set[str], unresolved: Counter) -> tuple[str, list[dict]]:
    """Task prompts are one paragraph: same rules, sentence by sentence."""
    cuts, keep = [], []
    for s in SENTENCE_SPLIT.split(text.strip()):
        kinds = flag_kinds(s)
        if kinds:
            cuts.append({"kinds": kinds, "text": s, "how": "cut"})
        else:
            keep.append(s)
    out = rewrite_names(rewrite_skills(" ".join(keep), known_skills, unresolved)).strip()
    return out, cuts


class Literal(str):
    pass


class Dumper(yaml.SafeDumper):
    pass


Dumper.add_representer(Literal, lambda d, v: d.represent_scalar("tag:yaml.org,2002:str", str(v), style="|"))
Dumper.add_representer(str, lambda d, v: d.represent_scalar("tag:yaml.org,2002:str", v, style="|" if "\n" in v else None))
Dumper.add_representer(OrderedDict, lambda d, v: d.represent_mapping("tag:yaml.org,2002:map", v.items()))


def port_one(path: Path, known_skills: set[str]) -> tuple[OrderedDict, dict]:
    src = yaml.safe_load(path.read_text(encoding="utf-8"))
    code = CODES[path.stem]
    unresolved: Counter = Counter()
    tasks_by_agent = {t["agent_id"]: t for t in src["tasks"]}
    agents, role_info = [], []
    for a in src["agents"]:
        task = tasks_by_agent[a["id"]]
        system, cuts = clean_prompt(a["system_prompt"], known_skills, unresolved)
        tools: list[str] = []
        kinds: set[str] = {k for c in cuts for k in c["kinds"]}
        for t in a["tools"]:
            if t in SHELL_TOOLS:
                continue
            if t in CUT_TOOLS:
                kinds.add(CUT_TOOLS[t])
            elif t in TOOL_MAP:
                tools += TOOL_MAP[t]
            else:
                raise SystemExit(f"{path.name}: agent {a['id']} lists the unmapped tool {t!r}: add it to TOOL_MAP or CUT_TOOLS")
        owns_quant = "quant" in tools  # quant the role had in Vibe (factor_analysis, quantlib_call) is a data source; quant added below is not
        if kinds & {"code", "calc"}:
            tools.append("quant")
        if "web" in kinds:
            blob = (a["role"] + " " + a["system_prompt"]).lower()
            for rx, add in WEB_REPLACEMENTS:
                if re.search(rx, blob):
                    tools += add
        tools = list(dict.fromkeys(tools))[:MAX_TOOLS]  # the mapped tools come first, so a cap drops replacement tools before the role's own
        missing = [t for t in tools if t not in toolbox.REGISTRY]
        if missing:
            raise SystemExit(f"{path.name}: {a['id']} maps to unknown OpenTerm tools {missing}")
        if task.get("input_from") and "{upstream_context}" not in system:  # Vibe fills it implicitly for some roles; OpenTerm only fills the placeholder
            system += "\n\n{upstream_context}"
        blind = not task.get("input_from") and not owns_quant and not any(t in DATA_TOOLS for t in tools)  # nothing to ground this role in
        if blind:
            kinds.add("blind")
        notes = [NOTES[k] for k in ("web", "code", "calc", "pattern", "china", "journal", "blind") if k in kinds]
        if notes:
            system += "\n\n## OpenTerm tool notes\n" + "\n".join(f"- {n}" for n in notes)
        agents.append(OrderedDict(id=a["id"], role=a["role"], system_prompt=Literal(system + "\n"), tools=tools,
                                  max_iterations=swarm.DESK_ROUNDS, timeout_seconds=int(swarm.ROLE_TIMEOUT_S)))
        role_info.append({"id": a["id"], "kinds": sorted(kinds), "cuts": cuts, "tools": tools, "has_input": bool(task.get("input_from")),
                          "blind": blind})
    tasks = []
    task_cuts = []
    for t in src["tasks"]:
        prompt, cuts = single_line(t["prompt_template"], known_skills, unresolved)
        if not prompt:
            raise SystemExit(f"{path.name}: task {t['id']} is empty after the cuts")
        for c in cuts:
            c["task"] = t["id"]
        task_cuts += cuts
        d = OrderedDict(id=t["id"], agent_id=t["agent_id"], prompt_template=prompt, depends_on=list(t.get("depends_on") or []))
        if t.get("input_from"):
            d["input_from"] = OrderedDict(t["input_from"])
        tasks.append(d)
    # coverage
    limits: list[str] = []
    for kind in ("web", "code", "calc", "pattern", "china", "journal", "blind"):
        roles = [r["id"] for r in role_info if kind in r["kinds"]]
        if roles:
            limits.append(f"{LIMITS[kind]} (roles: {', '.join(roles)})")
    for c in task_cuts:  # a cut inside a task prompt is a capability cut too
        for k in c["kinds"]:
            if not any(k in r["kinds"] for r in role_info) and LIMITS[k] not in " ".join(limits):
                limits.append(f"{LIMITS[k]} (task {c['task']})")
    coverage = "PARTIAL" if limits else "FULL"
    blind = [r["id"] for r in role_info if r["blind"]]
    if len(blind) * 2 >= len(role_info):  # half the desk or more cannot be grounded: refuse instead of showing a desk that is mostly empty
        coverage = "UNAVAILABLE"
    if code in OVERRIDES:
        coverage, reason = OVERRIDES[code]
        limits = [reason] + limits
    doc = OrderedDict(
        name=src["name"], code=code, title=src["title"], description=src["description"], coverage=coverage,
        variables=[OrderedDict(name=v["name"], description=neutral_examples(v.get("description", "")), required=bool(v.get("required", True))) for v in src["variables"]],
        agents=agents, tasks=tasks)
    if limits:
        doc["limits"] = limits
    info = {"file": path.name, "code": code, "vibe": src["name"], "title": src["title"], "coverage": coverage, "limits": limits,
            "roles": role_info, "task_cuts": task_cuts, "unresolved_skills": unresolved}
    return doc, info


def header(file: str) -> str:
    return (f"# Ported from HKUDS/Vibe-Trading @ {COMMIT} (MIT) agent/src/swarm/presets/{file}\n"
            f"# Copyright 2026 HKUDS contributors; licence and NOTICE wording in THIRD_PARTY.md.\n"
            f"# Changes: generated by scripts/port_vibe_presets.py (tool names mapped to OpenTerm tools; shell, file and web steps cut by rule;\n"
            f"# `coverage` and `limits` say what is missing; rounds and timeouts set to the engine's caps). Do not edit by hand: rerun the script.\n")


def write_report(infos: list[dict], skills_known: set[str]) -> str:
    counts = Counter(i["coverage"] for i in infos)
    L = ["# Phase 20 step 6: the 30 Vibe-Trading presets, ported", "",
         f"Source: HKUDS/Vibe-Trading @ {COMMIT} (MIT), `agent/src/swarm/presets/*.yaml`. Generated by `scripts/port_vibe_presets.py` "
         "(rerun it to regenerate this file and `backend/openterm/ai/presets/`). Do not edit by hand.", "",
         f"Coverage: FULL {counts['FULL']}, PARTIAL {counts['PARTIAL']}, UNAVAILABLE {counts['UNAVAILABLE']} (of {len(infos)}).", "",
         "## Preset code to Vibe name", "", "| Code | Vibe preset | Vibe file | Title | Roles | Coverage |", "|---|---|---|---|---|---|"]
    for i in sorted(infos, key=lambda x: x["code"]):
        L.append(f"| {i['code']} | {i['vibe']} | {i['file']} | {i['title']} | {len(i['roles'])} | {i['coverage']} |")
    L += ["", "## What each preset cannot do", "", "| Code | Coverage | Missing capability (roles) |", "|---|---|---|"]
    for i in sorted(infos, key=lambda x: x["code"]):
        L.append(f"| {i['code']} | {i['coverage']} | {'<br>'.join(x.replace('|', '/') for x in i['limits']) or '-'} |")
    L += ["", "## Flagged sentences and how each was resolved", "",
          "A sentence is flagged by regex when it tells the model to run code, touch files, browse, call a tool OpenTerm lacks, or call a function of a Vibe tool "
          "OpenTerm's version lacks. `cut` = removed; `stubbed` = a labelled output item kept with a \"not available here\" stub; "
          "`cut (list under a cut sentence)` = bullets introduced by a cut sentence. Text is shortened to 150 characters.", ""]
    for i in sorted(infos, key=lambda x: x["code"]):
        rows = [(r["id"], c) for r in i["roles"] for c in r["cuts"]] + [(f"task {c['task']}", c) for c in i["task_cuts"]]
        if not rows:
            continue
        L += [f"### {i['code']} ({i['file']})", "", "| Where | Kind | Resolution | Sentence |", "|---|---|---|---|"]
        for where, c in rows:
            t = re.sub(r"\s+", " ", c["text"]).replace("|", "/")
            L.append(f"| {where} | {'+'.join(c['kinds'])} | {c['how']} | {t[:150]}{'...' if len(t) > 150 else ''} |")
        L.append("")
    unresolved: Counter = Counter()
    for i in infos:
        unresolved.update(i["unresolved_skills"])
    L += ["## Playbooks (skills) the prompts named", "",
          f"Installed in OpenTerm now: {', '.join(sorted(skills_known))}. Aliases used: " + ", ".join(f"{k} to {v}" for k, v in SKILL_ALIASES.items()) + ". "
          "A call to any other playbook was rewritten to `your own knowledge of \"name\"`; step 7 (skills) may install more and a rerun of the script picks them up. "
          "Not installed (count of mentions):", "",
          ", ".join(f"{k} ({v})" for k, v in sorted(unresolved.items(), key=lambda x: (-x[1], x[0]))), "",
          "## Tool map", "", "| Vibe tool | OpenTerm tool(s) |", "|---|---|"]
    for k, v in TOOL_MAP.items():
        L.append(f"| {k} | {', '.join(v)} |")
    for k in sorted(SHELL_TOOLS):
        L.append(f"| {k} | never allowed (cut; `quant` added to a role whose code steps were cut) |")
    for k, kind in CUT_TOOLS.items():
        L.append(f"| {k} | none ({kind}) |")
    L += ["", "Roles that lost web access also gain data tools that match their subject (rule `WEB_REPLACEMENTS` in the script); each role is capped at "
          f"{MAX_TOOLS} tools. Every task is capped at the engine's {swarm.DESK_ROUNDS} rounds and {int(swarm.ROLE_TIMEOUT_S)} s.", ""]
    return "\n".join(L)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: port_vibe_presets.py <Vibe-Trading checkout or its agent/src/swarm/presets folder>")
    base = Path(sys.argv[1])
    src_dir = base / "agent" / "src" / "swarm" / "presets" if (base / "agent").is_dir() else base
    files = sorted(src_dir.glob("*.yaml"))
    if len(files) != 30:
        raise SystemExit(f"expected 30 preset files in {src_dir}, found {len(files)}")
    codes = [CODES[f.stem] for f in files]  # KeyError = a new Vibe file without a code
    for c in codes:
        if not swarm.CODE_RE.match(c) or len(c) > 14 or c in BUILT_IN:
            raise SystemExit(f"bad preset code {c}")
    if len(set(codes)) != len(codes):
        raise SystemExit("duplicate preset codes")
    known = set(skill_lib.names())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    infos = []
    for f in files:
        doc, info = port_one(f, known)
        body = yaml.dump(doc, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=1_000_000, default_flow_style=False)
        (OUT_DIR / f.name).write_bytes((header(f.name) + body).encode("utf-8").replace(b"\r\n", b"\n"))
        back = yaml.safe_load(body)
        if [x["system_prompt"] for x in back["agents"]] != [x["system_prompt"] for x in doc["agents"]]:
            raise SystemExit(f"{f.name}: a prompt does not survive the YAML round trip")
        swarm.parse_preset(back, source=f.name)  # the engine's own validation: tools exist, DAG acyclic, variables have a source
        infos.append(info)
    REPORT.write_bytes(write_report(infos, known).encode("utf-8").replace(b"\r\n", b"\n") + b"\n")
    counts = Counter(i["coverage"] for i in infos)
    print(f"ported {len(infos)} presets: FULL {counts['FULL']}, PARTIAL {counts['PARTIAL']}, UNAVAILABLE {counts['UNAVAILABLE']}")
    for i in sorted(infos, key=lambda x: x["code"]):
        print(f"  {i['code']:<12} {i['coverage']:<11} cuts={sum(len(r['cuts']) for r in i['roles']) + len(i['task_cuts']):<3} {i['file']}")


if __name__ == "__main__":
    main()
