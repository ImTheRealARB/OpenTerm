"""`POST /api/ai/filing` (Phase 20 step 9): `AI FILING <SYM> <question>` and `AI FILING <SYM> DRIVERS`. SSE, loopback only, like the other AI routes.

Pipeline (the pure parts are in `filings.py`): newest 10-K / 10-Q of a US filer from SEC EDGAR -> text -> Items -> passages -> FTS5 / BM25 search ->
the model answers from those passages and returns quotes -> every quote is checked against the filing text. This module is the glue: it fetches,
caches, calls the model, emits events the panel shows, and hands the stream to the same audit ledger as every other AI run.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import AsyncIterator

from fastapi import Request
from fastapi.responses import Response

from .. import api as api_mod
from .. import http_util
from ..idents import AI_SYMBOL_RE
from ..providers.base import ProviderError
from ..providers.sec import UA_HINT, US_ONLY, sec_ticker
from ..redact import redact
from . import (  # both are light (stdlib sqlite3 and html parsing); nothing heavy is imported here
    filings,
    ground,
)
from .routes import (
    MAX_QUESTION,
    _body,
    _models,
    _stream,
    ai_settings,
    audit,
    router,
)

CACHE_SIZE = 3  # parsed filings kept in memory (a 10-K is a few MB of text); asking again about the same filing re-downloads nothing
SOURCE = "SEC EDGAR"
MAX_FILING_BYTES = 12 * 1024 * 1024
TOOL = "filing_search"  # a "tool" in the panel's sense (a call with a source and an age), though here the server runs it, not the model


def _cache(request: Request) -> OrderedDict:
    st = getattr(request.app.state, "ai_filings", None)
    if st is None:
        st = request.app.state.ai_filings = OrderedDict()
    return st


# Output budget for one filing answer. It was 1,800: on 2026-11-07 a real run with deepseek-v4.1-flash (a reasoning model)
# spent all 1,800 tokens thinking and returned no answer at all. Reasoning models (the default deepseek-v4-pro is one too)
# count their thinking in this budget. 4,000 leaves room for both; the daily spend cap still checks the worst case
# (MAX_OUTPUT_TOKENS x the model's output price) before the call is made.
MAX_OUTPUT_TOKENS = 4000
OUT_OF_TOKENS = (f"THE MODEL USED ALL {MAX_OUTPUT_TOKENS} OUTPUT TOKENS (A REASONING MODEL THINKS IN THEM TOO) BEFORE IT ANSWERED: "
                 "ASK A NARROWER QUESTION OR PICK A NON-REASONING MODEL")

async def load_filing(request: Request, symbol: str, form: str | None) -> filings.ParsedFiling:
    """Newest 10-K / 10-Q (or the asked form) with a document, parsed. Raises ProviderError (SEC trouble) or FilingsError (unreadable filing)."""
    sec = http_util.svc(request).router.providers["sec"]
    listing = (await sec.filings(symbol.upper())).get("filings") or []
    wanted = (form,) if form else filings.FORMS
    hit = next((f for f in listing if f.get("form") in wanted and f.get("doc_url")), None)
    if hit is None:
        raise ProviderError("not_found", f"NO {' OR '.join(wanted)} FILING WITH A DOCUMENT FOR {symbol.upper()} IN THE LATEST SEC LIST")
    cache = _cache(request)
    key = (symbol.upper(), hit["accession"])
    if key in cache:
        cache.move_to_end(key)
        return cache[key]
    raw = await sec.get_bytes(hit["doc_url"])
    if len(raw) > MAX_FILING_BYTES:
        raise filings.FilingsError("THE FILING DOCUMENT IS OVER 12 MB")
    parsed = await asyncio.to_thread(  # parsing a 3 MB HTML file takes ~1 s of CPU: keep it off the event loop
        filings.parse_filing, raw.decode("utf-8", errors="replace"), symbol=symbol.upper(), form=hit["form"], filed=hit.get("filed") or "",
        accession=hit["accession"], url=hit.get("url") or hit["doc_url"], fetched_at=time.time())
    cache[key] = parsed
    while len(cache) > CACHE_SIZE:
        cache.popitem(last=False)
    return parsed


@router.post("/filing")
async def ai_filing(request: Request):
    t0 = time.perf_counter()
    body = await _body(request)
    if isinstance(body, Response):
        return body
    symbol = str(body.get("symbol") or "")
    drivers = body.get("mode") == "drivers"
    question = filings.DRIVERS_QUESTION if drivers else body.get("question")
    form = str(body["form"]).upper() if body.get("form") else None
    if not AI_SYMBOL_RE.match(symbol) or (form is not None and form not in filings.FORMS):
        return http_util.error_response(400, "bad_request", f"SYMBOL MUST BE A TICKER AND FORM ONE OF {', '.join(filings.FORMS)}")
    if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION:
        return http_util.error_response(400, "bad_request", f"QUESTION MUST BE 1-{MAX_QUESTION} CHARACTERS (OR mode \"drivers\")")
    names = _models(body, await ai_settings(request))
    if names is None:
        return http_util.error_response(400, "bad_request", "MODEL OR PROVIDER NAME IS NOT VALID")
    if sec_ticker(symbol) is None:
        return http_util.error_response(400, "unsupported", f"{US_ONLY}: {symbol.upper()} IS NOT A US SEC FILER")
    if not http_util.svc(request).router.providers["sec"].ua_set:  # SEC may refuse an anonymous client; say how to fix it before any work is done
        return http_util.error_response(400, "key_required", f"KEY REQUIRED: SEC_USER_AGENT IS NOT SET ({UA_HINT})")
    try:
        filing = await load_filing(request, symbol, form)
    except ProviderError as e:
        status = {"not_found": 404, "unsupported": 400}.get(e.kind, 502)
        return http_util.error_response(status, "provider" if status == 502 else e.kind, redact(f"SEC: {str(e)[:160]}"))
    except filings.FilingsError as e:
        return http_util.error_response(422, "bad_filing", str(e))
    questions = list(filings.DRIVERS_THEMES.values()) if drivers else [question.strip()]
    try:
        hits = await asyncio.to_thread(filings.retrieve, filing.passages, questions,
                                       filings.DRIVERS_PER_THEME if drivers else filings.MAX_HITS,
                                       filings.DRIVERS_PER_THEME * len(questions) if drivers else filings.MAX_HITS)
    except filings.FilingsError as e:
        return http_util.error_response(500, "unavailable", str(e))
    gateway = api_mod.llm_of(request)
    model, provider = names
    ask = question.strip()

    async def events() -> AsyncIterator[dict]:
        now = time.gmtime()
        yield {"type": "start", "model": model, "provider": provider, "started": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", now)}
        yield {"type": "filing", "symbol": filing.symbol, "form": filing.form, "filed": filing.filed, "accession": filing.accession, "url": filing.url,
               "source": SOURCE, "sections": len(filing.sections), "passages": len(filing.passages), "mode": "drivers" if drivers else "ask"}
        args = {"symbol": filing.symbol, "form": filing.form, "accession": filing.accession, "mode": "drivers" if drivers else "ask"}
        yield {"type": "tool_call", "id": "T1", "name": TOOL, "args": args}
        sections = sorted({h.section for h in hits})
        yield {"type": "tool_result", "id": "T1", "name": TOOL, "ok": True, "empty": not hits, "source": f"{SOURCE} {filing.form} {filing.filed}",
               "age_s": max(0.0, time.time() - filing.fetched_at), "stale": False, "bytes": sum(len(h.text) for h in hits),
               "summary": f"{len(hits)} PASSAGES FROM {'; '.join(sections)[:160]}" if hits else "NO PASSAGE MATCHES THE QUESTION"}
        yield {"type": "passages", "items": [{"id": h.pid, "section": h.section, "chars": len(h.text), "preview": h.text[:240]} for h in hits]}
        if not hits:  # nothing retrieved: no model call, no spend, and the answer says so
            yield {"type": "done", "answer": "NO PASSAGE OF THE FILING MATCHES THIS QUESTION: TRY OTHER WORDS.", "grounded": False, "label": "UNGROUNDED",
                   "unsourced": [], "tool_calls": 1, "cost": 0.0, "stopped": None, "verified": 0, "unverified": 0}
            return
        messages = filings.build_messages(filing.symbol, filing.form, filing.filed, ask, hits, time.strftime("%Y-%m-%d", now))
        parts: list[str] = []
        cost = 0.0
        used = 0  # output tokens the provider reports: tells "ran out of budget" apart from "answered badly"
        # Tokens are NOT forwarded: the reply is JSON for us to check, and showing half a JSON object is noise. The user sees the checked answer.
        async for ev in gateway.chat(messages, model, provider, None, MAX_OUTPUT_TOKENS, 0.1):
            if ev.type == "token":
                parts.append(ev.text)
            elif ev.type == "usage":
                cost += ev.cost or 0.0
                used = max(used, ev.completion_tokens or 0)
                yield {"type": "usage", "prompt_tokens": ev.prompt_tokens, "completion_tokens": ev.completion_tokens, "cost": ev.cost}
            elif ev.type == "error":
                yield {"type": "error", "kind": ev.kind, "text": redact(ev.text)}
                return
        try:
            points = filings.parse_points("".join(parts))
        except filings.FilingsError as e:
            if used >= MAX_OUTPUT_TOKENS:  # the budget ran out first (a reasoning model thinks in these tokens too): say so, not "bad JSON"
                yield {"type": "error", "kind": "bad_model_output", "text": OUT_OF_TOKENS}
            else:
                yield {"type": "error", "kind": "bad_model_output", "text": str(e)}
            return
        checked = filings.verify_points(points, filing.full_norm, filing.sections)
        for c in checked:  # a claim is model output: mask any key it might echo, as every error text is masked
            c["claim"] = redact(c["claim"])
        yield {"type": "quotes", "items": checked}
        summary = filings.rebuild_summary(checked)
        good = sum(1 for c in checked if c["verified"])
        # Numbers in the (verified-only) summary must appear in the retrieved passages, the same check every AI panel makes.
        unsourced = ground.check(summary, [h.text for h in hits]) if good else []
        yield {"type": "done", "answer": summary, "grounded": True, "label": None, "unsourced": unsourced, "tool_calls": 1, "cost": cost, "stopped": None,
               "verified": good, "unverified": len(checked) - good}

    system_for_audit = filings.FILING_SYSTEM
    tag = "DRIVERS" if drivers else ask
    stream = audit(request, events(), "ai_filing", system_for_audit, f"{symbol.upper()} {tag}", [TOOL], model, provider)
    return _stream(request, t0, stream)
