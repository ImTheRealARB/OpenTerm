import { describe, expect, it } from "vitest";
import { subjectSymbol, swarmArgs } from "./swarmArgs";
import { newSwarm, reduceSwarm, type SwarmEvent } from "./swarmStream";
import { nextStatus, thesisArgs } from "./thesisArgs";

describe("swarmArgs", () => {
  it("no args or LIST shows presets and stored runs", () => {
    expect(swarmArgs([])).toEqual({ mode: "list" });
    expect(swarmArgs(["list"])).toEqual({ mode: "list" });
  });
  it("a preset runs on the rest of the line", () => {
    expect(swarmArgs(["committee", "AAPL"])).toEqual({ mode: "run", preset: "COMMITTEE", subject: "AAPL" });
    expect(swarmArgs(["risk", "MAIN", "book"])).toEqual({ mode: "run", preset: "RISK", subject: "MAIN book" });
    expect(swarmArgs(["macro"])).toEqual({ mode: "run", preset: "MACRO", subject: "" });
    expect(swarmArgs(["quant"]).mode).toBe("bad");
    expect(swarmArgs(["poker", "x"]).mode).toBe("bad");
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
  it("an error event ends the run with the message", () => {
    const s = reduceSwarm(reduceSwarm(newSwarm(), start), { type: "error", kind: "key_required", text: "KEY REQUIRED: set OPENROUTER in APIKEYS" });
    expect(s.status).toBe("error");
    expect(s.error?.kind).toBe("key_required");
  });
});
