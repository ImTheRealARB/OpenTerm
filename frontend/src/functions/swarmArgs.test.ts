import { describe, expect, it } from "vitest";
import { commandFor, coverageLabel, subjectSymbol, swarmArgs, type PresetInfo } from "./swarmArgs";
import { estimateLine, newSwarm, reduceSwarm, type SwarmEvent } from "./swarmStream";
import { nextStatus, thesisArgs } from "./thesisArgs";

const DESKS: PresetInfo[] = [
  desk("COMMITTEE", { needs_subject: true }),
  desk("MACRO", { needs_subject: false }),
  desk("MYDESK", {
    kind: "dag",
    variables: [
      { name: "target", description: "the ticker", required: true },
      { name: "horizon", description: "e.g. 1Y", required: false },
    ],
  }),
  desk("NEEDSBOTH", {
    kind: "dag",
    variables: [
      { name: "a", description: "", required: true },
      { name: "b", description: "", required: true },
    ],
  }),
  desk("NOFEED", { coverage: "UNAVAILABLE", limits: ["needs a tick-level feed"] }),
];

function desk(code: string, over: Partial<PresetInfo> = {}): PresetInfo {
  return {
    code,
    title: code,
    roles: [],
    note: "",
    needs_subject: true,
    coverage: "FULL",
    limits: [],
    kind: "lite",
    variables: [],
    source: "built-in",
    estimate: { roles: 3, in_tokens: 100_000, out_tokens: 10_000, usd: 0.05 },
    ...over,
  };
}

describe("swarmArgs", () => {
  it("no args or LIST shows presets and stored runs", () => {
    expect(swarmArgs([])).toEqual({ mode: "list" });
    expect(swarmArgs(["list"])).toEqual({ mode: "list" });
  });
  it("a preset runs on the rest of the line", () => {
    expect(swarmArgs(["committee", "AAPL"], DESKS)).toEqual({ mode: "run", preset: "COMMITTEE", subject: "AAPL", variables: {}, force: false });
    expect(swarmArgs(["risk", "MAIN", "book"])).toEqual({ mode: "run", preset: "RISK", subject: "MAIN book", variables: {}, force: false }); // a desk the list does not know: the server decides
    expect(swarmArgs(["macro"], DESKS)).toEqual({ mode: "run", preset: "MACRO", subject: "", variables: {}, force: false });
    expect(swarmArgs(["quant"], DESKS).mode).toBe("bad"); // unknown to the list, no subject: usage
    expect(swarmArgs(["committee"], DESKS).mode).toBe("bad");
    expect(swarmArgs(["p"]).mode).toBe("bad"); // not shaped like a desk code
    expect(swarmArgs(["has space!"]).mode).toBe("bad");
  });
  it("NAME=value fills a declared variable, in any letter case", () => {
    expect(swarmArgs(["mydesk", "TARGET=AAPL"], DESKS)).toEqual({ mode: "run", preset: "MYDESK", subject: "", variables: { target: "AAPL" }, force: false });
    expect(swarmArgs(["mydesk", "target=AAPL", "Horizon=1Y"], DESKS)).toMatchObject({ variables: { target: "AAPL", horizon: "1Y" } });
  });
  it("the subject fills the first variable that is still empty", () => {
    expect(swarmArgs(["mydesk", "AAPL"], DESKS)).toMatchObject({ mode: "run", subject: "AAPL", variables: {} });
    expect(swarmArgs(["needsboth", "B=2", "one"], DESKS)).toMatchObject({ mode: "run", subject: "one", variables: { b: "2" } }); // fills a
    expect(swarmArgs(["needsboth", "one"], DESKS).mode).toBe("bad"); // b is still missing
  });
  it("a missing required variable gives a usage line naming the variables", () => {
    const r = swarmArgs(["mydesk"], DESKS);
    expect(r.mode).toBe("bad");
    if (r.mode === "bad") expect(r.error).toContain("TARGET=<value>");
    expect(swarmArgs(["mydesk", "HORIZON=1Y"], DESKS).mode).toBe("bad"); // optional given, required still missing
    expect(swarmArgs(["mydesk", "TARGET="], DESKS).mode).toBe("bad");
  });
  it("a token with = is part of the subject unless it names a declared variable (GC=F is a ticker)", () => {
    expect(swarmArgs(["committee", "GC=F"], DESKS)).toMatchObject({ mode: "run", subject: "GC=F", variables: {} });
    expect(swarmArgs(["mydesk", "EURUSD=X"], DESKS)).toMatchObject({ mode: "run", subject: "EURUSD=X", variables: {} });
  });
  it("--force is a flag, not part of the subject", () => {
    expect(swarmArgs(["committee", "AAPL", "--force"], DESKS)).toEqual({ mode: "run", preset: "COMMITTEE", subject: "AAPL", variables: {}, force: true });
    expect(swarmArgs(["mydesk", "--FORCE", "TARGET=X"], DESKS)).toMatchObject({ force: true, variables: { target: "X" } });
  });
  it("an UNAVAILABLE desk refuses with its reason before any request", () => {
    const r = swarmArgs(["nofeed", "AAPL"], DESKS);
    expect(r).toEqual({ mode: "bad", error: "NOFEED IS UNAVAILABLE: needs a tick-level feed" });
  });
  it("REPLAY needs a 12-hex run id", () => {
    expect(swarmArgs(["replay", "0123456789AB"])).toEqual({ mode: "replay", runId: "0123456789ab" });
    expect(swarmArgs(["replay", "nope"]).mode).toBe("bad");
  });
  it("the ticker is the first upper-case word of the subject", () => {
    expect(subjectSymbol("AAPL earnings")).toBe("AAPL");
    expect(subjectSymbol("BRK-B")).toBe("BRK-B");
    expect(subjectSymbol("inflation")).toBeNull();
    expect(subjectSymbol("")).toBeNull();
  });
  it("commandFor rebuilds the command, and coverage says what is missing", () => {
    expect(commandFor({ preset: "MYDESK", subject: "", variables: { target: "AAPL" } }, "--force")).toBe("SWARM MYDESK TARGET=AAPL --force");
    expect(commandFor({ preset: "COMMITTEE", subject: "AAPL", variables: {} })).toBe("SWARM COMMITTEE AAPL");
    expect(coverageLabel({ coverage: "FULL", limits: [] })).toBe("FULL");
    expect(coverageLabel({ coverage: "PARTIAL", limits: ["no intraday", "no news"] })).toBe("PARTIAL: no intraday; no news");
  });
});

describe("thesisArgs", () => {
  it("lists all or one symbol", () => {
    expect(thesisArgs([])).toEqual({ mode: "list", symbol: null });
    expect(thesisArgs(["aapl"])).toEqual({ mode: "list", symbol: "AAPL" });
  });
  it("ADD and INVALID parse their text", () => {
    expect(thesisArgs(["add", "aapl", "services", "grow"])).toEqual({ mode: "add", symbol: "AAPL", text: "services grow" });
    expect(thesisArgs(["add", "aapl"]).mode).toBe("bad");
    expect(thesisArgs(["invalid", "3", "margin", "below", "40%"])).toEqual({ mode: "invalid", id: 3, text: "margin below 40%" });
    expect(thesisArgs(["invalid", "x", "t"]).mode).toBe("bad");
    expect(thesisArgs(["a", "b"]).mode).toBe("bad");
  });
  it("status cycles open, confirmed, invalidated, closed, open", () => {
    expect(["open", "confirmed", "invalidated", "closed"].map(nextStatus)).toEqual(["confirmed", "invalidated", "closed", "open"]);
  });
});

describe("reduceSwarm", () => {
  const start: SwarmEvent = {
    type: "swarm_start",
    preset: "COMMITTEE",
    title: "Investment committee",
    subject: "AAPL",
    model: "m",
    provider: "openrouter",
    started: "2026-10-18T10:00:00+00:00",
    roles: [
      { id: "a", title: "A", tools: ["quote"] },
      { id: "chair", title: "Chair", tools: ["quote"] },
    ],
  };
  it("tracks each role: running, tool calls, answer, failure and the final answer", () => {
    let s = reduceSwarm(newSwarm(), start);
    expect(s.roles.map((r) => r.state)).toEqual(["waiting", "waiting"]);
    s = reduceSwarm(s, { type: "role_start", role: "a", title: "A", tools: ["quote"], attempt: 1 });
    s = reduceSwarm(s, { type: "tool_call", role: "a", id: "T1", name: "quote", args: { symbols: "AAPL" } });
    s = reduceSwarm(s, { type: "token", role: "a", text: "Hel" });
    expect(s.roles[0].state).toBe("running");
    expect(s.roles[0].turn.tools).toHaveLength(1);
    expect(s.roles[0].turn.answer).toBe("Hel");
    s = reduceSwarm(s, { type: "role_done", role: "a", answer: "Hello 1 [T1]", grounded: true, label: null, unsourced: [], tool_calls: 1, cost: 0.002, stopped: null });
    expect(s.roles[0].state).toBe("done");
    expect(s.roles[0].turn.answer).toBe("Hello 1 [T1]");
    s = reduceSwarm(s, { type: "role_error", role: "chair", kind: "provider", text: "DOWN" });
    s = reduceSwarm(s, { type: "role_retry", role: "chair", attempt: 2, why: "provider: DOWN" });
    s = reduceSwarm(s, { type: "role_start", role: "chair", title: "Chair", tools: [], attempt: 2 });
    expect(s.roles[1].errors).toHaveLength(2);
    expect(s.roles[1].attempt).toBe(2);
    s = reduceSwarm(s, { type: "saved", run_id: "0123456789ab" });
    s = reduceSwarm(s, { type: "swarm_done", answer: "Final", cost: 0.004, unsourced: ["9.9"], grounded: true, label: null, failed: [] });
    expect(s.status).toBe("done");
    expect(s.final?.unsourced).toEqual(["9.9"]);
    expect(s.runId).toBe("0123456789ab");
    expect(s.cost).toBe(0.004);
  });
  it("keeps coverage, limits and variables from the start and the estimate that follows", () => {
    let s = reduceSwarm(newSwarm(), { ...start, coverage: "PARTIAL", limits: ["no intraday"], variables: { target: "AAPL" } });
    expect(s.coverage).toBe("PARTIAL");
    expect(s.limits).toEqual(["no intraday"]);
    expect(s.variables).toEqual({ target: "AAPL" });
    s = reduceSwarm(s, { type: "estimate", roles: 2, in_tokens: 340_000, out_tokens: 12_000, usd: 0.0712, cap_left: 4.9 });
    expect(s.estimate?.usd).toBe(0.0712);
    s = reduceSwarm(s, { type: "swarm_done", answer: "", cost: 0.01, unsourced: [], grounded: false, label: "UNGROUNDED", failed: ["a"], capped: true });
    expect(s.capped).toBe(true);
    // a stored run from before Phase 20 has none of these fields: it still shows as a FULL desk
    const old = reduceSwarm(newSwarm(), start);
    expect(old.coverage).toBe("FULL");
    expect(old.limits).toEqual([]);
    expect(old.capped).toBe(false);
  });
  it("estimateLine says worst case, tokens and dollars, and admits an unknown price", () => {
    expect(estimateLine({ in_tokens: 340_000, out_tokens: 12_000, usd: 0.0712, cap_left: 4.9 })).toBe("WORST CASE 340K TOKENS READ + 12K WRITTEN · US$0.07 · US$4.90 LEFT OF TODAY'S CAP");
    expect(estimateLine({ in_tokens: 1_250_000, out_tokens: 400, usd: null })).toBe("WORST CASE 1.3M TOKENS READ + 1K WRITTEN · PRICE UNKNOWN FOR THIS MODEL");
  });
  it("an error event ends the run with the message", () => {
    const s = reduceSwarm(reduceSwarm(newSwarm(), start), { type: "error", kind: "key_required", text: "KEY REQUIRED: set OPENROUTER in APIKEYS" });
    expect(s.status).toBe("error");
    expect(s.error?.kind).toBe("key_required");
  });
});
