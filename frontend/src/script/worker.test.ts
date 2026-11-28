import { beforeEach, describe, expect, it } from "vitest";
import { dropScripts, handleScript, handleScriptTick, isScriptMsg, routeScript, runCount, type ScriptReq, type ScriptRes, type ScriptTickRes } from "./worker";
import { barsFromCloses } from "./testkit";

const H = `indicator("t")\n`;
const cols = (c: number[]) => {
  const b = barsFromCloses(c);
  return { o: Float64Array.from(b.o), h: Float64Array.from(b.h), l: Float64Array.from(b.l), c: Float64Array.from(b.c), v: Float64Array.from(b.v), t: Float64Array.from(b.t ?? []) };
};
const req = (source: string, over: Partial<ScriptReq> = {}): ScriptReq => ({
  type: "script", id: 1, key: "c1|T", name: "T", source, rawInputs: [], symbol: "AAPL", bars: cols([1, 2, 3, 4, 5]), ...over,
});
const ok = (r: { msg: ScriptRes | ScriptTickRes }) => {
  const m = r.msg as ScriptRes;
  if (m.status !== "ok") throw new Error(`expected ok, got ${m.status}`);
  return m;
};

beforeEach(() => dropScripts(""));

describe("handleScript", () => {
  it("compiles and runs, and describes the script", () => {
    const m = ok(handleScript(req(H + 'plot(close * 2, "twice")\nhline(3, "mid")\n')));
    expect(m.info).toMatchObject({ title: "t", overlay: false });
    expect(m.result.plots.map((p) => p.kind)).toEqual(["plot", "hline"]);
    expect(Array.from(m.result.plots[0].values!)).toEqual([2, 4, 6, 8, 10]);
    expect(m.id).toBe(1);
    expect(m.key).toBe("c1|T");
  });

  it("transfers every typed-array buffer it returns", () => {
    const r = handleScript(req(H + 'plot(close, "a")\nplot(open, "b")\nalertcondition(close > 2, "up")\n'));
    const m = ok(r);
    const bufs = new Set<ArrayBuffer>([...m.result.plots.map((p) => p.values!.buffer as ArrayBuffer), ...m.result.conditions.map((c) => c.values.buffer as ArrayBuffer)]);
    expect(r.transfer).toHaveLength(3);
    expect(new Set(r.transfer)).toEqual(bufs);
  });

  it("returns a compile error with line and column, and keeps no run", () => {
    const r = handleScript(req(H + "plot(nosuchname)\n"));
    const m = r.msg as ScriptRes;
    expect(m.status).toBe("error");
    if (m.status !== "error") return;
    expect(m.stage).toBe("compile");
    expect(m.errors[0]).toMatchObject({ line: 2 });
    expect(m.errors[0].msg).toMatch(/NOSUCHNAME/);
    expect(runCount()).toBe(0);
  });

  it("applies raw positional inputs and reports a bad one by name", () => {
    const src = H + 'len = input.int(2, "Length")\nplot(ta.sma(close, len), "x")\n';
    const m = ok(handleScript(req(src, { rawInputs: ["3"] })));
    expect(Array.from(m.result.plots[0].values!).slice(2)).toEqual([2, 3, 4]); // sma(3) of 1..5
    expect(m.info.inputs.map((i) => i.title)).toEqual(["Length"]);
    const bad = handleScript(req(src, { rawInputs: ["abc"] })).msg as ScriptRes;
    expect(bad.status).toBe("error");
    if (bad.status === "error") {
      expect(bad.stage).toBe("inputs");
      expect(bad.errors[0].msg).toBe("LENGTH NEEDS A NUMBER");
    }
  });

  it("a runtime error comes back inside the result (with the bar), not as a crash", () => {
    const m = ok(handleScript(req(H + 'x = array.new(1, 0)\nplot(array.get(x, 5), "x")\n')));
    expect(m.result.error?.bar).toBe(0);
    expect(m.result.error?.msg).toMatch(/\S/);
  });

  it("asks for another symbol's bars, then runs when they are sent", () => {
    const src = H + 'plot(request("MSFT", "1D", close), "m")\n';
    const first = handleScript(req(src)).msg as ScriptRes;
    expect(first.status).toBe("needs");
    if (first.status !== "needs") return;
    expect(first.needs).toEqual([{ symbol: "MSFT", timeframe: "1D" }]);
    expect(runCount()).toBe(0);
    const msft = barsFromCloses([10, 20, 30, 40, 50]);
    const m = ok(handleScript(req(src, { requests: { "MSFT|1D": msft } })));
    expect(Array.from(m.result.plots[0].values!)).toEqual([10, 20, 30, 40, 50]);
  });

  it("answers a request for the chart's own symbol from the chart's bars (no fetch)", () => {
    const m = ok(handleScript(req(H + 'plot(request("aapl", "1D", close), "m")\n', { chartTf: "1D" })));
    expect(Array.from(m.result.plots[0].values!)).toEqual([1, 2, 3, 4, 5]);
  });

  it("builds a longer timeframe of the chart's own symbol", () => {
    // 5 daily bars -> weekly buckets (Mondays). The result is a plot over the daily bars of the weekly close, no look-ahead.
    const m = ok(handleScript(req(H + 'plot(request("AAPL", "1W", close), "w")\n', { chartTf: "1D" })));
    expect(m.result.error).toBeUndefined();
    expect(m.result.plots[0].values).toHaveLength(5);
  });
});

describe("live ticks", () => {
  const src = H + 'plot(close, "c")\nif barstate.islast and close > 5\n    alert("big")\n';

  it("updateLast re-runs only the newest bar and reports its values and alerts", () => {
    ok(handleScript(req(src)));
    const t = (isNew: boolean, c: number): ScriptTickRes["tick"] =>
      (handleScriptTick({ type: "script-tick", id: 2, key: "c1|T", isNew, bar: { o: c, h: c + 1, l: c - 1, c, v: 10, t: 1_700_006_400 + 4 * 86400 } }).msg as ScriptTickRes).tick;
    const quiet = t(false, 4.5);
    expect(quiet?.bar).toBe(4);
    expect(quiet?.plots[0].v).toBe(4.5);
    expect(quiet?.alerts).toEqual([]);
    const loud = t(false, 7);
    expect(loud?.plots[0].v).toBe(7);
    expect(loud?.alerts.map((a) => a.message)).toEqual(["big"]);
  });

  it("append opens a new bar", () => {
    ok(handleScript(req(src)));
    const r = handleScriptTick({ type: "script-tick", id: 3, key: "c1|T", isNew: true, bar: { o: 8, h: 9, l: 7, c: 8, v: 1, t: 1_700_006_400 + 5 * 86400 } });
    const tick = (r.msg as ScriptTickRes).tick!;
    expect(tick.n).toBe(6);
    expect(tick.bar).toBe(5);
    expect(tick.alerts.map((a) => a.message)).toEqual(["big"]);
  });

  it("a tick for an unknown run is null, never a crash", () => {
    const r = handleScriptTick({ type: "script-tick", id: 4, key: "nope", isNew: false, bar: { o: 1, h: 1, l: 1, c: 1, v: 1 } });
    expect((r.msg as ScriptTickRes).tick).toBeNull();
  });
});

describe("routing and cleanup", () => {
  it("recognises its own messages only", () => {
    expect(isScriptMsg({ type: "script" })).toBe(true);
    expect(isScriptMsg({ type: "script-tick" })).toBe(true);
    expect(isScriptMsg({ type: "script-drop", prefix: "" })).toBe(true);
    expect(isScriptMsg({ type: "library" })).toBe(false);
    expect(isScriptMsg({ id: 1, series: {}, which: [] })).toBe(false);
    expect(isScriptMsg(null)).toBe(false);
  });

  it("script-drop forgets a chart's runs by prefix", () => {
    ok(handleScript(req(H + 'plot(close, "a")\n', { key: "c1|A" })));
    ok(handleScript(req(H + 'plot(close, "a")\n', { key: "c1|B" })));
    ok(handleScript(req(H + 'plot(close, "a")\n', { key: "c2|A" })));
    expect(runCount()).toBe(3);
    expect(routeScript({ type: "script-drop", prefix: "c1|" })).toBeNull();
    expect(runCount()).toBe(1);
  });

  it("a second run with the same key replaces the first (no leak)", () => {
    ok(handleScript(req(H + 'plot(close, "a")\n')));
    ok(handleScript(req(H + 'plot(close, "a")\n')));
    expect(runCount()).toBe(1);
  });
});
