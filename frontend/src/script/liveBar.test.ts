import { describe, expect, it } from "vitest";
import { compile } from "./index";
import {
  addPrice, applyFold, compileErrorText, DAY, findCondition, foldOf, messagesToFire, noConditionText, requestRange, runErrorText, seedKey, toCols,
  type LastBar,
} from "./liveBar";

const last: LastBar = { t: 1_000 * DAY + 52_200, o: 100, h: 105, l: 99, c: 102, v: 5000 };

describe("toCols", () => {
  it("drops rows with a missing price or time and zeroes a missing volume", () => {
    const cols = toCols({ t: [1, 2, 3, 4], o: [1, null, 3, 4], h: [1, 2, 3, 4], l: [1, 2, 3, 4], c: [1, 2, 3, null], v: [10, 20, null, 40] });
    expect(cols).toEqual({ o: [1, 3], h: [1, 3], l: [1, 3], c: [1, 3], v: [10, 0], t: [1, 3] });
  });
  it("is null when nothing is left", () => {
    expect(toCols({ t: [], o: [], h: [], l: [], c: [], v: [] })).toBeNull();
    expect(toCols({ t: [1], o: [null], h: [1], l: [1], c: [1], v: [1] })).toBeNull();
  });
});

describe("applyFold: prices into the newest daily bar", () => {
  it("inside the day: keeps open and volume, widens high / low, close = latest price", () => {
    const f = addPrice(addPrice(foldOf(103), 110), 98);
    const r = applyFold(last, f, last.t + 3_600);
    expect(r.append).toBe(false);
    expect(r.bar).toEqual({ t: last.t, o: 100, h: 110, l: 98, c: 98, v: 5000 });
  });
  it("a price inside the range changes only the close", () => {
    expect(applyFold(last, foldOf(101), last.t + 10).bar).toEqual({ ...last, c: 101 });
  });
  it("a whole day after the bar opened: a new bar at the same time of day, volume 0", () => {
    const f = addPrice(foldOf(103), 104);
    const r = applyFold(last, f, last.t + DAY + 60);
    expect(r.append).toBe(true);
    expect(r.bar).toEqual({ t: last.t + DAY, o: 103, h: 104, l: 103, c: 104, v: 0 });
  });
  it("after a weekend the new bar is a whole number of days later (not a bar per day)", () => {
    const r = applyFold(last, foldOf(110), last.t + 3 * DAY + 30_000);
    expect(r.append).toBe(true);
    expect(r.bar.t).toBe(last.t + 3 * DAY);
  });
  it("the exact moment a day is over opens the next bar; one second before does not", () => {
    expect(applyFold(last, foldOf(101), last.t + DAY - 1).append).toBe(false);
    expect(applyFold(last, foldOf(101), last.t + DAY).append).toBe(true);
  });
});

describe("messagesToFire", () => {
  const conds = [{ title: "RSI down", message: "RSI fell" }, { title: "Gap", message: "" }];
  const tick = (alerts: string[], conditions: number[]) => ({ alerts: alerts.map((message) => ({ bar: 9, message })), conditions });

  it("no COND: only the script's own alert() calls", () => {
    expect(messagesToFire(tick(["a", "b"], [1, 1]), conds, null)).toEqual(["a", "b"]);
    expect(messagesToFire(tick([], [1, 1]), conds, null)).toEqual([]);
  });
  it("a COND: that condition when it is 1, with its message (else its title); alert() calls are not used", () => {
    expect(messagesToFire(tick(["a"], [1, 0]), conds, "RSI down")).toEqual(["RSI fell"]);
    expect(messagesToFire(tick([], [0, 1]), conds, "Gap")).toEqual(["Gap"]);
    expect(messagesToFire(tick(["a"], [0, 0]), conds, "RSI down")).toEqual([]);
  });
  it("a title the script no longer has gives nothing", () => {
    expect(messagesToFire(tick([], [1, 1]), conds, "Gone")).toEqual([]);
  });
});

describe("conditions and wording", () => {
  const conds = [{ title: "RSI down" }, { title: "Gap" }];
  it("matches a typed title ignoring case and outer spaces, answering with the script's own spelling", () => {
    expect(findCondition(conds, " rsi DOWN ")).toBe("RSI down");
    expect(findCondition(conds, "up")).toBeNull();
  });
  it("names the choices when the title is wrong", () => {
    expect(noConditionText("up", "RSI-X", conds)).toBe('NO CONDITION "up" IN RSI-X (HAS: RSI down, Gap)');
    expect(noConditionText("up", "RSI-X", [])).toBe('NO CONDITION "up" IN RSI-X (HAS: NONE)');
  });
  it("writes compile and run errors with line numbers", () => {
    expect(compileErrorText("A", { msg: "EXPECTED )", line: 3, col: 5 })).toBe("SCRIPT A DOES NOT COMPILE: LINE 3:5 EXPECTED )");
    expect(runErrorText({ msg: "BAD", line: 4, bar: 12 })).toBe("SCRIPT ERROR AT BAR 12: BAD (LINE 4)");
  });
  it("asks history for the right range per request timeframe, and refuses short ones", () => {
    expect(requestRange("1D")).toEqual({ range: "1Y", interval: "1d" });
    expect(requestRange("1W")).toEqual({ range: "5Y", interval: "1wk" });
    expect(requestRange("5m")).toBeNull();
    expect(seedKey(5, "x")).toBe("5|x");
  });
});

// The whole path with the real engine: history run (no firing), then live updates of the newest bar.
describe("a script alert end to end on the engine", () => {
  const SRC = [
    'indicator("Cross", overlay=true)',
    "up = close > 105",
    'alertcondition(up, "Broke 105", "price above 105")',
    'if up and not up[1]',
    '  alert("crossed 105")',
    "plot(close)",
  ].join("\n");

  it("fires once on the live bar that crosses, never for history, and again only on a new bar", () => {
    const c = compile(SRC);
    if (!c.ok) throw new Error(JSON.stringify(c.errors));
    const days = 20;
    const t0 = 20_000 * DAY + 52_200;
    const cols = { o: [] as number[], h: [] as number[], l: [] as number[], c: [] as number[], v: [] as number[], t: [] as number[] };
    for (let i = 0; i < days; i++) {
      cols.o.push(100); cols.h.push(101); cols.l.push(99); cols.c.push(100); cols.v.push(1); cols.t.push(t0 + i * DAY);
    }
    const rs = c.program.run(cols, { chartTimeframe: "1D" });
    const first = rs.tick();
    expect(messagesToFire(first, c.program.meta.conditions, null)).toEqual([]); // nothing true in history
    expect(messagesToFire(first, c.program.meta.conditions, "Broke 105")).toEqual([]);

    let bar: LastBar = { t: cols.t[days - 1], o: 100, h: 101, l: 99, c: 100, v: 1 };
    const live = (price: number, nowSec: number) => {
      const r = applyFold(bar, foldOf(price), nowSec);
      if (r.append) rs.append(r.bar);
      else rs.updateLast(r.bar);
      bar = r.bar;
      return rs.tick();
    };
    const now = bar.t + 3_600;
    expect(messagesToFire(live(103, now), c.program.meta.conditions, null)).toEqual([]);
    const crossed = live(107, now + 1);
    expect(messagesToFire(crossed, c.program.meta.conditions, null)).toEqual(["crossed 105"]);
    expect(messagesToFire(crossed, c.program.meta.conditions, "Broke 105")).toEqual(["price above 105"]);
    // the same bar again (another tick): the engine reports it again, fireScriptAlert's once-per-bar key is what keeps it quiet
    expect(messagesToFire(live(108, now + 2), c.program.meta.conditions, null)).toEqual(["crossed 105"]);
    // price falls back below 105 (the bar closes at 100), the next day opens above 105: a cross on a NEW bar fires again
    live(100, now + 3);
    expect(messagesToFire(live(109, bar.t + DAY + 10), c.program.meta.conditions, null)).toEqual(["crossed 105"]);
    expect(bar.t).toBe(cols.t[days - 1] + DAY);
  });
});
