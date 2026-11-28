/**
 * The script controller end to end, with the network and the chart faked: source fetch -> worker (the real `handleScript`, run
 * in-process) -> draw -> live ticks -> alerts. The chart library, the request layer and the alert path are replaced by recorders.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({ fired: [] as unknown[], sources: {} as Record<string, string>, history: vi.fn() }));

vi.mock("lightweight-charts", () => ({
  AreaSeries: "Area", HistogramSeries: "Histogram", LineSeries: "Line",
  LineStyle: { Solid: 0, Dotted: 1, Dashed: 2 }, LineType: { Simple: 0, WithSteps: 1 },
}));
vi.mock("../net/core", () => ({
  ApiError: class ApiError extends Error {
    constructor(public status: number, message: string) {
      super(message);
    }
  },
}));
vi.mock("../net/scriptsApi", async () => {
  const { ApiError } = await import("../net/core");
  return {
    scriptsApi: {
      get: async (name: string) => {
        if (!(name in h.sources)) throw new ApiError(404, "NOT FOUND");
        return { name, source: h.sources[name] };
      },
    },
  };
});
vi.mock("../net/marketApi", () => ({ marketApi: { history: h.history } }));
vi.mock("../perf/metrics", () => ({ gauges: { set: vi.fn() } }));
vi.mock("../command/alerts", () => ({ fireScriptAlert: (p: unknown) => void h.fired.push(p) }));

import { createScriptController, type ScriptController } from "./scriptLayer";
import { routeScript, dropScripts, type ScriptMsg } from "../script/worker";
import { barsFromCloses } from "../script/testkit";
import type { ScriptHost, ScriptReport } from "./scriptTypes";
import type { BarData, ThemeColors } from "./chartBase";

const theme = { bg: "#000", fg: "#fff", dim: "#888", up: "#0f0", down: "#f00", line: "#333", acc: "#ffa028", warn: "#fa0", val: "#eee", font: "mono", fs: 12 } as ThemeColors;
const H = `indicator("t")\n`;

/** A fake lightweight-charts series that records what it was given. */
function fakeSeries() {
  const s = {
    kind: "", data: [] as unknown[], updates: [] as unknown[], lines: [] as unknown[], removedLines: 0,
    setData(d: unknown[]) { s.data = d; },
    update(d: unknown) { s.updates.push(d); },
    createPriceLine(o: unknown) { s.lines.push(o); return o; },
    removePriceLine() { s.removedLines++; },
    priceToCoordinate: (v: number) => 200 - v,
    getPane: () => ({ getHTMLElement: () => null }),
  };
  return s;
}

function setup(closes = [1, 2, 3, 4, 5], interval = "1d") {
  const b = barsFromCloses(closes);
  const data: BarData = { symbol: "AAPL", interval, tz: "UTC", t: Float64Array.from(b.t as number[]), o: Float64Array.from(b.o as number[]), h: Float64Array.from(b.h as number[]), l: Float64Array.from(b.l as number[]), c: Float64Array.from(b.c as number[]), v: Float64Array.from(b.v as number[]) };
  const series: ReturnType<typeof fakeSeries>[] = [];
  const panes: number[] = [];
  const chart = {
    addSeries: (def: string, _opts: unknown, pane: number) => { const s = fakeSeries(); s.kind = def; series.push(s); panes.push(pane); return s; },
    removeSeries: vi.fn(),
    panes: () => [0, ...new Set(panes.filter((p) => p > 0))].map((_, i) => i),
    priceScale: () => ({ width: () => 50 }),
  };
  const main = fakeSeries();
  const reports: ScriptReport[] = [];
  const marks: unknown[][] = [];
  let ctl: ScriptController;
  const posted: ScriptMsg[] = [];
  const host: ScriptHost = {
    chart: () => chart as never,
    main: () => main as never,
    data: () => data,
    colors: () => theme,
    box: () => null,
    props: () => ({ items: [], symbol: "AAPL", range: "1Y", synthetic: true, onReport: (r) => void reports.push(r) }),
    post: (m) => {
      posted.push(m as ScriptMsg);
      const r = routeScript(m as ScriptMsg);
      // the real worker answers asynchronously
      if (r) queueMicrotask(() => ctl.onMessage(r.msg));
    },
    keepRange: (fn) => fn(),
    layoutPanes: () => {},
    publish: () => {},
    setMarks: (m) => void marks.push(m),
    repaint: () => {},
  };
  ctl = createScriptController(host);
  // every hop is a promise or a microtask (the fakes answer at once), so a run of microtask turns is enough
  const settle = async () => { for (let i = 0; i < 60; i++) await Promise.resolve(); };
  const last = () => reports[reports.length - 1] ?? {};
  return { ctl, series, panes, main, reports, marks, posted, settle, last, data, chart };
}

beforeEach(() => {
  h.fired.length = 0;
  h.history.mockReset();
  for (const k of Object.keys(h.sources)) delete h.sources[k];
  dropScripts("");
});

const ref = (name: string, inputs: string[] = []) => ({ name, inputs });

describe("loading and drawing", () => {
  it("fetches, runs and draws plots as series, hlines as price lines, shapes as marks", async () => {
    h.sources.A = H + 'plot(close, "c")\nhline(3, "mid")\nplotshape(close > 3, "s", "triangleup", "belowbar")\n';
    const t = setup();
    t.ctl.sync([ref("A")]);
    expect(t.last().A.state).toBe("loading");
    await t.settle();
    expect(t.last().A).toMatchObject({ state: "ready", error: "", title: "t" });
    // not an overlay script: its series are in a pane below the price pane
    expect(t.series).toHaveLength(1);
    expect(t.panes).toEqual([1]);
    expect(t.series[0].data).toHaveLength(5);
    expect(t.series[0].lines).toHaveLength(1);
    expect(t.marks[t.marks.length - 1]).toHaveLength(2);
    expect(t.ctl.seriesCount()).toBe(1);
  });

  it("an overlay script goes on the price pane and its hlines on the price series", async () => {
    h.sources.A = `indicator("t", overlay=true)\nplot(close, "c")\nhline(3, "mid")\n`;
    const t = setup();
    t.ctl.sync([ref("A")]);
    await t.settle();
    expect(t.panes).toEqual([0]);
    expect(t.main.lines).toHaveLength(1);
  });

  it("leaves an unchanged script alone on the next sync and replaces one whose inputs changed", async () => {
    h.sources.A = H + 'n = input.int(2, "N")\nplot(ta.sma(close, n), "m")\n';
    const t = setup();
    t.ctl.sync([ref("A")]);
    await t.settle();
    const first = t.posted.length;
    t.ctl.sync([ref("A")]);
    await t.settle();
    expect(t.posted.length).toBe(first); // nothing sent again
    t.ctl.sync([ref("A", ["3"])]);
    await t.settle();
    expect(t.posted.length).toBeGreaterThan(first);
    expect(t.last().A.state).toBe("ready");
  });

  it("removing a script from the args takes its series and price lines off", async () => {
    h.sources.A = H + 'plot(close, "c")\nhline(3, "mid")\n';
    const t = setup();
    t.ctl.sync([ref("A")]);
    await t.settle();
    t.ctl.sync([]);
    expect(t.chart.removeSeries).toHaveBeenCalledTimes(1);
    expect(t.series[0].removedLines).toBe(1);
    expect(t.ctl.seriesCount()).toBe(0);
  });
});

describe("errors are shown, never silent", () => {
  it("SCRIPT NOT FOUND", async () => {
    const t = setup();
    t.ctl.sync([ref("NOPE")]);
    await t.settle();
    expect(t.last().NOPE).toMatchObject({ state: "error", error: "SCRIPT NOT FOUND: NOPE" });
  });

  it("a compile error carries the script name and line:col", async () => {
    h.sources.BAD = H + "plot(nosuch)\n";
    const t = setup();
    t.ctl.sync([ref("BAD")]);
    await t.settle();
    expect(t.last().BAD.state).toBe("error");
    expect(t.last().BAD.error).toMatch(/^SCRIPT BAD: UNKNOWN NAME NOSUCH \(LINE 2:\d+\)/);
    expect(t.series).toHaveLength(0);
  });

  it("a run-time error names the bar and still draws what ran before it", async () => {
    h.sources.R = H + 'x = array.new(1, 0)\nplot(close < 3 ? close : array.get(x, 5), "c")\n';
    const t = setup();
    t.ctl.sync([ref("R")]);
    await t.settle();
    expect(t.last().R.state).toBe("ready");
    expect(t.last().R.error).toMatch(/^SCRIPT R: .* \(LINE 3:\d+, BAR 2\)/);
  });

  it("a bad input value is reported by input name", async () => {
    h.sources.A = H + 'n = input.int(2, "Length")\nplot(ta.sma(close, n), "m")\n';
    const t = setup();
    t.ctl.sync([ref("A", ["x"])]);
    await t.settle();
    expect(t.last().A.error).toBe("SCRIPT A: LENGTH NEEDS A NUMBER");
  });

  it("scripts are off (with the reason, per script) while a % overlay is on", async () => {
    h.sources.A = H + 'plot(close, "c")\n';
    const t = setup();
    t.ctl.sync([ref("A")], "OFF WHILE A % OVERLAY (VS) IS ON");
    await t.settle();
    expect(t.last().A.error).toBe("SCRIPT A: OFF WHILE A % OVERLAY (VS) IS ON");
    expect(t.posted).toHaveLength(0);
  });

  it("a failed request fetch is an error line, not a blank chart", async () => {
    h.sources.A = H + 'plot(request("MSFT", "1D", close), "m")\n';
    h.history.mockRejectedValue(new Error("PROVIDER DOWN"));
    const t = setup();
    t.ctl.sync([ref("A")]);
    await t.settle();
    expect(t.last().A.error).toBe("SCRIPT A: REQUEST DATA FAILED: PROVIDER DOWN");
  });
});

describe("request(...) of another symbol", () => {
  it("fetches the other symbol's bars with the history client, then runs", async () => {
    h.sources.A = H + 'plot(request("MSFT", "1D", close), "m")\n';
    const m = barsFromCloses([10, 20, 30, 40, 50]);
    h.history.mockResolvedValue({ data: { t: m.t, o: m.o, h: m.h, l: m.l, c: m.c, v: m.v } });
    const t = setup();
    t.ctl.sync([ref("A")]);
    await t.settle();
    expect(h.history).toHaveBeenCalledWith("MSFT", "1Y", "1d");
    expect(t.last().A.state).toBe("ready");
    expect((t.series[0].data[4] as { value: number }).value).toBe(50);
  });
});

describe("live ticks", () => {
  const src = H + 'plot(close, "c")\nplotshape(close > 5, "big")\nif barstate.islast and close > 5\n    alert("big " + str.tostring(close))\n';
  const bar = (c: number, t: number) => ({ t, o: c, h: c + 1, l: c - 1, c, v: 10 });

  it("updates only the newest point, re-makes the newest mark, and fires the alert (never from the first run)", async () => {
    h.sources.A = src;
    const t = setup();
    t.ctl.sync([ref("A")]);
    await t.settle();
    expect(h.fired).toHaveLength(0); // the history run fires nothing
    const lastT = t.data.t[4];
    t.ctl.onLive(bar(7, lastT), false);
    await t.settle();
    expect(t.series[0].updates).toEqual([{ time: lastT, value: 7 }]);
    expect(h.fired).toEqual([{ symbol: "AAPL", script: "A", message: "big 7", barTime: lastT, synthetic: true }]);
    expect(t.marks[t.marks.length - 1]).toHaveLength(1);
    t.ctl.onLive(bar(3, lastT), false);
    await t.settle();
    expect(t.marks[t.marks.length - 1]).toHaveLength(0); // condition false again: mark gone
    expect(t.series[0].data).toHaveLength(5); // history was not re-sent
  });

  it("a new bar is appended, not an update of the old newest bar", async () => {
    h.sources.A = src;
    const t = setup();
    t.ctl.sync([ref("A")]);
    await t.settle();
    const next = t.data.t[4] + 86400;
    t.ctl.onLive(bar(8, next), true);
    await t.settle();
    expect(t.series[0].updates).toEqual([{ time: next, value: 8 }]);
    expect(h.fired[0]).toMatchObject({ message: "big 8", barTime: next });
  });

  it("an alert already true when the script first ran is state, not news", async () => {
    h.sources.A = H + 'if barstate.islast\n    alert("on load")\n';
    const t = setup();
    t.ctl.sync([ref("A")]);
    await t.settle();
    t.ctl.onLive(bar(5, t.data.t[4]), false);
    await t.settle();
    expect(h.fired).toHaveLength(0);
  });

  it("ticks that arrive while one is in flight merge: one update with the latest values, and an opened bar is not lost", async () => {
    h.sources.A = H + 'plot(close, "c")\n';
    const t = setup();
    t.ctl.sync([ref("A")]);
    await t.settle();
    const before = t.posted.length;
    const next = t.data.t[4] + 86400;
    // three ticks in the same turn: the first goes out at once, the rest merge into one waiting tick
    t.ctl.onLive(bar(6, t.data.t[4]), false);
    t.ctl.onLive(bar(7, next), true);
    t.ctl.onLive(bar(9, next), false);
    expect(t.posted.length - before).toBe(1);
    await t.settle();
    expect(t.posted.length - before).toBe(2);
    expect(t.series[0].updates.map((u) => (u as { value: number }).value)).toEqual([6, 9]);
  });

  it("a tick for a chart that was rebuilt is dropped (the answer belongs to the old series)", async () => {
    h.sources.A = H + 'plot(close, "c")\n';
    const t = setup();
    t.ctl.sync([ref("A")]);
    await t.settle();
    t.ctl.onLive(bar(6, t.data.t[4]), false);
    t.ctl.reset();
    await t.settle();
    expect(t.series[0].updates).toEqual([]);
  });
});
