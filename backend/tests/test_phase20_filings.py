"""Phase 20 step 9: Filings Intelligence (`AI FILING`). The pure parts (section split, FTS5 / BM25 retrieval, quote verification) run on small
hand-made filing text; the route runs inside the app with a scripted model (`FakeGateway`) and a faked SEC document download. Nothing here
touches the network or a real model, so it costs nothing to run."""

import json
import sqlite3
from collections import OrderedDict

import pytest
from test_phase16_agent import SECRET, FakeGateway, sse, text

from openterm.ai import filings as F
from openterm.llm.events import Event


# --- a small but realistic 10-K ---------------------------------------------------------------------------------------------------------
def pad(sentence: str, n: int = 4) -> str:
    """Repeat a sentence so a section is longer than the table-of-contents cut-off (a heading with <200 characters under it is dropped)."""
    return " ".join([sentence] * n)


RISK_SENTENCE = "The Company’s business depends on a limited number of suppliers, and supply chain constraints could materially harm results."
REV_SENTENCE = "Total net sales increased 6% during 2024 primarily due to higher iPhone volume and growth in Services revenue."
MARGIN_SENTENCE = "Gross margin percentage decreased due to unfavorable mix and higher component costs, partially offset by cost savings."
BIZ_SENTENCE = "The Company designs, manufactures and markets smartphones, personal computers, tablets and wearables."


def tenk_html(ix_header: bool = True) -> str:
    toc = "".join(f"<p>Item {i}. {t} {n}</p>" for i, t, n in [("1", "Business", 3), ("1A", "Risk Factors", 5), ("7", "Management’s Discussion", 21)])
    hidden = "<div style='display:none'><ix:header>HIDDENXBRLFACT 0000320193 dei:EntityRegistrantName</ix:header></div>" if ix_header else ""
    return (
        f"<html><body>{hidden}<p>UNITED STATES SECURITIES AND EXCHANGE COMMISSION</p><p>FORM 10-K</p><p>Apple Inc.</p>{toc}"
        f"<p>PART I</p><p>Item 1. Business</p><p>{pad(BIZ_SENTENCE)}</p>"
        f"<p>Item 1A. Risk Factors</p><p>{pad(RISK_SENTENCE)}</p>"
        f"<p>As described in Item 7 of this report, margins may vary.</p>"  # a cross reference, not a heading
        f"<p>PART II</p><p>Item 7. Management’s Discussion and Analysis</p><p>{pad(REV_SENTENCE)}</p><p>{pad(MARGIN_SENTENCE)}</p>"
        f"<table><tr><td>Net sales</td><td>391,035</td></tr></table>"
        f"<p>Item 8. Financial Statements</p><p>{pad('Total net sales were 391,035 million dollars for the year ended September 28, 2024.')}</p>"
        "</body></html>"
    )


def tenk() -> F.ParsedFiling:
    return F.parse_filing(tenk_html(), symbol="AAPL", form="10-K", filed="2024-11-01", accession="0000320193-24-000123", url="https://x/index.htm", fetched_at=0.0)


# --- sections ---------------------------------------------------------------------------------------------------------------------------
def test_split_drops_the_table_of_contents_and_labels_items():
    secs = F.split_sections(F.filing_text(tenk_html()), "10-K")
    labels = [s.label for s in secs]
    assert labels[0] == "Cover page"
    assert [lb for lb in labels if lb.startswith("Item")] == [
        "Item 1. Business", "Item 1A. Risk Factors", "Item 7. Management’s Discussion and Analysis", "Item 8. Financial Statements"]
    risk = next(s for s in secs if s.label.startswith("Item 1A"))
    assert "supply chain constraints" in risk.text
    assert "described in Item 7 of this report" in risk.text  # the cross reference stayed inside the section it was written in
    assert not any("Item 1A. Risk Factors 5" in s.text for s in secs if s.label != "Cover page")  # the contents line is not a section body


def test_split_10q_keeps_part_in_the_label_because_item_numbers_repeat():
    body = "x" * 10
    html = (f"<p>FORM 10-Q</p><p>PART I — FINANCIAL INFORMATION</p><p>Item 1. Financial Statements</p><p>{pad(body, 40)}</p>"
            f"<p>Item 2. Management’s Discussion</p><p>{pad(body, 40)}</p><p>PART II — OTHER INFORMATION</p>"
            f"<p>Item 1. Legal Proceedings</p><p>{pad(body, 40)}</p><p>Item 1A. Risk Factors</p><p>{pad(body, 40)}</p>")
    labels = [s.label for s in F.split_sections(F.filing_text(html), "10-Q") if s.label != "Cover page"]
    assert labels == ["Part I, Item 1. Financial Statements", "Part I, Item 2. Management’s Discussion", "Part II, Item 1. Legal Proceedings",
                      "Part II, Item 1A. Risk Factors"]


def test_a_document_with_no_item_headings_is_an_error_not_a_guess():
    with pytest.raises(F.FilingsError, match="NO ITEM HEADINGS"):
        F.split_sections("just some prose\nwith no structure", "10-K")


def test_inline_xbrl_header_is_dropped_and_table_cells_do_not_fuse():
    text_ = F.filing_text(tenk_html())
    assert "HIDDENXBRLFACT" not in text_
    assert "Net sales 391,035" in text_  # a space between the two table cells


def test_passages_stay_inside_their_section_and_under_the_size():
    f = tenk()
    assert f.passages and all(len(p.text) <= F.PASSAGE_CHARS + 50 for p in f.passages)
    assert {p.section for p in f.passages} >= {"Item 1A. Risk Factors", "Item 7. Management’s Discussion and Analysis"}
    for p in f.passages:
        sec = next(s for s in f.sections if s.label == p.section)
        assert F.normalise(p.text) in sec.norm  # every passage is real text from its own section


def test_a_very_long_paragraph_is_cut_into_passages():
    long = ("Sentence number one is here. " * 200).strip()
    secs = [F.Section("Item 7. MD&A", long)]
    ps = F.make_passages(secs, 500)
    assert len(ps) > 5 and all(len(p.text) <= 500 for p in ps)


# --- retrieval --------------------------------------------------------------------------------------------------------------------------
def test_retrieval_ranks_the_passage_with_the_question_words_first():
    ps = [F.Passage("Item 1. Business", "The company sells phones and tablets in many countries."),
          F.Passage("Item 1A. Risk Factors", "Supply chain constraints and supplier concentration could harm results. Supply chain disruption is a risk."),
          F.Passage("Item 7. MD&A", "Revenue grew because of services. A supply agreement was renewed.")]
    hits = F.retrieve(ps, ["What are the supply chain constraints?"])
    assert hits[0].section == "Item 1A. Risk Factors"
    assert hits[0].pid == "P1" and hits[0].score <= hits[1].score  # BM25 in SQLite: more negative is better, list is best first
    assert "Item 1. Business" not in [h.section for h in hits]  # no question word in it


def test_retrieval_stems_words_and_survives_fts_syntax_in_the_question():
    ps = [F.Passage("Item 1A. Risk Factors", "Each risk is described below. Competition in each market is intense.")]
    assert F.retrieve(ps, ["which risks?"])[0].section == "Item 1A. Risk Factors"  # the porter tokenizer: "risks" matches "risk"
    nasty = 'competition" OR (NEAR( AND * ^ :col -x'
    assert F.retrieve(ps, [nasty])  # quoted tokens: nothing is read as FTS syntax, no crash
    assert F.retrieve(ps, ["the and of"]) == []  # only filler words: nothing to search
    assert F.fts_query("what is the supply chain?") == '"supply" OR "chain"'


def test_drivers_merges_theme_queries_without_duplicates():
    f = tenk()
    hits = F.retrieve(f.passages, list(F.DRIVERS_THEMES.values()), F.DRIVERS_PER_THEME, F.DRIVERS_PER_THEME * 3)
    assert len(hits) == len({h.text for h in hits}) and {"Item 1A. Risk Factors", "Item 7. Management’s Discussion and Analysis"} <= {h.section for h in hits}
    assert [h.pid for h in hits] == [f"P{i}" for i in range(1, len(hits) + 1)]


def test_missing_fts5_fails_loudly(monkeypatch):
    class NoFts:
        def execute(self, *a, **kw):
            raise sqlite3.OperationalError("no such module: fts5")

        def close(self):
            pass

    monkeypatch.setattr(F.sqlite3, "connect", lambda *a, **kw: NoFts())
    with pytest.raises(F.FilingsError, match="FTS5 IS NOT AVAILABLE"):
        F.retrieve([F.Passage("s", "text")], ["text"])


# --- quote verification -----------------------------------------------------------------------------------------------------------------
def test_an_exact_quote_is_verified_and_names_its_section():
    f = tenk()
    ok, section, reason = F.check_quote("supply chain constraints could materially harm results", f.full_norm, f.sections)
    assert ok and section == "Item 1A. Risk Factors" and reason == "EXACT MATCH"


def test_typography_differences_do_not_break_a_true_quote():
    f = tenk()
    # curly vs straight apostrophe, extra spaces and line breaks, capital letters: same words, so verified
    q = "THE COMPANY'S   business depends on a\nlimited number of suppliers"
    assert F.check_quote(q, f.full_norm, f.sections)[0] is True
    assert F.check_quote("“Total net sales increased 6% during 2024 primarily due to higher iPhone volume”", f.full_norm, f.sections)[0] is True  # surrounding quote marks
    dash = F.parse_filing("<p>Item 7. MD&A</p><p>" + pad("Revenue rose 5–6% in the quarter on strong demand across all regions worldwide.", 6) + "</p>",
                          symbol="X", form="10-K", filed="", accession="a", url="u", fetched_at=0)
    assert F.check_quote("Revenue rose 5-6% in the quarter on strong demand", dash.full_norm, dash.sections)[0] is True  # en dash vs hyphen


def test_a_paraphrase_fails():
    f = tenk()
    ok, section, reason = F.check_quote("Apple relies on very few suppliers and supply problems might hurt its profits", f.full_norm, f.sections)
    assert ok is False and section is None and "PARAPHRASED OR INVENTED" in reason
    # one changed word is enough to fail; so is an elision
    assert F.check_quote("supply chain constraints could materially damage results", f.full_norm, f.sections)[0] is False
    assert F.check_quote("depends on a limited number ... could materially harm results", f.full_norm, f.sections)[0] is False


def test_too_short_or_empty_quotes_are_not_verified():
    f = tenk()
    assert F.check_quote("net sales", f.full_norm, f.sections) == (False, None, "QUOTE TOO SHORT TO PROVE ANYTHING")
    assert F.check_quote("  ", f.full_norm, f.sections)[2] == "NO QUOTE GIVEN"


def test_unverified_claims_are_left_out_of_the_summary():
    f = tenk()
    points = [{"claim": "Suppliers are a concentrated risk.", "quote": "depends on a limited number of suppliers", "section": "Item 1A. Risk Factors"},
              {"claim": "Apple will triple its margins.", "quote": "Apple expects margins to triple next year across all products", "section": "Item 7"}]
    checked = F.verify_points(points, f.full_norm, f.sections)
    assert [c["verified"] for c in checked] == [True, False]
    summary = F.rebuild_summary(checked)
    assert "Suppliers are a concentrated risk. [Q1]" in summary and "triple" not in summary
    assert F.rebuild_summary([]).startswith("THE RETRIEVED PASSAGES DO NOT ANSWER")
    assert "NONE OF THE MODEL'S 1 QUOTES" in F.rebuild_summary(checked[1:])


def test_parse_points_accepts_a_fence_or_chatter_and_rejects_anything_else():
    obj = {"points": [{"claim": "c", "quote": "q", "section": "s"}]}
    assert F.parse_points("```json\n" + json.dumps(obj) + "\n```")[0]["claim"] == "c"
    assert F.parse_points("Here you go: " + json.dumps(obj) + " Hope that helps.")[0]["quote"] == "q"
    assert F.parse_points('{"points": [{"claim": "no quote"}]}') == [{"claim": "no quote", "quote": "", "section": ""}]
    for bad in ("no json at all", '{"points": ', '{"answer": "x"}', "[1,2]"):
        with pytest.raises(F.FilingsError):
            F.parse_points(bad)


# --- the route --------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def sec(client):
    """The SEC provider with a declared user agent and a faked document download (the filings list comes from the recorded fixture)."""
    p = client.app.state.service.router.providers["sec"]
    p.ua_set = True
    p.seen = []
    client.app.state.ai_filings = OrderedDict()  # the app object is shared by every test: start with no cached filing

    async def get_bytes(url, *a, **kw):
        p.seen.append(url)
        return tenk_html().encode()

    p.get_bytes = get_bytes

    base = "https://www.sec.gov/Archives/edgar/data/320193/"

    async def filings(symbol):  # newest first, like SEC's list; the recorded AAPL list holds only 10-Qs, so a 10-K is added by hand
        rows = [("10-Q", "2025-02-01", "0000320193-25-000010", "aapl-20241228.htm"), ("8-K", "2025-01-15", "0000320193-25-000005", "x8k.htm"),
                ("10-K", "2024-11-01", "0000320193-24-000123", "aapl-20240928.htm")]
        return {"filings": [{"form": f, "filed": d, "accession": a, "doc_url": base + a.replace("-", "") + "/" + doc, "url": base + a.replace("-", "") + "/" + a + "-index.htm"}
                            for f, d, a, doc in rows]}

    p.filings = filings
    return p


def points_reply(*pts) -> list:
    return text(json.dumps({"points": [{"claim": c, "quote": q, "section": s} for c, q, s in pts]}))


GOOD = ("The Company depends on a limited number of suppliers.", "business depends on a limited number of suppliers", "Item 1A. Risk Factors")
BAD = ("Management expects supply to improve soon.", "management expects the supply situation to improve substantially by next quarter", "Item 7")


def test_route_answers_with_verified_quotes_and_the_labels(client, sec):
    client.app.state.llm = FakeGateway(points_reply(GOOD, BAD))
    r = client.post("/api/ai/filing", json={"symbol": "aapl", "form": "10-K", "question": "What supply chain risks does the company have?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = sse(r)
    kinds = [e["type"] for e in ev]
    assert kinds[:3] == ["start", "filing", "tool_call"] and kinds[-1] == "done" and "quotes" in kinds and "passages" in kinds
    flg = next(e for e in ev if e["type"] == "filing")
    assert flg["symbol"] == "AAPL" and flg["form"] == "10-K" and flg["accession"] and flg["source"] == "SEC EDGAR" and flg["filed"]
    tr = next(e for e in ev if e["type"] == "tool_result")
    assert tr["id"] == "T1" and tr["ok"] and not tr["empty"] and tr["source"].startswith("SEC EDGAR 10-") and tr["age_s"] >= 0
    q = next(e for e in ev if e["type"] == "quotes")["items"]
    assert [(c["verified"], c["section"]) for c in q] == [(True, "Item 1A. Risk Factors"), (False, None)]
    done = ev[-1]
    assert done["grounded"] is True and done["label"] is None and done["verified"] == 1 and done["unverified"] == 1
    assert "limited number of suppliers" in done["answer"] and "improve soon" not in done["answer"]  # the unverified claim is excluded
    assert ev[0]["model"] == "deepseek/deepseek-v4-pro" and ev[0]["started"]  # the AI · model · time label
    sent = client.app.state.llm.calls[0]["messages"]
    assert "[P1]" in sent[1]["content"] and "ONLY the numbered passages" in sent[0]["content"] and client.app.state.llm.calls[0]["tools"] is None
    assert len(sec.seen) == 1 and "sec.gov/Archives" in sec.seen[0]


def test_route_second_question_reuses_the_downloaded_filing(client, sec):
    client.app.state.llm = FakeGateway(points_reply(GOOD), points_reply(GOOD))
    for _ in range(2):
        assert sse(client.post("/api/ai/filing", json={"symbol": "AAPL", "form": "10-K", "question": "supplier risk"}))[-1]["type"] == "done"
    assert len(sec.seen) == 1


def test_route_drivers_mode_uses_the_fixed_question_and_three_themes(client, sec):
    client.app.state.llm = FakeGateway(points_reply(GOOD))
    ev = sse(client.post("/api/ai/filing", json={"symbol": "AAPL", "form": "10-K", "mode": "drivers"}))
    assert next(e for e in ev if e["type"] == "filing")["mode"] == "drivers"
    sent = client.app.state.llm.calls[0]["messages"][1]["content"]
    assert F.DRIVERS_QUESTION in sent
    sections = {p["section"] for p in next(e for e in ev if e["type"] == "passages")["items"]}
    assert any("Risk Factors" in s for s in sections) and any("Management" in s for s in sections)


def test_route_with_no_matching_passage_is_ungrounded_and_spends_nothing(client, sec):
    client.app.state.llm = FakeGateway(points_reply(GOOD))
    ev = sse(client.post("/api/ai/filing", json={"symbol": "AAPL", "form": "10-K", "question": "zebra xylophone quokka"}))
    done = ev[-1]
    assert done["type"] == "done" and done["grounded"] is False and done["label"] == "UNGROUNDED" and done["cost"] == 0.0
    assert client.app.state.llm.calls == []  # the model was never called
    assert next(e for e in ev if e["type"] == "tool_result")["empty"] is True


def test_route_needs_sec_user_agent_and_a_us_filer(client):
    p = client.app.state.service.router.providers["sec"]
    p.ua_set = False
    r = client.post("/api/ai/filing", json={"symbol": "AAPL", "question": "risks"})
    assert r.status_code == 400 and r.json()["kind"] == "key_required" and "SEC_USER_AGENT" in r.json()["error"]
    p.ua_set = True
    for sym in ("RELIANCE.NS", "^GSPC", "EURUSD=X"):
        r = client.post("/api/ai/filing", json={"symbol": sym, "question": "risks"})
        assert r.status_code == 400 and "US FILERS ONLY" in r.json()["error"]
    assert client.post("/api/ai/filing", json={"symbol": "bad symbol!", "question": "x"}).status_code == 400
    assert client.post("/api/ai/filing", json={"symbol": "AAPL"}).status_code == 400
    assert client.post("/api/ai/filing", json={"symbol": "AAPL", "question": "x", "form": "8-K"}).status_code == 400


def test_route_is_loopback_only(client):
    from fastapi.testclient import TestClient

    other = TestClient(client.app, client=("203.0.113.9", 5))
    assert other.post("/api/ai/filing", json={"symbol": "AAPL", "question": "x"}).status_code == 403


def test_route_bad_model_output_is_an_error_not_a_made_up_answer(client, sec):
    client.app.state.llm = FakeGateway(text("The company has supplier risk (trust me)."))
    ev = sse(client.post("/api/ai/filing", json={"symbol": "AAPL", "form": "10-K", "question": "supplier risk"}))
    assert ev[-1]["type"] == "error" and ev[-1]["kind"] == "bad_model_output"
    assert client.get("/api/ai/ledger").json() == {"entries": []}  # an error run writes no ledger entry


def test_route_sec_failure_is_shown_with_the_source(client, sec):
    from openterm.providers.base import ProviderError

    async def boom(url, *a, **kw):
        raise ProviderError("unavailable", "403 from SEC: set SEC_USER_AGENT in .env")

    sec.get_bytes = boom
    r = client.post("/api/ai/filing", json={"symbol": "AAPL", "form": "10-K", "question": "supplier risk"})
    assert r.status_code == 502 and r.json()["error"].startswith("SEC: ")


def test_ledger_records_the_run_with_hashes_only(client, sec):
    client.app.state.llm = FakeGateway(points_reply(GOOD, BAD))
    sse(client.post("/api/ai/filing", json={"symbol": "AAPL", "form": "10-K", "question": "What about SECRETWORD suppliers?"}))
    es = client.get("/api/ai/ledger").json()["entries"]
    assert [e["kind"] for e in es] == ["ai_filing"]
    meta = es[0]["meta"]
    assert len(meta["question_sha"]) == 64 and len(meta["answer_sha"]) == 64
    assert meta["tool_calls"][0]["name"] == "filing_search" and meta["tool_calls"][0]["ok"] is True and meta["tool_calls"][0]["source"].startswith("SEC EDGAR")
    blob = json.dumps(es)
    assert "SECRETWORD" not in blob and "limited number of suppliers" not in blob  # no question or answer text in the ledger
    assert client.get("/api/ai/ledger/verify").json()["ok"] is True


def test_secrets_never_reach_the_stream(client, sec):
    client.app.state.llm = FakeGateway([Event("error", kind="provider", text=f"OPENROUTER said no to {SECRET}")])
    r = client.post("/api/ai/filing", json={"symbol": "AAPL", "form": "10-K", "question": "supplier risk"})
    assert SECRET not in r.text and sse(r)[-1]["type"] == "error"
    # a model that echoes a key inside a claim: the claim is redacted before it is shown
    client.app.state.llm = FakeGateway(points_reply((f"Leaked {SECRET} here.", "business depends on a limited number of suppliers", "Item 1A")))
    r = client.post("/api/ai/filing", json={"symbol": "AAPL", "form": "10-K", "question": "supplier risk"})
    assert SECRET not in r.text


def test_route_picks_the_newest_10k_or_10q_unless_a_form_is_asked(client, sec):
    client.app.state.llm = FakeGateway(points_reply(GOOD), points_reply(GOOD))
    newest = next(e for e in sse(client.post("/api/ai/filing", json={"symbol": "AAPL", "question": "supplier risk"})) if e["type"] == "filing")
    assert (newest["form"], newest["filed"], newest["accession"]) == ("10-Q", "2025-02-01", "0000320193-25-000010")  # the 8-K is skipped
    asked = next(e for e in sse(client.post("/api/ai/filing", json={"symbol": "AAPL", "form": "10-K", "question": "supplier risk"})) if e["type"] == "filing")
    assert (asked["form"], asked["accession"]) == ("10-K", "0000320193-24-000123")
    assert len(sec.seen) == 2 and "000032019324000123" in sec.seen[1]


def test_a_reply_cut_off_by_the_token_budget_says_so_not_bad_json(client, sec):
    # 2026-11-07 real run: a reasoning model spent the whole budget thinking and sent no text. The error must name the budget.
    from openterm.ai import routes_filing
    from openterm.llm.events import Event

    cut = [Event("usage", prompt_tokens=1555, completion_tokens=routes_filing.MAX_OUTPUT_TOKENS, cost=0.0), Event("done")]
    client.app.state.llm = FakeGateway(cut)
    ev = sse(client.post("/api/ai/filing", json={"symbol": "aapl", "form": "10-K", "question": "What supply chain risks does the company have?"}))
    err = next(e for e in ev if e["type"] == "error")
    assert err["kind"] == "bad_model_output" and f"ALL {routes_filing.MAX_OUTPUT_TOKENS} OUTPUT TOKENS" in err["text"]
    # a short reply that is simply not JSON keeps the old message
    client.app.state.llm = FakeGateway(text("no json here"))
    ev = sse(client.post("/api/ai/filing", json={"symbol": "aapl", "form": "10-K", "question": "What supply chain risks does the company have?"}))
    assert "STRUCTURED ANSWER (JSON)" in next(e for e in ev if e["type"] == "error")["text"]
