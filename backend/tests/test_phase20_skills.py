"""Phase 20 step 7: the ported Vibe-Trading skill library, the `section` argument of the `skill` tool, the `skills` search tool and the prompt-size guard.

Table driven: every ported playbook is checked on its own (header, parse, real tools only, no forbidden names, loads through the tool, every section reads).
Nothing touches the network or a model. The porter script itself is tested on small synthetic inputs, so these tests do not need a Vibe-Trading checkout.
"""

import asyncio
import importlib.util
import json
import re
from pathlib import Path

import pytest

from openterm.ai import skills, tools
from openterm.ai.tools import ToolRunner

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("port_vibe_skills", ROOT / "scripts" / "port_vibe_skills.py")
porter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(porter)

COMMIT = "8172827"
HAND_WRITTEN = {"valuation", "earnings", "options", "risk", "macro"}
# Names that no playbook may use as a tool (spec rule 6 and 8). Compared against whole backticked words, so the real tool `skill` is not caught by "kill".
FORBIDDEN = {"bash", "read_file", "write_file", "edit_file", "web_search", "read_url", "order", "trade", "gtt", "margin", "kill", "broker"}
RESULT_CAP = 6000  # context.RESULT_LIMIT
# Prompt guard: today's `skill` tool spec is 358 characters, about 89 tokens (measured with len/4 before this step). The playbook library may add at most ~600 tokens.
OLD_SKILL_SPEC_TOKENS = 89
BUDGET_TOKENS = 600

VIBE_SKILLS = (
    "adr-hshare", "akshare", "alpha-zoo", "ashare-pre-st-filter", "asset-allocation", "backtest-diagnose", "behavioral-finance",
    "bottleneck-hunter", "candlestick", "ccxt", "chanlun", "commodity-analysis", "convertible-bond", "corporate-events",
    "correlation-analysis", "correlation-regime", "credit-analysis", "cross-market-strategy", "crypto-derivatives", "data-routing",
    "deep-company-series", "defi-yield", "dividend-analysis", "doc-reader", "earnings-forecast", "earnings-revision", "eastmoney",
    "edgar-sec-filings", "elliott-wave", "etf-analysis", "event-driven", "execution-model", "factor-research", "financial-statement",
    "fund-analysis", "fundamental-filter", "geopolitical-risk", "global-macro", "harmonic", "hedging-strategy", "hk-connect-flow",
    "ichimoku", "investor-lenses", "liquidation-heatmap", "macro-analysis", "management-deep-dive", "market-microstructure",
    "minute-analysis", "ml-strategy", "mootdx", "multi-factor", "okx-market", "onchain-analysis", "options-advanced", "options-payoff",
    "options-strategy", "pair-trading", "performance-attribution", "perp-funding-basis", "pine-script", "private-company-research",
    "quant-statistics", "regulatory-knowledge", "report-generate", "research-discipline", "research-goal", "risk-analysis", "seasonal",
    "sec-edgar", "sector-rotation", "sentiment-analysis", "shadow-account", "smc", "social-media-intelligence", "stablecoin-flow",
    "strategy-dev-manager", "strategy-discovery", "strategy-generate", "technical-basic", "thesis-tracker", "token-unlock-treasury",
    "trade-journal", "tushare", "us-etf-flow", "valuation-model", "vnpy-export", "volatility", "web-reader", "yfinance",
)

HEADER = re.compile(r"\A<!-- Ported from HKUDS/Vibe-Trading `agent/src/skills/([a-z0-9-]+)/SKILL\.md` @ (\w+) \(MIT\)\.")


def ported() -> dict[str, str]:
    """{file stem: source skill name} for every file the porter wrote."""
    out = {}
    for n in skills.names():
        m = HEADER.match(skills.get(n))
        if m:
            out[n] = m.group(1)
    return out


PORTED = ported()


def skipped_from_doc() -> dict[str, str]:
    text = (ROOT / "docs" / "PHASE_20_SKIPPED.md").read_text(encoding="utf-8")
    block = text.split("## Skipped", 1)[1].split("## Ported with limits", 1)[0]
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^\| `([a-z0-9-]+)` \| (.+) \|$", block, re.MULTILINE)}


def prose_of(text: str) -> str:
    return "\n".join("\n".join(b) for kind, _, b in porter.blocks(text.splitlines()) if kind == "prose")


def spec_tokens(*names: str) -> int:
    specs = [s for s in tools.openai_tools() if s["function"]["name"] in names]
    return len(json.dumps(specs, separators=(",", ":"))) // 4


# --- the ported set -----------------------------------------------------------------------------------------------------------------------
def test_every_vibe_skill_is_ported_or_listed_as_skipped_exactly_once():
    skipped = skipped_from_doc()
    done = set(PORTED.values())
    assert len(VIBE_SKILLS) == 89 and len(set(VIBE_SKILLS)) == 89
    assert done | set(skipped) == set(VIBE_SKILLS), "port_vibe_skills.py output and docs/PHASE_20_SKIPPED.md disagree with the 89 Vibe skills"
    assert not done & set(skipped), "a skill is both ported and skipped"
    assert all(len(r) > 15 for r in skipped.values()), "every skipped skill needs a written reason"
    assert not set(skipped) & set(skills.names()), "a skipped skill must not have a playbook file"
    head = (ROOT / "docs" / "PHASE_20_SKIPPED.md").read_text(encoding="utf-8")
    assert f"{len(done)} ported" in head and f"{len(skipped)} skipped" in head and f"## Skipped ({len(skipped)})" in head


def test_the_five_hand_written_playbooks_are_untouched_by_the_port():
    for n in HAND_WRITTEN:
        assert n in skills.names() and n not in PORTED, n
        assert not skills.get(n).startswith("<!--"), n
    assert len(PORTED) >= 30, "the port lost most of the library"


def test_every_ported_directory_has_a_third_party_row():
    tp = (ROOT / "THIRD_PARTY.md").read_text(encoding="utf-8")
    row = next(x for x in tp.splitlines() if x.startswith("| `openterm/ai/skills/"))
    assert "agent/src/skills/" in row and COMMIT in row and "MIT" in row and "HKUDS contributors" in row


@pytest.mark.parametrize("stem", sorted(PORTED))
def test_ported_playbook(stem):
    raw = skills.get(stem)
    m = HEADER.match(raw)
    assert m and m.group(2) == COMMIT and m.group(1) in VIBE_SKILLS
    body = skills.text(stem)
    assert "<!--" not in body.split("\n", 1)[0], "the source comment is for people and must not reach the model"
    assert body.startswith(f"# Playbook: {stem}\n")
    assert re.search(r"^Goal: .{10,}$", body, re.MULTILINE), "a Goal line is what the search result shows"
    assert 10 <= len(skills.describe(stem)) <= skills.INDEX_WIDTH
    assert "not personalised investment advice" in body

    # real tools only: no tool name from Vibe's registry that OpenTerm lacks, and the same check is clean for every backticked word
    registry = set(tools.REGISTRY)
    assert porter.names_in(raw, registry) == set(), porter.names_in(raw, registry)
    prose = prose_of(raw)
    words = set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", prose)) | set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)\(", prose))
    assert not words & FORBIDDEN, words & FORBIDDEN
    assert not {w for w in words if w.startswith(("trading_", "etoro_", "paper_trade"))}
    assert not re.search(r"^\s*```(bash|sh|shell|powershell|cmd)\b", raw, re.MULTILINE), "shell blocks must be cut"
    assert not re.search(r"\b(read_file|write_file|edit_file|web_search|read_url|run_swarm|signal_engine)\b", raw)

    # parses: headings are found outside code, and unique enough to be addressed
    secs = skills.sections(stem)
    assert secs and all(s.strip() for s in secs)


@pytest.mark.parametrize("stem", sorted(PORTED) + sorted(HAND_WRITTEN))
def test_playbook_loads_through_the_skill_tool_within_the_result_cap(stem):
    assert tools.validate("skill", {"name": stem}) is None
    res = asyncio.run(ToolRunner(app=None).call("skill", {"name": stem}))  # `skill` is answered in this process: no route is called
    assert res.ok and not res.empty
    data = json.loads(res.text)  # a result cut mid-JSON would not parse
    assert data["name"] == stem and data["playbook"].strip()
    assert len(res.text) < RESULT_CAP
    if data.get("truncated"):
        assert data["headings"] and "section" in data["hint"]


@pytest.mark.parametrize("stem", sorted(PORTED) + sorted(HAND_WRITTEN))
def test_every_section_of_every_playbook_reads_and_fits(stem):
    for title in skills.sections(stem):
        out = skills.read(stem, title)
        assert "error" not in out, (stem, title, out)
        assert out["playbook"].lstrip().startswith("#"), (stem, title)
        assert len(json.dumps(out, separators=(",", ":"))) < RESULT_CAP
        if out.get("truncated"):  # a long section is read child by child: it must list the children, or its tail would be out of reach
            assert out.get("headings"), f"{stem}: section {title!r} is cut and has no sub-headings"


# --- the skill tool: section argument -----------------------------------------------------------------------------------------------------
def test_skill_tool_schema_has_an_optional_section_and_validates_it():
    t = tools.REGISTRY["skill"]
    assert set(t.parameters["properties"]) == {"name", "section"} and t.parameters["required"] == ["name"]
    assert tools.validate("skill", {"name": "valuation-model", "section": "DCF"}) is None
    assert "section" in tools.validate("skill", {"name": "valuation-model", "section": 5}).lower()
    assert "name" in tools.validate("skill", {"name": "astrology"})
    assert "skills tool" in tools.validate("skill", {"name": "astrology"})  # the error tells the model where to look


def test_section_returns_one_heading_and_what_is_under_it():
    out = skills.read("valuation-model", "Absolute Valuation Methods")
    assert out["section"] == "Absolute Valuation Methods" and out["playbook"].startswith("## Absolute Valuation Methods")
    assert "### 1. DCF" in out["playbook"] and "## Overview" not in out["playbook"]
    sub = skills.read("valuation-model", "1. DCF (Discounted Cash Flow)")  # a ### heading is a section too
    assert sub["playbook"].startswith("### 1. DCF") and "### 2." not in sub["playbook"]
    assert skills.read("valuation-model", "absolute valuation")["section"] == "Absolute Valuation Methods"  # case and a unique fragment are enough


def test_a_repeated_heading_is_numbered_so_each_copy_can_be_asked_for():
    names = skills.sections("correlation-regime")
    assert "Workflow" in names and "Workflow (2)" in names
    first, second = skills.read("correlation-regime", "Workflow"), skills.read("correlation-regime", "Workflow (2)")
    assert first["playbook"] != second["playbook"] and second["section"] == "Workflow (2)"


def test_unknown_or_ambiguous_section_is_a_clear_error_that_lists_the_headings():
    bad = skills.read("valuation-model", "Astrology")
    assert bad["error"].startswith("UNKNOWN SECTION") and "Overview" in bad["headings"] and "playbook" not in bad
    amb = skills.read("valuation-model", "methods")  # a fragment that matches several headings
    assert amb["error"].startswith("AMBIGUOUS SECTION") and len(amb["headings"]) > 1
    none = skills.read("risk", "anything")  # a hand-written playbook without headings
    assert none["error"].startswith("UNKNOWN SECTION") and none["headings"] == []
    res = asyncio.run(ToolRunner(app=None).call("skill", {"name": "valuation-model", "section": "Astrology"}))
    assert res.ok and json.loads(res.text)["error"].startswith("UNKNOWN SECTION")  # information for the model, not a failed call
    with pytest.raises(KeyError):
        skills.read("nope")


def test_a_long_playbook_comes_back_cut_with_its_headings():
    out = skills.read("investor-lenses")
    assert out["truncated"] and out["headings"] and "section" in out["hint"]
    assert len(out["playbook"]) <= skills.MAX_CHARS and out["playbook"].endswith("\n")
    assert not skills.read("candlestick").get("truncated")


# --- the skills search tool + prompt guard ------------------------------------------------------------------------------------------------
def test_skills_search_finds_playbooks_by_topic():
    top = lambda q: [m["name"] for m in skills.search(q)]
    assert top("pairs trading")[0] == "pair-trading"
    assert "dividend-analysis" in top("dividend yield income")
    assert top("perpetual funding rate")[0] == "perp-funding-basis"
    assert "valuation" in top("valuation dcf")[:3] and "risk" in top("value at risk drawdown")
    assert skills.search("zzzz nothing") == [] and skills.search("   ") == []
    assert len(skills.search("analysis", 3)) == 3 and len(skills.search("analysis", 99)) <= 15
    hit = skills.search("candlestick")[0]
    assert set(hit) == {"name", "about", "sections"} and len(hit["about"]) <= skills.INDEX_WIDTH


def test_skills_tool_is_read_only_and_answers_through_the_runner():
    t = tools.REGISTRY["skills"]
    assert t.local is not None and not t.desk_only and not t.doc_only and t.parameters["required"] == ["query"]
    assert tools.validate("skills", {"query": "options"}) is None and "query" in tools.validate("skills", {})
    res = asyncio.run(ToolRunner(app=None).call("skills", {"query": "ichimoku"}))
    data = json.loads(res.text)
    assert res.ok and data["total"] == len(skills.names()) and data["matches"][0]["name"] == "ichimoku"
    empty = asyncio.run(ToolRunner(app=None).call("skills", {"query": "zzzz nothing"}))
    assert empty.ok and empty.empty  # an empty answer is marked empty


def test_index_budget_holds_and_the_search_tool_is_used_when_a_full_index_would_not_fit():
    index_tokens = sum(len(f"{n}: {skills.describe(n)}") + 1 for n in skills.names()) // 4  # len/4 estimate; one line per playbook
    added = spec_tokens("skill", "skills") - OLD_SKILL_SPEC_TOKENS
    assert added <= BUDGET_TOKENS, f"the playbook tools add {added} tokens to every prompt (budget {BUDGET_TOKENS})"
    for n in skills.names():
        assert len(skills.describe(n)) <= skills.INDEX_WIDTH
    skill_spec = json.dumps(tools.REGISTRY["skill"].parameters) + tools.REGISTRY["skill"].description
    if index_tokens > BUDGET_TOKENS:  # a full index is too big: the prompt carries a one-line hint and the search tool carries the rest
        assert "skills" in tools.REGISTRY and "skills tool" in tools.REGISTRY["skill"].description
        assert sum(1 for n in PORTED if n in skill_spec) == 0, "the skill tool spec must not list ported playbook names"
    else:  # a small library may list every playbook in the spec instead
        assert all(n in skill_spec for n in skills.names())
    assert len(tools.REGISTRY["skill"].description) <= 330


def test_audit_manifest_hashes_every_playbook():
    from openterm.ai import audit

    m = audit.manifest("p", ["skill"], "m", "o")
    assert set(m["skills"]) == set(skills.names()) and len(m["skills"]) == 5 + len(PORTED)
    assert all(len(h) == 16 for h in m["skills"].values())


# --- the porter script on small inputs (rules, not the data) ------------------------------------------------------------------------------
REG = {n for n, t in tools.REGISTRY.items() if not t.web_only}  # web tools are opt-in, a ported playbook never names them


def convert(body, name="demo", desc="A demo playbook about nothing in particular", category="analysis", refs=None, taken=None):
    raw = f"---\nname: {name}\ndescription: {desc}\ncategory: {category}\n---\n# Title\n\n{body}\n"
    return porter.convert(name, raw, REG, refs, taken)


def test_porter_renames_equivalent_tools_and_never_names_a_missing_one():
    r = convert("## Steps\n\nUse `get_stock_news` and `get_sec_filings` first.\nThen `web_search` the company.\nFinally `write_file` the report.\n")
    assert r.status == "ported"
    assert "`news`" in r.text and "`filings`" in r.text
    assert not re.search(r"web_search|write_file", r.text) and "Step omitted" in r.text
    assert porter.names_in(r.text, REG) == set()


def test_porter_cuts_shell_blocks_install_sections_and_script_lines():
    body = ("## Dependencies\n\n```bash\npip install pandas\n```\n\n## Method\n\nCompute the ratio.\n\n```bash\npython run.py --fast\n```\n\n"
            "Run `python analyse.py` to see it.\n\n```python\nx = 1\n```\n")
    r = convert(body)
    assert r.status == "ported"
    assert "Dependencies" not in r.text and "pip install" not in r.text and "```bash" not in r.text and "python analyse.py" not in r.text
    assert "Shell commands omitted" in r.text and "`quant` tool" in r.text and "x = 1" in r.text  # python reference code stays


def test_porter_skips_chinese_china_data_library_journal_and_central_tool_skills():
    assert "Chinese" in convert("## 概述\n\n" + "这是一个关于股票分析的中文技能说明文档，包含很多内容。" * 5).reason
    assert "China" in convert("## A\n\n" + "A-share and Stock Connect flows via Tushare. " * 20).reason
    assert "Data-library" in convert("## A\n\nUse the package.", category="data-source").reason
    assert "journal" in convert("## A\n\nCall `analyze_trade_journal` on the file.").reason
    many = "\n".join(f"{i}. Call `write_file` for step {i}." for i in range(8))
    r = convert("## A\n\n" + many)
    assert r.status == "skipped" and "8 steps" in r.reason and "write_file" in r.reason
    for name in ("web-reader", "tushare", "trade-journal", "strategy-dev-manager"):
        assert name in skipped_from_doc()


def test_porter_inlines_english_reference_files_and_splits_long_sections():
    r = convert("## Method\n\nSee `references/combination.md` for more.\n", refs=[("combination.md", "# Combination\n\nEqual weights.\n\n## Detail\n\nText.\n")])
    assert '## Reference: combination' in r.text and "### Detail" in r.text and "Equal weights." in r.text and "references/combination.md" not in r.text
    big = "## Long\n\n" + "\n\n".join(f"Paragraph {i} " + "word " * 120 for i in range(20)) + "\n"
    out = convert(big).text
    parts = re.findall(r"^## Long( \(part \d+\))?$", out, re.MULTILINE)
    assert len(parts) >= 3
    assert max(len(seg) for seg in re.split(r"^## ", out, flags=re.MULTILINE)) < porter.SECTION_LIMIT + 200


def test_porter_is_idempotent_and_renames_a_clashing_name():
    a = convert("## A\n\nBody text here.\n")
    assert a.text == convert("## A\n\nBody text here.\n").text
    clash = convert("## A\n\nBody text here.\n", name="risk", taken={"risk"})
    assert clash.name == "vibe-risk" and "# Playbook: vibe-risk" in clash.text and "agent/src/skills/risk/SKILL.md" in clash.text
    assert clash.text.startswith(f"<!-- Ported from HKUDS/Vibe-Trading `agent/src/skills/risk/SKILL.md` @ {COMMIT} (MIT).")
