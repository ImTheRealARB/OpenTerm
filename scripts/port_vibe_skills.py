#!/usr/bin/env python3
"""Port Vibe-Trading's skills to OpenTerm playbooks (Phase 20, step 7).

    cd backend
    uv run python ../scripts/port_vibe_skills.py <path to Vibe-Trading checkout or its agent/src/skills> [--check]

Source: HKUDS/Vibe-Trading `agent/src/skills/<name>/SKILL.md` @ 8172827, MIT (see THIRD_PARTY.md).
Output: `backend/openterm/ai/skills/<name>.md` for every skill that survives triage, `docs/PHASE_20_SKIPPED.md` for the rest.
Idempotent: the same input gives byte-identical output; stale ported files are removed. `--check` writes nothing and exits 1 on any difference.

Triage, in this order (the first rule that fires skips the skill and its reason is written down):
  1. Written in Chinese (3 percent or more CJK characters), or about China A-share / Stock Connect data and rules.
  2. A data-library recipe (category `data-source`: pip packages, scripts, API keys). OpenTerm reads data through its own tools.
  3. After the rewrite rules below, more than MAX_HITS steps still depend on something OpenTerm does not have.
  4. The finished text still names a tool OpenTerm lacks (cannot happen unless a rule has a gap; it is the safety net).
Rewrite rules (scripted, never by hand):
  - Vibe tool names that have an OpenTerm equivalent are renamed (TOOL_MAP). The new name must exist in `ai.tools.REGISTRY`.
  - A prose line that names a tool OpenTerm lacks (file, shell, web search, Vibe-only stores, anything with orders) is replaced by one note that does
    not name it. A fenced block that does is dropped. Table rows get the tool named by its class ("a file tool").
  - Shell blocks and "run python" lines say OpenTerm cannot run scripts and point to the `quant` tool, or state the limit.
  - Dependency / install / config / output-contract sections for Vibe's own backtest harness are removed.
  - English files under `references/` are appended as `## Reference: ...` sections; other `references/` mentions are dropped.
  - A section longer than SECTION_LIMIT is split at a blank line outside code and tables, so that the `skill` tool's `section` argument reaches all of it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "backend" / "openterm" / "ai" / "skills"
SKIPPED_DOC = ROOT / "docs" / "PHASE_20_SKIPPED.md"
THIRD_PARTY = ROOT / "THIRD_PARTY.md"

COMMIT = "8172827"
SOURCE = "HKUDS/Vibe-Trading"
MARK = "Ported from HKUDS/Vibe-Trading"  # the first words of every ported file: tests and this script find ported files by it
MAX_HITS = 5  # steps that may be cut from a skill before it is skipped
SECTION_LIMIT = 3800  # characters; the runtime cap (skills.MAX_CHARS) is 4,200
CJK = re.compile(r"[㐀-鿿豈-﫿]")

# Every tool name Vibe-Trading registers (agent/src/tools, commit 8172827).
VIBE_TOOLS = ["adapt_strategy", "add_goal_evidence", "alpha_bench", "alpha_compare", "alpha_zoo", "analyze_image", "analyze_trade_journal", "background_run", "backtest", "bash", "cancel_background", "cashflow_performance", "check_background", "compact", "create_hypothesis", "delete_skill", "edit_file", "etf_holdings", "etoro_cancel_close_order", "etoro_close_position", "etoro_copy_close", "etoro_copy_poll", "etoro_copy_precheck", "etoro_copy_start", "etoro_edit_position_stops", "etoro_search_instruments", "extract_shadow_strategy", "factor_analysis", "financial_rigor", "generate_backtest_config", "get_block_trades", "get_br_market_data", "get_cn_announcements", "get_cn_macro_series", "get_dragon_tiger", "get_financial_statements", "get_fund_flow", "get_fund_nav", "get_fundamentals", "get_institutional_holdings", "get_lockup_expiry", "get_macro_series", "get_margin_trading", "get_market_data", "get_northbound_flow", "get_options_chain", "get_research_artifact", "get_research_goal", "get_research_reports", "get_sec_filings", "get_sector_info", "get_shareholder_count", "get_southbound_flow", "get_stock_news", "get_stock_profile", "get_strategy_evidence", "get_taiwan_stock_data", "gildata_fin_query", "gildata_stock_selection", "iwencai_search", "link_autopilot_backtest", "link_backtest", "list_backtest_runs", "list_strategies", "load_skill", "load_tools", "options_payoff", "options_pricing", "orderbook_depth", "paper_trade_step", "patch_skill", "pattern", "pixel_office", "portfolio_risk_xray", "portfolio_summary", "prediction_market", "propose_mandate_profiles", "quantlib_call", "query_strategies", "read_document", "read_file", "read_run_artifact", "read_url", "refresh_strategy_evidence", "remember", "render_shadow_report", "report_audit", "research_papers", "run_research_autopilot", "run_shadow_backtest", "run_swarm", "save_research_artifact", "save_skill", "scaffold_signal_engine", "scan_shadow_signals", "scheduled_research", "screen_market", "sdm_decay_scan", "sdm_register", "sdm_status", "search_broker_reports", "search_hypotheses", "search_research_artifacts", "search_symbol", "sentiment", "session_search", "skill_file", "start_research_goal", "technical_indicators", "tencent_raw", "trading_acc_cash_flow", "trading_account", "trading_cancel_order", "trading_capital_distribution", "trading_capital_flow", "trading_check", "trading_connections", "trading_earnings_calendar", "trading_financials", "trading_history", "trading_history_deals", "trading_orders", "trading_place_order", "trading_positions", "trading_quote", "trading_rehab", "trading_select_connection", "update_hypothesis", "update_research_goal", "update_research_goal_status", "web_search", "write_file"]
# Ordinary English words that are also tool names: only a backticked `word` or `word(` counts as naming the tool ("bash" is rare enough to count anywhere).
GENERIC = {"backtest", "pattern", "sentiment", "compact", "remember", "bash"}

# Vibe name -> OpenTerm tool. Used only where the meaning is the same; each target must exist in tools.REGISTRY (checked at run time).
TOOL_MAP = {
    "load_skill": "skill", "get_sec_filings": "filings", "get_financial_statements": "fa", "get_stock_news": "news", "get_market_data": "history",
    "screen_market": "screener", "financial_rigor": "rigor", "get_options_chain": "options_chain", "options_pricing": "option_price",
    "options_payoff": "option_payoff", "get_macro_series": "macro", "get_stock_profile": "profile", "technical_indicators": "indicators",
    "etf_holdings": "etf", "get_institutional_holdings": "holders", "prediction_market": "pred", "orderbook_depth": "crypto_depth",
    "run_backtest": "backtest_run", "backtest": "backtest_run", "factor_analysis": "quant",
}
# Class of every other tool, for the sentence that replaces a step that needed it. The sentence never names the tool.
LIMIT_CLASS = {
    "bash": "a shell", "read_file": "a file tool", "write_file": "a file tool", "edit_file": "a file tool", "read_document": "a file tool",
    "read_run_artifact": "a file tool", "web_search": "web search", "read_url": "a web page reader", "analyze_trade_journal": "a trade journal tool",
    "run_swarm": "a Vibe-Trading-only tool",
}

# A skill that names any of these is skipped, however few steps it is: they read a journal, place orders, or are out of scope for OpenTerm.
HARD_TOOLS = {t for t in VIBE_TOOLS if t.startswith(("trading_", "etoro_", "paper_trade", "propose_mandate"))} | {
    "analyze_trade_journal", "extract_shadow_strategy", "run_shadow_backtest", "scan_shadow_signals", "render_shadow_report", "pixel_office"}

NOTE_LIMIT = "(Step omitted: it needs {what}, which OpenTerm does not have. Say so if the question depends on it.)"
NOTE_SCRIPT = "(OpenTerm cannot run scripts here. Use the `quant` tool where it covers the calculation, otherwise state the limit.)"
NOTE_HARNESS = "(Step omitted: it refers to Vibe-Trading's own files or backtest harness, which OpenTerm does not have.)"
NOTE_SHELL = "(Shell commands omitted: OpenTerm runs no shell. Use the `quant` tool where it covers the calculation, otherwise state the limit.)"
NOTE_CODE = "(Code omitted: it called a tool OpenTerm does not have. The method above still applies.)"
NOTE_LONG_CODE = "(A long code example is omitted here; the method described above still applies.)"

LEAD = ("Limits: this assistant reads market data through its tools. It cannot run code, a shell, or read files, so code blocks below are reference only "
        "(use the `quant` tool where it covers a calculation). This is analysis, not personalised investment advice.")

DROP_HEADINGS = re.compile(r"^(dependencies|install(ation)?|setup|prerequisites|signal convention|run(ning)?( command)?|output( files)?|"
                           r"example `?config\.?json`?|`?config\.?json`?.*|file structure)$", re.IGNORECASE)
CHINA = re.compile(r"A[- ]?shares?|A股|Stock Connect|Northbound|Southbound|Tushare|AKShare|Eastmoney|mootdx|\bTDX\b|Shenzhen|Shanghai|H-share|\.SH\b|\.SZ\b|CSI ?300|ChiNext|STAR Market", re.IGNORECASE)
HARNESS = re.compile(r"signal_engine|config\.json|\brun_dir\b|\bartifacts/|\bscripts/\S|\bsrc/\S|\bagent/\S|\btemplates/\S|SKILL\.md|[Vv]ibe-[Tt]rading|\bswarm\b", re.IGNORECASE)
SCRIPT = re.compile(r"\bpython3?\s+[\w./-]+\.py\b|\bpython3?\s+-m\b|\bpip3? install\b|\buv (?:run|pip)\b")
PIP_ONLY = re.compile(r"^\s*(?:#.*|pip3? install\b.*|uv pip install\b.*|python3? -m pip\b.*)?$")


# --- small helpers -----------------------------------------------------------------------------------------------------------------------
def split_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n?", raw, re.DOTALL)
    if not m:
        return {}, raw
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if _ and k.strip() and not line.startswith(" "):
            fm[k.strip()] = v.strip().strip("\"'")
    return fm, raw[m.end():]


def blocks(lines: list[str]) -> list[tuple[str, str, list[str]]]:
    """Cut lines into ('prose', '', lines) and ('fence', language, lines including the ``` lines)."""
    out: list[tuple[str, str, list[str]]] = []
    cur: list[str] = []
    in_fence, lang = False, ""
    for ln in lines:
        if ln.lstrip().startswith("```"):
            if not in_fence:
                if cur:
                    out.append(("prose", "", cur))
                cur, in_fence, lang = [ln], True, ln.strip()[3:].strip().split(" ")[0].lower()
            else:
                cur.append(ln)
                out.append(("fence", lang, cur))
                cur, in_fence = [], False
        else:
            cur.append(ln)
    if cur:
        out.append(("fence" if in_fence else "prose", lang if in_fence else "", cur))
    return out


def names_in(text: str, registry: set[str] | None = None) -> set[str]:
    """Vibe tool names that `text` names, minus names that are also OpenTerm tools."""
    prose = "\n".join("\n".join(b) for kind, _, b in blocks(text.splitlines()) if kind == "prose")
    hit: set[str] = set()
    for t in VIBE_TOOLS:
        if t == "bash":
            found = re.search(r"\bbash\b", prose) is not None or re.search(r"^\s*```(?:bash|sh|shell|powershell|cmd)\b", text, re.MULTILINE) is not None
        elif t in GENERIC:
            found = re.search(rf"`{t}`|`{t}\(", prose) is not None
        else:
            found = re.search(rf"\b{t}\b", text) is not None
        if found:
            hit.add(t)
    return hit - (registry or set())


def _tool_token(name: str) -> re.Pattern:
    """A tool named in prose: `name`, `name(...)`, or (for snake_case names) the bare identifier."""
    if name in GENERIC and name != "bash":
        return re.compile(rf"`{name}`|`{name}\(\)?`?")
    return re.compile(rf"`{name}(?:\([^`]*\))?`|\b{name}\b")


def split_big(lines: list[str], limit: int) -> list[str]:
    """Split every `##` / `###` section longer than `limit` characters into siblings 'Title (part 2)', ... Cuts fall on blank lines outside code fences,
    so a table or a code block stays whole (a single block longer than `limit` stays one piece)."""
    segs: list[tuple[int, str, list[str]]] = []
    cur: tuple[int, str, list[str]] = (0, "", [])
    fenced = False
    for ln in lines:
        if ln.lstrip().startswith("```"):
            fenced = not fenced
        m = None if fenced else re.match(r"^(#{2,4})\s+(.+?)\s*$", ln)
        if m:
            segs.append(cur)
            cur = (len(m.group(1)), m.group(2), [ln])
        else:
            cur[2].append(ln)
    segs.append(cur)
    out: list[str] = []
    for lvl, title, seg in segs:
        if lvl == 0 or lvl >= 4 or sum(len(x) + 1 for x in seg) <= limit:
            out += seg
            continue
        units: list[list[str]] = [[]]  # paragraphs: a blank line outside a fence ends one
        fenced = False
        for ln in seg[1:]:
            if ln.lstrip().startswith("```"):
                fenced = not fenced
            units[-1].append(ln)
            if not fenced and not ln.strip():
                units.append([])
        pieces: list[list[str]] = [[seg[0]]]
        size = len(seg[0]) + 1
        for u in units:
            usize = sum(len(x) + 1 for x in u)
            if size + usize > limit and size > 0 and any(x.strip() for x in pieces[-1][1:]):
                pieces.append([])
                size = 0
            pieces[-1] += u
            size += usize
        for n, pc in enumerate(pieces):
            out += pc if n == 0 else [f"{'#' * lvl} {title} (part {n + 1})", ""] + [x for x in pc]
    return out


# --- conversion --------------------------------------------------------------------------------------------------------------------------
class Result:
    def __init__(self, name: str, status: str, reason: str = "", text: str = "", hits: list[str] | None = None, mapped: set[str] | None = None):
        self.name, self.status, self.reason, self.text = name, status, reason, text
        self.hits, self.mapped = hits or [], mapped or set()


def static_skip(name: str, fm: dict[str, str], body: str) -> list[str]:
    """Reasons to skip that do not depend on the rewrite (the language, the market, the kind of skill)."""
    desc = fm.get("description", "")
    out = []
    cjk = len(CJK.findall(body)) / max(1, len(body))
    if cjk >= 0.03:
        out.append(f"Written in Chinese ({cjk:.0%} of characters)")
    per_k = len(CHINA.findall(body)) / max(1, len(body)) * 1000
    if per_k >= 2.5 or (CHINA.search(desc) and per_k >= 2.0):
        out.append("China A-share, H-share or Stock Connect data and rules, which OpenTerm does not have")
    if fm.get("category") == "data-source":
        out.append("Data-library recipe (pip package, scripts or API keys); OpenTerm reads data through its own tools")
    return out


def demote(lines: list[str]) -> list[str]:
    """Push every `#` heading of a reference file one level down; a `#` line inside a code fence is a comment and stays."""
    out: list[str] = []
    for kind, _, b in blocks(lines):
        out += b if kind == "fence" else [re.sub(r"^(#{1,3})(\s)", lambda m: "#" * (len(m.group(1)) + 1) + m.group(2), x) for x in b]
    return out


def is_chinese(text: str) -> bool:
    return len(CJK.findall(text)) / max(1, len(text)) >= 0.03


def rewrite(raw: str, registry: set[str], refs: list[tuple[str, str]] | None = None) -> tuple[list[str], list[str], set[str], int]:
    """Apply the rewrite rules to a SKILL.md body. Returns (lines, hit descriptions, tools renamed, reference files left out)."""
    _, body = split_frontmatter(raw)
    lines = body.replace("\r\n", "\n").split("\n")
    # 1. drop the file's own H1 (we write ours) and whole sections that describe Vibe's harness
    kept: list[str] = []
    drop_level, fenced = 0, False
    for ln in lines:
        if ln.lstrip().startswith("```"):
            fenced = not fenced
        m = None if fenced else re.match(r"^(#{1,4})\s+(.+?)\s*$", ln)
        if m:
            lvl = len(m.group(1))
            if drop_level and lvl <= drop_level:
                drop_level = 0
            if not drop_level and lvl >= 2 and DROP_HEADINGS.match(m.group(2).strip("`* ").strip()):
                drop_level = lvl
            if lvl == 1:
                continue
        if not drop_level:
            kept.append(ln)
    # 2. English reference files become sections of the playbook
    all_blocks = blocks(kept)
    ref_title: dict[str, str] = {}
    skipped_refs = 0
    for ref_name, ref_raw in refs or []:
        if is_chinese(ref_raw):
            skipped_refs += 1
            continue
        _, rbody = split_frontmatter(ref_raw)
        title = re.sub(r"[_-]+", " ", Path(ref_name).stem).strip()
        ref_title[Path(ref_name).stem] = title
        all_blocks += [("prose", "", ["", f"## Reference: {title}", ""])] + blocks(demote(rbody.replace("\r\n", "\n").split("\n")))

    hits: list[str] = []
    mapped: set[str] = set()
    out: list[str] = []

    def emit(note: str) -> None:
        if not out or out[-1] != note:  # one note per run of cut lines
            out.append(note)

    for kind, lang, b in all_blocks:
        if kind == "fence":
            joined = "\n".join(b)
            if lang in ("bash", "sh", "shell", "powershell", "cmd", "console", "zsh"):
                if all(PIP_ONLY.match(x) for x in b[1:-1]):
                    continue  # an install line: nothing to say
                hits.append("shell block")
                emit(NOTE_SHELL)
                continue
            bad = names_in(joined) | {t for t in TOOL_MAP if t != "backtest" and re.search(rf"\b{t}\b", joined)}
            if bad:
                hits.append("code block: " + ", ".join(sorted(bad)))
                emit(NOTE_CODE)
            elif re.search(r'signal_engine|run_dir|config\.json|"codes"\s*:', joined):
                hits.append("config block")
                emit(NOTE_HARNESS)
            elif len(joined) > SECTION_LIMIT:  # the assistant cannot run it, and a block that long cannot be read in one piece
                emit(NOTE_LONG_CODE)
            else:
                out.extend(b)
            continue
        for ln in b:
            if not ln.strip():
                out.append(ln)
                continue
            if ln.startswith("#"):  # a heading keeps its text; a parenthesis that names a harness file or a missing tool is cut from it
                out.append(re.sub(r"\s*\([^()]*\)", lambda m: "" if HARNESS.search(m.group(0)) or names_in(m.group(0)) else m.group(0), ln))
                continue
            new = ln
            for stem, title in ref_title.items():  # a pointer to an included reference file points at its section instead
                new = re.sub(rf"`?(?:\./)?references/{re.escape(stem)}\.md`?", f'the section "Reference: {title}"', new)
            for old, repl in TOOL_MAP.items():  # renames
                if repl in registry and (pat := _tool_token(old)).search(new):
                    new = pat.sub(f"`{repl}`", new)
                    mapped.add(repl)
            prefix = re.match(r"^(\s*(?:[-*>]\s+|\d+[.)]\s+)*)", new).group(1)
            if (left := sorted(names_in(new, registry))):  # tools OpenTerm lacks
                hits.append("tool: " + ", ".join(left))
                if new.lstrip().startswith("|"):  # a table row stays, with the tool named by its class
                    for t in left:
                        new = _tool_token(t).sub(LIMIT_CLASS.get(t, "a Vibe-Trading-only tool"), new)
                else:
                    emit(prefix + NOTE_LIMIT.format(what=", ".join(sorted({LIMIT_CLASS.get(t, "a Vibe-Trading-only tool") for t in left}))))
                    continue
            elif SCRIPT.search(new):
                hits.append("script")
                emit(prefix + NOTE_SCRIPT)
                continue
            elif HARNESS.search(new):
                hits.append("harness")
                if new.lstrip().startswith("|"):
                    new = HARNESS.sub("(Vibe-Trading only)", new)
                else:
                    emit(prefix + NOTE_HARNESS)
                    continue
            out.append(new)
    return out, hits, mapped, skipped_refs


def one_sentence(desc: str, registry: set[str]) -> str:
    """The skill's description for the `Goal:` line: sentences that name a tool OpenTerm lacks are dropped, the rest kept up to 300 characters."""
    desc = re.sub(r"\s+", " ", desc).strip()
    for old, repl in TOOL_MAP.items():
        if repl in registry:
            desc = _tool_token(old).sub(f"`{repl}`", desc)
    kept = [x for x in re.split(r"(?<=[.!?])\s+", desc) if not names_in(x, registry)]
    desc = " ".join(kept)
    return desc if len(desc) <= 300 else desc[:297].rsplit(" ", 1)[0] + "..."


def tools_cut(hits: list[str]) -> str:
    """The names behind a list of hits, once each, for the skip list."""
    names = sorted({t.strip() for h in hits if h.startswith(("tool: ", "code block: ")) for t in h.split(": ", 1)[1].split(",")})
    other = sorted({h for h in hits if not h.startswith(("tool: ", "code block: "))})
    return ", ".join(names + other)[:150]


def convert(name: str, raw: str, registry: set[str], refs: list[tuple[str, str]] | None = None, taken: set[str] | None = None) -> Result:
    fm, body = split_frontmatter(raw)
    reasons = static_skip(name, fm, body)
    if (hard := names_in(body) & HARD_TOOLS):
        reasons.append("Uses a journal, broker, order or Pixel Office tool, which is out of scope: " + ", ".join(sorted(hard)))
    lines, hits, mapped, skipped_refs = rewrite(raw, registry, refs)
    if len(hits) > MAX_HITS:
        reasons.append(f"{len(hits)} steps need things OpenTerm lacks: {tools_cut(hits)}")
    if reasons:
        return Result(name, "skipped", "; ".join(reasons), hits=hits)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    lines = split_big(lines, SECTION_LIMIT)
    file_name = name if not taken or name not in taken else f"vibe-{name}"
    head = [
        f"<!-- {MARK} `agent/src/skills/{name}/SKILL.md` @ {COMMIT} (MIT). Generated by scripts/port_vibe_skills.py: change the script, not this file. See THIRD_PARTY.md. -->",
        f"# Playbook: {file_name}", "",
        f"Goal: {one_sentence(fm.get('description', name), registry) or name}", "", LEAD, "",
    ]
    if skipped_refs:
        head += [f"({skipped_refs} Chinese-language reference file(s) of the original are not included.)", ""]
    text = "\n".join(head + lines) + "\n"
    text = re.sub(r"\n{3,}", "\n\n", text)
    if (left := names_in(text, registry)):
        return Result(name, "skipped", "Still names a tool OpenTerm lacks: " + ", ".join(sorted(left)), hits=hits)
    res = Result(file_name, "ported", text=text, hits=hits, mapped=mapped)
    res.source = name  # type: ignore[attr-defined]
    return res


# --- driver ------------------------------------------------------------------------------------------------------------------------------
def skills_dir(arg: str) -> Path:
    p = Path(arg)
    for cand in (p, p / "agent" / "src" / "skills"):
        if (cand / "valuation-model" / "SKILL.md").exists():
            return cand
    sys.exit(f"no Vibe-Trading skills found under {arg}")


def load_refs(d: Path) -> list[tuple[str, str]]:
    ref = d / "references"
    if not ref.is_dir():
        return []
    return [(p.name, p.read_text(encoding="utf-8")) for p in sorted(ref.rglob("*.md"))]


def registry_names() -> set[str]:
    sys.path.insert(0, str(ROOT / "backend"))
    from openterm.ai import tools

    return set(tools.REGISTRY)


def skipped_doc(skipped: list[Result], ported: list[Result], total: int) -> str:
    lines = [
        "# Phase 20: Vibe-Trading skills that were not ported", "",
        f"Source: HKUDS/Vibe-Trading `agent/src/skills` @ `{COMMIT}` (MIT). Generated by `scripts/port_vibe_skills.py`: change the script, not this file.",
        f"{total} skills were read: {len(ported)} ported to `backend/openterm/ai/skills/`, {len(skipped)} skipped. A skill is skipped when it needs something OpenTerm does not have:",
        "a shell or file tools, web search or a page reader, Vibe-only stores, a journal or broker, China A-share data, or a paid or keyed data API; or when it is written in Chinese.",
        "A ported skill never names a tool that is not in the AI tool registry, and never an order, trading or broker tool.", "",
        f"## Skipped ({len(skipped)})", "", "| Skill | Reason |", "|---|---|",
    ]
    lines += [f"| `{r.name}` | {r.reason} |" for r in sorted(skipped, key=lambda r: r.name)]
    lines += ["", f"## Ported with limits ({len([r for r in ported if r.hits])})", "",
              "Steps cut from these skills (shell, file, web or Vibe-only tools). The rest of each skill is intact.", "", "| Skill | Steps cut | What |", "|---|---|---|"]
    for r in sorted(ported, key=lambda r: r.name):
        if r.hits:
            what = "; ".join(sorted({h.split(": ", 1)[1] if ": " in h else h for h in r.hits}))[:110]
            lines.append(f"| `{r.name}` | {len(r.hits)} | {what} |")
    return "\n".join(lines) + "\n"


def third_party_row() -> str:
    return (f"| `openterm/ai/skills/*.md` (ported ones start with `<!-- {MARK}`) | `agent/src/skills/<name>/SKILL.md` and its English `references/*.md` "
            f"(frontmatter dropped; shell, file, web and Vibe-only tool steps cut; Vibe tool names renamed to OpenTerm tools; one header comment added; "
            f"list in `docs/PHASE_20_SKIPPED.md`) | {SOURCE} @ `{COMMIT}` | MIT. NOTICE: \"Vibe-Trading, Copyright 2026 HKUDS contributors. "
            f"This product includes software developed at HKUDS (https://github.com/HKUDS).\" |")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vibe", help="Vibe-Trading checkout (or its agent/src/skills folder)")
    ap.add_argument("--check", action="store_true", help="write nothing; exit 1 if the output on disk differs")
    a = ap.parse_args()
    src = skills_dir(a.vibe)
    registry = registry_names()
    hand_written = {p.stem for p in OUT_DIR.glob("*.md") if not p.read_text(encoding="utf-8").lstrip().startswith(f"<!-- {MARK}")}
    results: list[Result] = []
    dirs = sorted(d for d in src.iterdir() if (d / "SKILL.md").exists())
    for d in dirs:
        results.append(convert(d.name, (d / "SKILL.md").read_text(encoding="utf-8"), registry, load_refs(d), hand_written))
    ported = [r for r in results if r.status == "ported"]
    skipped = [r for r in results if r.status == "skipped"]
    want = {f"{r.name}.md": r.text for r in ported}
    diffs: list[str] = []
    for p in OUT_DIR.glob("*.md"):  # stale ported files
        if p.name not in want and p.read_text(encoding="utf-8").lstrip().startswith(f"<!-- {MARK}"):
            diffs.append(f"remove {p.name}")
            if not a.check:
                p.unlink()
    for fname, text in want.items():
        p = OUT_DIR / fname
        if not p.exists() or p.read_bytes() != text.encode("utf-8"):
            diffs.append(f"write {fname}")
            if not a.check:
                p.write_bytes(text.encode("utf-8"))
    doc = skipped_doc(skipped, ported, len(results)).encode("utf-8")
    if not SKIPPED_DOC.exists() or SKIPPED_DOC.read_bytes() != doc:
        diffs.append("write docs/PHASE_20_SKIPPED.md")
        if not a.check:
            SKIPPED_DOC.write_bytes(doc)
    tp = THIRD_PARTY.read_text(encoding="utf-8")
    row = third_party_row()
    if row not in tp:  # one row for the ported directory: replace the old one, or add it after the last row of the "Ported code" table
        rows = tp.split("\n")
        old_i = next((i for i, x in enumerate(rows) if x.startswith("| `openterm/ai/skills/")), None)
        if old_i is not None:
            rows[old_i] = row
        else:
            last = max(i for i, x in enumerate(rows) if x.startswith("| `openterm/") and "HKUDS/Vibe-Trading" in x)
            rows.insert(last + 1, row)
        diffs.append("write THIRD_PARTY.md")
        if not a.check:
            THIRD_PARTY.write_bytes("\n".join(rows).encode("utf-8"))
    print(f"read {len(results)}  ported {len(ported)}  skipped {len(skipped)}  changed files {len(diffs)}")
    if a.check and diffs:
        sys.exit("out of date: " + ", ".join(diffs[:5]))


if __name__ == "__main__":
    main()
