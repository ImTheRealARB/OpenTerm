import { describe, expect, it } from "vitest";
import { citeSegments, codeDraftStatus, newTurn, numberedLines, reduceTurn, stopTurn, turnLine, type AiEvent } from "./aiStream";

// The SSE parser (`parseSse`) moved to net/sse.ts; its tests are in net/sse.test.ts.

describe("reduceTurn", () => {
  it("builds a grounded answer with a tool row", () => {
    let t = newTurn("AAPL?");
    for (const e of [
      { type: "start", model: "m/x", provider: "openrouter", started: "2026-10-18T10:00:00+00:00" },
      { type: "tool_call", id: "T1", name: "quote", args: { symbols: "AAPL" } },
      { type: "tool_result", id: "T1", name: "quote", ok: true, empty: false, source: "yahoo", age_s: 2, stale: false, bytes: 200, summary: "{}" },
      { type: "token", text: "AAPL is " },
      { type: "token", text: "343.46 [T1]." },
      { type: "usage", prompt_tokens: 10, completion_tokens: 5, cost: 0.001 },
      { type: "done", answer: "AAPL is 343.46 [T1].", grounded: true, label: null, unsourced: [], tool_calls: 1, cost: 0.001, stopped: null },
    ] as AiEvent[]) t = reduceTurn(t, e);
    expect(t.status).toBe("done");
    expect(t.answer).toBe("AAPL is 343.46 [T1].");
    expect(t.tools).toEqual([{ id: "T1", name: "quote", args: { symbols: "AAPL" }, state: "ok", source: "yahoo", age_s: 2, stale: false, summary: "{}" }]);
    expect(t.model).toBe("m/x");
    expect(t.cost).toBeCloseTo(0.001);
    expect(turnLine(t)).toBe("AI · m/x · 10:00:00Z · MODEL OUTPUT, NOT DATA · US$0.0010");
  });

  it("marks failed and empty tool results, notices and ungrounded answers", () => {
    let t = newTurn("q");
    for (const e of [
      { type: "tool_call", id: "T1", name: "quote", args: {} },
      { type: "tool_result", id: "T1", name: "quote", ok: false, empty: false, source: null, age_s: null, stale: false, bytes: 9, summary: "HTTP 500" },
      { type: "tool_call", id: "T2", name: "news", args: {} },
      { type: "tool_result", id: "T2", name: "news", ok: true, empty: true, source: "rss", age_s: 1, stale: true, bytes: 2, summary: "{}" },
      { type: "notice", text: "STOPPED: x" },
      { type: "done", answer: "none", grounded: false, label: "UNGROUNDED", unsourced: ["9.9"], tool_calls: 2, cost: 0, stopped: "x" },
    ] as AiEvent[]) t = reduceTurn(t, e);
    expect(t.tools.map((x) => x.state)).toEqual(["failed", "empty"]);
    expect(t.tools[1].stale).toBe(true);
    expect(t.notices).toEqual(["STOPPED: x"]);
    expect(t.label).toBe("UNGROUNDED");
    expect(t.unsourced).toEqual(["9.9"]);
  });

  it("an error ends the turn and keeps the kind; KEY REQUIRED text is shown as is", () => {
    const t = reduceTurn(newTurn("q"), { type: "error", kind: "key_required", text: "KEY REQUIRED: set OPENROUTER in APIKEYS" });
    expect(t.status).toBe("error");
    expect(t.error).toEqual({ kind: "key_required", text: "KEY REQUIRED: set OPENROUTER in APIKEYS" });
  });

  it("streamed tokens show before done; done's answer wins", () => {
    let t = reduceTurn(newTurn("q"), { type: "token", text: "par" });
    expect(t.status).toBe("running");
    expect(t.answer).toBe("par");
    t = reduceTurn(t, { type: "done", answer: "full", grounded: false, label: "UNGROUNDED", unsourced: [], tool_calls: 0, cost: 0, stopped: null });
    expect(t.answer).toBe("full");
  });
});

describe("draft events", () => {
  it("keeps a validated BT draft and a draft error on the turn", () => {
    const d = { symbols: ["AAPL"], rule: "SMA20 CROSS> SMA50", range: "5Y", interval: "1D", rationale: "r", command: "BT AAPL SMA20 CROSS> SMA50 1D 5Y", note: "n" };
    let t = reduceTurn(newTurn("idea"), { type: "draft", draft: d });
    expect(t.draft).toEqual(d);
    t = reduceTurn(newTurn("idea"), { type: "draft_error", text: "NOT VALID" });
    expect(t.draftError).toBe("NOT VALID");
    expect(t.draft).toBeUndefined();
  });
});

describe("citeSegments", () => {
  it("splits text around [T1] markers", () => {
    expect(citeSegments("a 1 [T1] b [T12].")).toEqual([{ text: "a 1 " }, { cite: "T1" }, { text: " b " }, { cite: "T12" }, { text: "." }]);
    expect(citeSegments("plain")).toEqual([{ text: "plain" }]);
    expect(citeSegments("1. claim [Q2]")).toEqual([{ text: "1. claim " }, { cite: "Q2" }]); // AI FILING quote markers
    expect(citeSegments("")).toEqual([]);
  });
});

describe("AI FILING events", () => {
  it("keeps the filing, the passages and each quote's verdict on the turn", () => {
    let t = newTurn("AI FILING AAPL supplier risk");
    t = reduceTurn(t, { type: "filing", symbol: "AAPL", form: "10-K", filed: "2024-11-01", accession: "0000320193-24-000123", url: "u", source: "SEC EDGAR", sections: 4, passages: 9, mode: "ask" });
    t = reduceTurn(t, { type: "passages", items: [{ id: "P1", section: "Item 1A. Risk Factors", chars: 1200, preview: "..." }] });
    t = reduceTurn(t, {
      type: "quotes",
      items: [
        { n: 1, claim: "c1", quote: "q1", claimed_section: "Item 1A", section: "Item 1A. Risk Factors", verified: true, reason: "EXACT MATCH" },
        { n: 2, claim: "c2", quote: "q2", claimed_section: null, section: null, verified: false, reason: "NOT FOUND IN THE FILING (PARAPHRASED OR INVENTED)" },
      ],
    });
    expect(t.filing).toMatchObject({ symbol: "AAPL", form: "10-K", accession: "0000320193-24-000123" });
    expect("type" in (t.filing as object)).toBe(false); // the event tag is not kept
    expect(t.passages?.[0].id).toBe("P1");
    expect(t.quotes?.map((q) => q.verified)).toEqual([true, false]);
  });
});

describe("stopTurn", () => {
  it("cuts a running turn short and says why", () => {
    const t = stopTurn(newTurn("q"), "CANCELLED");
    expect(t.status).toBe("done");
    expect(t.label).toBe("INCOMPLETE");
    expect(t.notices).toEqual(["CANCELLED"]);
  });
  it("leaves a finished turn alone", () => {
    const done = { ...newTurn("q"), status: "done" as const };
    expect(stopTurn(done, "CANCELLED")).toBe(done);
  });
  it("Esc after the answer finished shows no CANCELLED (ESC) and keeps the label", () => {
    const done = { ...newTurn("q"), status: "done" as const, label: "GROUNDED" };
    const after = stopTurn(done, "CANCELLED (ESC)");
    expect(after.notices).not.toContain("CANCELLED (ESC)");
    expect(after.label).toBe("GROUNDED");
  });
});

describe("code drafts (AI BT CODE)", () => {
  const draft = { code: "class SignalEngine:\n    pass\n", name: "x", ok: true, error: null, line: null, repaired: false, note: "n" };
  it("the reducer keeps the draft and the status line says what the check found", () => {
    const t = reduceTurn(newTurn("AI BT CODE x"), { type: "code_draft", draft });
    expect(t.codeDraft).toEqual(draft);
    expect(codeDraftStatus(draft)).toBe("SANDBOX CHECK PASSED");
    expect(codeDraftStatus({ ...draft, repaired: true })).toBe("SANDBOX CHECK PASSED AFTER ONE REPAIR");
    expect(codeDraftStatus({ ...draft, ok: false, repaired: true, error: "LINE 1: IMPORT os IS NOT ALLOWED" })).toBe(
      "SANDBOX CHECK FAILED AFTER ONE REPAIR: LINE 1: IMPORT os IS NOT ALLOWED",
    );
  });
  it("numbers the lines of the code", () => {
    expect(numberedLines("a\nb\n")).toEqual(["1  a", "2  b"]);
    expect(numberedLines(Array.from({ length: 10 }, () => "x").join("\n"))[0]).toBe(" 1  x");
  });
});
